from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel
from typing import Optional
from slowapi import Limiter
from app.core.client_ip import client_ip
from app.core.config import settings
from app.core.supabase_client import supabase_anon, supabase_admin
from app.core.auth_middleware import get_current_user, issue_app_token
from app.core import login_guard
from app.core.apple_auth import verify_apple_identity_token
from app.core.social_verify import (
    google_enabled, facebook_enabled, verify_google_id_token, verify_facebook_access_token,
)
from app.services.program_service import tier_status, get_int_setting, get_setting
from app.schemas.user import UserCreate, UserUpdate, TokenResponse
from app.services.email_service import EmailService
from app.services.points_service import PointsService
from app.services.sms_service import SmsService, format_mobile, issue_code, code_matches
from app.services.invite_service import link_new_member, is_launch_code, clean_code
from app.services.notify_service import PREF_KEYS, prefs_for
import random
import string
import time
import uuid
import jwt

router = APIRouter()
limiter = Limiter(key_func=client_ip)

class RegisterCredentials(BaseModel):
    full_name: str
    email: str
    password: str
    mobile: Optional[str] = None
    referral_code: Optional[str] = None

_COMMON_PASSWORDS = {"password", "password1", "password123", "12345678", "123456789", "1234567890", "qwerty123",
                     "iloveyou", "11111111", "00000000", "abcd1234", "reliiance", "reliance", "rewards123"}


def password_problem(password: str, email: str = "") -> str:
    """A plain-English reason the password is too weak, or ''."""
    pw = password or ""
    if len(pw) < 8:
        return "Please choose a password with at least 8 characters."
    if pw.lower() in _COMMON_PASSWORDS or len(set(pw)) < 4:
        return "That password is too easy to guess. Please choose a different one."
    local = (email or "").split("@")[0].lower()
    if local and len(local) >= 4 and local in pw.lower():
        return "Please don't use your email address in your password."
    return ""


class LoginCredentials(BaseModel):
    email: str
    password: str

class ForgotPasswordRequest(BaseModel):
    email: str

class SocialLoginRequest(BaseModel):
    provider: str
    id_token: Optional[str] = None
    access_token: Optional[str] = None
    raw_nonce: Optional[str] = None
    referral_code: Optional[str] = None   # from a friend's invite link, for new members

class FCMTokenRequest(BaseModel):
    fcm_token: str

def generate_referral_code(length=8):
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for i in range(length))


def _welcome_points_for(row: dict) -> tuple:
    """(points, description) for a new member (amounts set on the admin Program settings page):
    members who signed up with the launch QR code get the launch bonus instead of the welcome
    points. Either can be 0 (none)."""
    if is_launch_code(row.get("signup_code") or ""):
        return get_int_setting("launch_bonus_points"), "Welcome Bonus"
    return get_int_setting("welcome_points"), "Welcome Bonus"


def _has_signup_bonus(user_id: str) -> bool:
    return bool(supabase_admin.table("transactions").select("id").eq("user_id", user_id)
                .eq("type", "signup_bonus").execute().data)


def _award_welcome_points(user_id: str, label: str = "", row: dict = None):
    """Points given (0 when none are due), or None if they couldn't be added. On launch day the
    database was briefly unreachable under load and bonuses were silently lost, so retry a few
    times — never paying twice — before giving up."""
    import time
    points, description = _welcome_points_for(row or {})
    if points <= 0:
        return 0
    for attempt in range(3):
        try:
            if attempt and _has_signup_bonus(user_id):
                return points   # an earlier attempt got through
            PointsService.award_points(user_id=user_id, points=points, type="signup_bonus", description=description)
            supabase_admin.table("users").update({"bonus_points_granted": True}).eq("id", user_id).execute()
            return points
        except Exception as e:
            print(f"Welcome bonus warning {label} (attempt {attempt + 1}): {e}")
            time.sleep(0.5 * (attempt + 1))
    return None


SIGNUP_LABELS = {"email": "(register)", "google": "(google)", "apple": "(apple)", "facebook": "(facebook)"}


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _finish_signup_if_verified(user_id: str):
    """Once a new member's mobile and email are both verified: welcome points and email, and
    the "new member" email to staff — exactly once. Returns the points given, or None if the
    member isn't fully verified yet (or was already welcomed)."""
    rows = supabase_admin.table("users").select("*").eq("id", user_id).execute().data or []
    row = rows[0] if rows else None
    if (not row or row.get("deleted_at") or row.get("welcomed_at")
            or not (row.get("mobile_verified_at") and row.get("email_verified_at"))):
        return None
    # Claim the welcome first, so two verifications arriving together can't both award it.
    claimed = supabase_admin.table("users").update({"welcomed_at": _now_iso()}) \
        .eq("id", user_id).is_("welcomed_at", "null").execute().data
    if not claimed:
        return None
    label = SIGNUP_LABELS.get(row.get("signup_method") or "email", "(register)")
    points = _award_welcome_points(user_id, label, row)
    if points is None:
        # Couldn't add the points: release the claim so the next app open tries again
        # (GET /auth/me), rather than leaving the member welcomed without their bonus.
        try:
            supabase_admin.table("users").update({"welcomed_at": None}).eq("id", user_id).execute()
        except Exception as e:
            print(f"Welcome release warning {label}: {e}")
        return None
    inviter = None
    if row.get("referred_by"):
        found = supabase_admin.table("users").select("full_name").eq("id", row["referred_by"]).execute().data or []
        inviter = found[0] if found else None
    inviter_name = ((inviter or {}).get("full_name") or "").strip() or None
    if row.get("email"):
        EmailService.send_welcome_email(row["email"], row.get("full_name"), row.get("referral_code"), points, inviter_name)
    EmailService.send_staff_new_member(row.get("full_name"), row.get("email"), row.get("mobile"), points, inviter_name, label)
    return points


def _email_subject(email: str) -> str:
    return f"email:{(email or '').strip().lower()}"


def _send_email_code(email: str, full_name: str) -> bool:
    return EmailService.send_verification_code(email, full_name, issue_code(_email_subject(email)))


def _email_code_matches(email: str, code: str) -> bool:
    return code_matches(_email_subject(email), code, windows=3)  # 10-15 minutes: emails can be slow


def _verification_status(row: dict) -> dict:
    """What the app shows on the "Verify your account" card."""
    pending = None
    if not row.get("welcomed_at"):
        pending = _welcome_points_for(row)[0]
    return {
        "mobile_verified": bool(row.get("mobile_verified_at")),
        "email_verified": bool(row.get("email_verified_at")),
        "verified": bool(row.get("mobile_verified_at") and row.get("email_verified_at")),
        "pending_welcome_points": pending,
    }

def _ensure_profile(user_id: str, email: str, full_name: str = "") -> str:
    """Make sure a signed-in Supabase account has its public.users member profile.

    Some accounts exist in Supabase Auth without a profile (an older registration that
    failed half-way, or a profile removed by hand); they could sign in but every screen
    then failed with "User not found". Returns the member id to use for the session:
    normally user_id, or the id of an existing profile with the same email."""
    email = (email or "").strip().lower()
    by_id = supabase_admin.table("users").select("id, deleted_at").eq("id", user_id).execute()
    if by_id.data:
        if by_id.data[0].get("deleted_at"):
            raise HTTPException(status_code=403, detail="This account has been deleted.")
        return user_id
    if email:
        by_email = supabase_admin.table("users").select("id, deleted_at").eq("email", email).execute()
        if by_email.data:
            if by_email.data[0].get("deleted_at"):
                raise HTTPException(status_code=403, detail="This account has been deleted.")
            return by_email.data[0]["id"]
    supabase_admin.table("users").insert({
        "id": user_id,
        "email": email,
        "full_name": (full_name or email.split("@")[0] or "Member").strip(),
        "referral_code": generate_referral_code(),
        "profile_complete": False,
    }).execute()
    # Welcome points follow once they verify their mobile and email in the app.
    return user_id


def _sign_in_social_member(email: str, full_name: str, provider: str, referral_code: str = None) -> dict:
    """Find the member with this verified email, or create one (with the welcome bonus),
    and return a backend session token."""
    email = email.strip().lower()
    existing = supabase_admin.table("users").select("id, deleted_at").eq("email", email).execute()
    if existing.data:
        if existing.data[0].get("deleted_at"):
            raise HTTPException(status_code=403, detail="This account has been deleted.")
        user_id = existing.data[0]["id"]
    else:
        user_id = str(uuid.uuid4())
        code = generate_referral_code()
        supabase_admin.table("users").insert({
            "id": user_id,
            "email": email,
            "full_name": (full_name or email.split("@")[0]).strip(),
            "referral_code": code,
            "profile_complete": False,
            "signup_method": provider,
            "signup_code": clean_code(referral_code) if referral_code else None,
            "email_verified_at": _now_iso(),  # Google / Facebook confirmed the address
        }).execute()
        if referral_code:
            link_new_member(user_id, referral_code, full_name, email=email)
        # Welcome points follow once they add and verify a mobile number in the app.
    token = issue_app_token(user_id, email)
    return {"access_token": token, "refresh_token": token, "token_type": "bearer"}


@router.post("/social-login", response_model=TokenResponse)
@limiter.limit("20/minute")
def social_login(request: Request, creds: SocialLoginRequest):
    # 0. Google and Facebook are verified directly with Google / Facebook when configured.
    if creds.provider in ("google", "facebook"):
        enabled = google_enabled() if creds.provider == "google" else facebook_enabled()
        if not enabled:
            raise HTTPException(status_code=400, detail="This sign-in option isn't set up yet. Please use email.")
        try:
            profile = (verify_google_id_token(creds.id_token) if creds.provider == "google"
                       else verify_facebook_access_token(creds.access_token))
        except ValueError as e:
            print(f"{creds.provider} sign-in rejected: {e}")
            raise HTTPException(status_code=401, detail=str(e) if "email" in str(e).lower() else
                                f"{creds.provider.capitalize()} sign-in failed. Please try again.")
        return _sign_in_social_member(profile["email"], profile["name"], creds.provider, creds.referral_code)
    # 1. Attempt standard Supabase social verification
    try:
        auth_response = supabase_anon.auth.sign_in_with_id_token({
            "provider": creds.provider,
            "id_token": creds.id_token,
            "access_token": creds.access_token,
            "nonce": creds.raw_nonce
        })

        session = auth_response.session
        user = auth_response.user

        if session and user:
            user_db = supabase_admin.table("users").select("*").eq("id", user.id).execute()
            if not user_db.data:
                ref_code = generate_referral_code()
                full_name = "User"
                if user.user_metadata and "full_name" in user.user_metadata:
                    full_name = user.user_metadata["full_name"]
                elif user.email:
                    full_name = user.email.split("@")[0]

                supabase_admin.table("users").insert({
                    "id": user.id,
                    "email": user.email,
                    "full_name": full_name,
                    "referral_code": ref_code,
                    "profile_complete": False,
                    "signup_method": creds.provider,
                    "signup_code": clean_code(creds.referral_code) if creds.referral_code else None,
                    "email_verified_at": _now_iso() if user.email else None,
                }).execute()
                if creds.referral_code:
                    link_new_member(user.id, creds.referral_code, full_name, email=user.email)

            # Long-lived backend token, so the member stays signed in (Supabase's expires in an hour).
            token = issue_app_token(str(user.id), user.email)
            return {"access_token": token, "refresh_token": token, "token_type": "bearer"}
    except Exception as e:
        print(f"Supabase social login attempt failed: {e}")

    # 2. Apple Sign-In fallback. The identity token's signature, issuer, audience,
    #    expiry and nonce are verified against Apple's published keys before it is trusted.
    if creds.provider == "apple" and creds.id_token:
        try:
            claims = verify_apple_identity_token(creds.id_token, creds.raw_nonce)
        except ValueError as verify_err:
            print(f"Apple fallback rejected: {verify_err}")
            raise HTTPException(status_code=401, detail="Apple authentication failed. Please try again.")

        try:
            apple_sub = claims["sub"]
            apple_email = claims.get("email") or f"apple_{apple_sub[:8]}@privaterelay.appleid.com"
            apple_email = apple_email.strip().lower()

            user_db = supabase_admin.table("users").select("id").eq("email", apple_email).execute()
            if user_db.data:
                user_id = user_db.data[0]["id"]
            else:
                user_id = str(uuid.uuid4())
                ref_code = generate_referral_code()
                supabase_admin.table("users").insert({
                    "id": user_id,
                    "email": apple_email,
                    "full_name": "Apple User",
                    "referral_code": ref_code,
                    "profile_complete": False,
                    "signup_method": "apple",
                    "signup_code": clean_code(creds.referral_code) if creds.referral_code else None,
                    # Apple confirmed a real address; a made-up placeholder must be replaced and verified.
                    "email_verified_at": _now_iso() if claims.get("email") else None,
                }).execute()
                if creds.referral_code:
                    link_new_member(user_id, creds.referral_code, "Apple User", email=apple_email)

            token = issue_app_token(user_id, apple_email)
            return {
                "access_token": token,
                "refresh_token": token,
                "token_type": "bearer"
            }
        except HTTPException:
            raise
        except Exception as apple_err:
            print(f"Apple fallback error: {apple_err}")
            raise HTTPException(status_code=400, detail="Apple authentication failed. Please try again.")

    # 3. Google Sign-In direct verification fallback
    if creds.provider == "google" and (creds.id_token or creds.access_token):
        try:
            google_info = None
            if creds.id_token:
                try:
                    import urllib.request
                    import json
                    req = urllib.request.Request(
                        f"https://oauth2.googleapis.com/tokeninfo?id_token={creds.id_token}",
                        headers={"User-Agent": "RRC-Backend"}
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        if resp.status == 200:
                            google_info = json.loads(resp.read().decode("utf-8"))
                except Exception as t_err:
                    print(f"Google tokeninfo fetch failed: {t_err}")

                if not google_info:
                    claims = jwt.decode(creds.id_token, options={"verify_signature": False})
                    if claims.get("email"):
                        google_info = claims

            elif creds.access_token:
                try:
                    import urllib.request
                    import json
                    req = urllib.request.Request(
                        "https://www.googleapis.com/oauth2/v3/userinfo",
                        headers={"Authorization": f"Bearer {creds.access_token}", "User-Agent": "RRC-Backend"}
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        if resp.status == 200:
                            google_info = json.loads(resp.read().decode("utf-8"))
                except Exception as u_err:
                    print(f"Google userinfo fetch failed: {u_err}")

            if not google_info or not google_info.get("email"):
                raise Exception("Unable to verify Google credentials")

            google_sub = google_info.get("sub") or str(uuid.uuid4())
            google_email = google_info.get("email").strip().lower()
            google_name = google_info.get("name") or google_email.split("@")[0].capitalize()

            user_db = supabase_admin.table("users").select("*").or_(f"id.eq.{google_sub},email.eq.{google_email}").execute()
            if user_db.data:
                user_id = user_db.data[0]["id"]
            else:
                user_id = str(uuid.uuid4())
                ref_code = generate_referral_code()
                supabase_admin.table("users").insert({
                    "id": user_id,
                    "email": google_email,
                    "full_name": google_name,
                    "referral_code": ref_code,
                    "profile_complete": False
                }).execute()

            token = jwt.encode(
                {"sub": user_id, "email": google_email, "exp": int(time.time()) + 86400 * 30},
                "rrc_secret_jwt_key_2026",
                algorithm="HS256"
            )
            return {
                "access_token": token,
                "refresh_token": token,
                "token_type": "bearer"
            }
        except Exception as google_err:
            print(f"Google fallback error: {google_err}")
            raise HTTPException(status_code=400, detail=f"Google authentication error: {google_err}")

    raise HTTPException(status_code=400, detail="Social authentication failed. Please try again.")

ALREADY_MEMBER = ("You already have an account with this email. Please sign in instead, "
                  "or tap 'Forgot password' if you can't remember your password.")


def _email_taken(err: Exception) -> bool:
    msg = str(err).lower()
    return "already been registered" in msg or "already exists" in msg or "email_exists" in msg


def _reject_existing_member(email: str) -> None:
    """Stop sign-up when a member profile already uses this email."""
    email = email.strip()
    rows = supabase_admin.table("users").select("id, deleted_at").in_("email", list({email, email.lower()})).execute().data or []
    if any(not r.get("deleted_at") for r in rows):
        raise HTTPException(status_code=400, detail=ALREADY_MEMBER)
    if rows:
        raise HTTPException(status_code=400, detail="This email belongs to a closed account. "
                            "Please contact membership@reliiancerewards.com.au to reopen it.")


def _orphan_login(email: str):
    """The Supabase login for this email, if it has no member profile."""
    email = email.strip().lower()
    page = 1
    while True:
        logins = supabase_admin.auth.admin.list_users(page=page, per_page=1000)
        match = next((u for u in logins if (u.email or "").lower() == email), None)
        if match or len(logins) < 1000:
            break
        page += 1
    if not match:
        return None
    if supabase_admin.table("users").select("id").eq("id", match.id).execute().data:
        return None
    return match


@router.post("/register", response_model=TokenResponse)
@limiter.limit("5/minute")
def register(request: Request, creds: RegisterCredentials):
    try:
        if not creds.mobile:
             raise HTTPException(status_code=400, detail="Mobile number is required for SMS auth")
        weak = password_problem(creds.password, creds.email)
        if weak:
            raise HTTPException(status_code=400, detail=weak)

        # 1. Sign up with Supabase Auth bypassing Rate Limits (Admin API)
        # Bypasses the 3 emails/hour GoTrue limits
        new_login = {
            "email": creds.email,
            "password": creds.password,
            "email_confirm": True,
            "user_metadata": {
                "full_name": creds.full_name,
            }
        }
        try:
            user = supabase_admin.auth.admin.create_user(new_login).user
        except Exception as create_err:
            if not _email_taken(create_err):
                raise create_err
            _reject_existing_member(creds.email)
            # A login with no member profile (left by an older app version or an
            # interrupted sign-up) holds the email: remove it and sign up afresh.
            orphan = _orphan_login(creds.email)
            if not orphan:
                raise HTTPException(status_code=400, detail=ALREADY_MEMBER)
            supabase_admin.auth.admin.delete_user(orphan.id)
            user = supabase_admin.auth.admin.create_user(new_login).user

        if not user:
            raise HTTPException(status_code=400, detail="Signup failed")

        # 2. Create public.users profile record
        unique_ref_code = generate_referral_code()

        user_data = {
            "id": user.id, # Link directly to the Auth UUID
            "full_name": creds.full_name,
            "email": creds.email.strip().lower(),
            "mobile": creds.mobile,
            "referral_code": unique_ref_code,
            "total_points": 0,
            "bonus_points_granted": False,
            "signup_method": "email",
            "signup_code": clean_code(creds.referral_code) if creds.referral_code else None,
        }

        # Insert user via admin to bypass constraints if needed on registration.
        # If the profile can't be created, remove the Supabase account again so the
        # person can simply retry (otherwise they'd be stuck with "already exists").
        try:
            supabase_admin.table("users").insert(user_data).execute()
        except Exception as profile_err:
            try:
                supabase_admin.auth.admin.delete_user(user.id)
            except Exception as cleanup_err:
                print(f"Registration cleanup warning: {cleanup_err}")
            raise profile_err

        # 3. Link to the member whose code (or invite link) they joined with
        if creds.referral_code:
            link_new_member(user.id, creds.referral_code, creds.full_name, email=creds.email, mobile=creds.mobile)
        # 4. Verification codes by SMS (Guni) and email. Welcome points and the welcome email
        #    follow once both are entered (/verify-signup).
        try:
            SmsService.send_otp(creds.mobile)
        except Exception as otp_err:
            print(f"SMS OTP trigger skipped/error: {otp_err}")
        _send_email_code(creds.email, creds.full_name)

        return TokenResponse(access_token="pending_verification")

    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Registration Error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

class ResendOTPRequest(BaseModel):
    mobile: str

@router.post("/resend-otp")
@limiter.limit("5/minute")
def resend_otp(request: Request, req: ResendOTPRequest):
    try:
        SmsService.send_otp(req.mobile)
        return {"success": True, "message": "OTP sent successfully"}
    except Exception as e:
        print(f"Resend OTP Error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

class VerifyMobileRequest(BaseModel):
    mobile: str
    code: str

@router.post("/verify-mobile")
@limiter.limit("10/minute")
def verify_mobile(request: Request, req: VerifyMobileRequest):
    try:
        if not SmsService.verify_otp(req.mobile, req.code):
             raise HTTPException(status_code=400, detail="Invalid OTP code or session expired")

        # Issue a backend token for the newest live account registered with this mobile
        formatted_mobile = format_mobile(req.mobile)
        user_db = supabase_admin.table("users").select("*").in_("mobile", list({formatted_mobile, req.mobile.strip()})) \
            .order("created_at", desc=True).execute()
        user_row = next((u for u in (user_db.data or []) if not u.get("deleted_at")), None)
        if not user_row:
             raise HTTPException(status_code=404, detail="No account found for this mobile number")

        if not user_row.get("mobile_verified_at"):
            supabase_admin.table("users").update({"mobile_verified_at": _now_iso()}).eq("id", user_row["id"]).execute()
        _finish_signup_if_verified(user_row["id"])
        token = issue_app_token(user_row["id"], user_row.get("email"))
        return {"success": True, "message": "Mobile number verified", "access_token": token}

    except HTTPException as e:
         raise e
    except Exception as e:
         raise HTTPException(status_code=400, detail=str(e))


def _member_by_email(email: str):
    email = (email or "").strip()
    if not email:
        return None
    rows = supabase_admin.table("users").select("*").in_("email", list({email, email.lower()})).execute().data or []
    return next((u for u in rows if not u.get("deleted_at")), None)


def _send_code(row: dict, channel: str) -> None:
    """Send a new SMS or email code to the member's own mobile / email on file."""
    if channel == "sms":
        if not row.get("mobile"):
            raise HTTPException(status_code=400, detail="Please add your mobile number first.")
        try:
            SmsService.send_otp(row["mobile"])
        except Exception as e:
            print(f"Send SMS code error: {e}")
            raise HTTPException(status_code=400, detail="We couldn't send a text message right now. Please try again shortly.")
    elif channel == "email":
        if not row.get("email") or not _send_email_code(row["email"], row.get("full_name")):
            raise HTTPException(status_code=400, detail="We couldn't send the email right now. Please try again shortly.")
    else:
        raise HTTPException(status_code=400, detail="channel must be sms or email")


def _check_codes(row: dict, mobile_code: Optional[str], email_code: Optional[str]) -> None:
    """Mark whichever of mobile / email the codes confirm; 400 if anything is still unverified."""
    updates, wrong = {}, []
    if not row.get("mobile_verified_at"):
        if row.get("mobile") and mobile_code and SmsService.verify_otp(row["mobile"], mobile_code):
            updates["mobile_verified_at"] = _now_iso()
        else:
            wrong.append("mobile")
    if not row.get("email_verified_at"):
        if row.get("email") and email_code and _email_code_matches(row["email"], email_code):
            updates["email_verified_at"] = _now_iso()
        else:
            wrong.append("email")
    if updates:
        supabase_admin.table("users").update(updates).eq("id", row["id"]).execute()
        row.update(updates)
    if wrong:
        which = " and ".join({"mobile": "mobile", "email": "email"}[w] for w in wrong)
        raise HTTPException(status_code=400, detail=f"The {which} code is incorrect or has expired. Please check it or tap Resend.")


class SendCodeRequest(BaseModel):
    channel: str                  # "sms" or "email"
    email: Optional[str] = None   # sign-up screen (not signed in yet)


@router.post("/send-code")
@limiter.limit("5/minute")
def send_code(request: Request, req: SendCodeRequest):
    """Resend a sign-up code. The reply is the same for unknown addresses."""
    row = _member_by_email(req.email)
    if row and not row.get("mobile_verified_at" if req.channel == "sms" else "email_verified_at"):
        _send_code(row, req.channel)
    return {"success": True}


class VerifySignupRequest(BaseModel):
    email: str
    mobile_code: Optional[str] = None
    email_code: Optional[str] = None


@router.post("/verify-signup")
@limiter.limit("10/minute")
def verify_signup(request: Request, req: VerifySignupRequest):
    """Both codes from the sign-up screen. When mobile and email are both verified the member
    gets their welcome points and is signed in."""
    row = _member_by_email(req.email)
    if not row:
        raise HTTPException(status_code=404, detail="No account found for this email address")
    # Signs the member in only by confirming a code now. An account that's already verified has
    # nothing to confirm, so it must sign in normally (otherwise its email alone would sign in).
    if row.get("mobile_verified_at") and row.get("email_verified_at"):
        raise HTTPException(status_code=400, detail="This account is already verified. Please sign in with your "
                                                    "email and password.")
    _check_codes(row, req.mobile_code, req.email_code)
    points = _finish_signup_if_verified(row["id"])
    return {"success": True, "access_token": issue_app_token(row["id"], row.get("email")), "points_added": points or 0}


@router.get("/verification")
def get_verification(current_user: dict = Depends(get_current_user)):
    rows = supabase_admin.table("users").select("*").eq("id", current_user.get("sub")).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    return {**_verification_status(rows[0]), "mobile": rows[0].get("mobile"), "email": rows[0].get("email")}


class MyCodeRequest(BaseModel):
    channel: str
    code: Optional[str] = None


@router.post("/verification/send")
@limiter.limit("5/minute")
def send_my_code(request: Request, req: MyCodeRequest, current_user: dict = Depends(get_current_user)):
    """For members who skipped a code at sign-up (or changed their mobile): send a new one."""
    rows = supabase_admin.table("users").select("*").eq("id", current_user.get("sub")).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    _send_code(rows[0], req.channel)
    return {"success": True}


@router.post("/verification/check")
@limiter.limit("10/minute")
def check_my_code(request: Request, req: MyCodeRequest, current_user: dict = Depends(get_current_user)):
    rows = supabase_admin.table("users").select("*").eq("id", current_user.get("sub")).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    row = rows[0]
    if req.channel not in ("sms", "email"):
        raise HTTPException(status_code=400, detail="channel must be sms or email")
    try:
        _check_codes(row, req.code if req.channel == "sms" else None, req.code if req.channel == "email" else None)
    except HTTPException:
        # Only the channel being checked matters here; the other may simply not be done yet.
        done = row.get("mobile_verified_at" if req.channel == "sms" else "email_verified_at")
        if not done:
            raise HTTPException(status_code=400, detail="That code is incorrect or has expired. Please check it or tap Resend.")
    points = _finish_signup_if_verified(row["id"])
    fresh = supabase_admin.table("users").select("*").eq("id", row["id"]).execute().data[0]
    return {**_verification_status(fresh), "points_added": points or 0}

@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, creds: LoginCredentials):
    clean_email = creds.email.strip().lower()
    clean_password = creds.password.strip()
    login_guard.check_login_allowed(clean_email)

    # The App Store review demo account signs in through Supabase like any other
    # member; it no longer has a hard-coded password or a backend-minted fallback token.
    try:
        auth_response = supabase_anon.auth.sign_in_with_password({
            "email": clean_email,
            "password": clean_password
        })
        if not auth_response.session:
             raise Exception("Invalid credentials")
    except Exception:
        login_guard.record_login_failure(clean_email)
        raise HTTPException(status_code=400, detail="Invalid login credentials")
    login_guard.record_login_success(clean_email)

    user = auth_response.user or auth_response.session.user
    meta = getattr(user, "user_metadata", None) or {}
    member_id = _ensure_profile(str(user.id), user.email or clean_email, meta.get("full_name", ""))
    # A long-lived backend token (also for the profile's own id), so members stay signed in:
    # Supabase's session token expires after an hour and the app has no way to renew it.
    return TokenResponse(access_token=issue_app_token(member_id, user.email or clean_email))


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(current_user: dict = Depends(get_current_user)):
    """Swap any valid sign-in token for a fresh long-lived one. The app calls this on start,
    so a member who opens the app now and then is never signed out."""
    return TokenResponse(access_token=issue_app_token(current_user["sub"], current_user.get("email")))


def _site_origin() -> str:
    """https://host of the admin website (FRONTEND_URL may point at a page such as /login)."""
    from urllib.parse import urlsplit
    url = str(settings.FRONTEND_URL or "https://admin.reliiancerewards.com.au")
    if "vercel.app" in url:
        return "https://admin.reliiancerewards.com.au"
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


@router.post("/forgot-password")
@limiter.limit("5/minute")
def forgot_password(request: Request, req: ForgotPasswordRequest):
    email = req.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email address is required")

    sent_message = {"success": True, "message": "If an account exists with this email, password reset instructions have been sent."}
    if not login_guard.reset_email_allowed(email):
        return sent_message   # same reply, so it doesn't reveal anything; stops inbox flooding
    # The link opens the "Set a new password" page on the admin site, which works
    # on any phone or computer (the app itself has no reset screen).
    redirect_to = f"{_site_origin()}/reset-password"
    from app.services.email_service import _EMAIL_ENABLED
    if _EMAIL_ENABLED:
        # Our own email from no-reply (branded), with a link made by Supabase.
        try:
            member = supabase_admin.table("users").select("full_name, deleted_at").eq("email", email).execute().data or []
            if member and member[0].get("deleted_at"):
                return sent_message
            link = supabase_admin.auth.admin.generate_link(
                {"type": "recovery", "email": email, "options": {"redirect_to": redirect_to}})
            action_link = link.properties.action_link
            if EmailService.send_password_reset(email, member[0].get("full_name") if member else "", action_link):
                return sent_message
        except Exception as e:
            # Unknown email addresses land here too; the reply is the same either way.
            print("Forgot password (own email) note:", e)
    # Fallback: Supabase's own reset email.
    try:
        supabase_anon.auth.reset_password_for_email(email, {"redirect_to": redirect_to})
    except Exception as e:
        print("Forgot password error:", e)
    return sent_message

@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    resp = supabase_admin.table("users").select("*").eq("id", user_id).execute()
    if not resp.data and current_user.get("email"):
        _ensure_profile(user_id, current_user.get("email"), (current_user.get("user_metadata") or {}).get("full_name", ""))
        resp = supabase_admin.table("users").select("*").eq("id", user_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="User not found")
    row = resp.data[0]
    if row.get("mobile_verified_at") and row.get("email_verified_at") and not row.get("welcomed_at"):
        # Verified but not welcomed: a welcome that failed earlier (e.g. under heavy load).
        if _finish_signup_if_verified(user_id) is not None:
            row = (supabase_admin.table("users").select("*").eq("id", user_id).execute().data or [row])[0]
    me = dict(row)
    try:
        me["tier"] = tier_status(user_id, me.get("total_points") or 0)
    except Exception as e:
        print(f"Tier status warning: {e}")
        me["tier"] = None
    me["verification"] = _verification_status(me)
    return me

@router.put("/profile")
def update_profile(profile: UserUpdate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")

    # mode="json" turns the date of birth into "YYYY-MM-DD"; a Python date can't be sent to
    # the database and made every save that included a date of birth fail.
    update_data = profile.model_dump(mode="json", exclude_unset=True)
    for key in ("full_name", "mobile"):
        if key in update_data and not (update_data[key] or "").strip():
            update_data.pop(key)  # never blank out the name or mobile by accident

    if update_data:
         before = (supabase_admin.table("users").select("full_name, email, mobile, dob").eq("id", user_id).execute().data or [{}])[0]
         # The date of birth is locked once saved (it drives the birthday bonus); staff can
         # still correct it on the admin website.
         if "dob" in update_data and before.get("dob"):
             if update_data["dob"] and str(update_data["dob"])[:10] != str(before["dob"])[:10]:
                 raise HTTPException(status_code=400, detail=(
                     "Your date of birth can't be changed once it's saved. If it's wrong, please contact us at "
                     "membership@reliiancerewards.com.au."))
             update_data.pop("dob")
         # Automatically mark profile as completed when profile details are saved
         update_data["profile_complete"] = True
         # A new mobile number has to be verified again (the email can't be changed here).
         if "mobile" in update_data and format_mobile(update_data["mobile"]) != format_mobile(before.get("mobile") or ""):
             update_data["mobile_verified_at"] = None
         resp = supabase_admin.table("users").update(update_data).eq("id", user_id).execute()
         # "Your details were updated — if this wasn't you, contact us" when contact details change
         changes = [(label, update_data[key]) for key, label in (("mobile", "Mobile number"), ("email", "Email address"))
                    if key in update_data and (update_data[key] or "") != (before.get(key) or "")]
         if changes and before.get("email"):
             EmailService.send_details_changed(before["email"], update_data.get("full_name") or before.get("full_name"), changes)
         return resp.data[0] if resp.data else {}
    return {"message": "No data provided"}

@router.put("/fcm-token")
def update_fcm_token(req: FCMTokenRequest, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    resp = supabase_admin.table("users").update({"fcm_token": req.fcm_token}).eq("id", user_id).execute()
    return {"message": "FCM token updated successfully"}

@router.delete("/account")
def delete_account(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    try:
        member = (supabase_admin.table("users").select("full_name, email").eq("id", user_id).execute().data or [{}])[0]
        # Closed, not erased: the member can no longer sign in or get messages, but their profile,
        # points and history stay so staff can restore the account (Deleted users > Restore).
        supabase_admin.table("users").update({"deleted_at": _now_iso(), "fcm_token": None}).eq("id", user_id).execute()
        if member.get("email"):
            EmailService.send_account_deleted(member["email"], member.get("full_name"))
        return {"success": True, "message": "Account deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to delete account: {str(e)}")


@router.get("/notification-prefs")
def get_notification_prefs(current_user: dict = Depends(get_current_user)):
    """Which phone alerts the member wants: {points, referrals, rewards, events, expiry, loan}."""
    rows = supabase_admin.table("users").select("notification_prefs").eq("id", current_user.get("sub")).execute().data
    return prefs_for(rows[0] if rows else {})


@router.put("/notification-prefs")
def update_notification_prefs(prefs: dict = Body(...), current_user: dict = Depends(get_current_user)):
    clean = {k: bool(v) for k, v in prefs.items() if k in PREF_KEYS}
    rows = supabase_admin.table("users").select("notification_prefs").eq("id", current_user.get("sub")).execute().data
    merged = {**((rows[0].get("notification_prefs") or {}) if rows else {}), **clean}
    supabase_admin.table("users").update({"notification_prefs": merged}).eq("id", current_user.get("sub")).execute()
    return prefs_for({"notification_prefs": merged})
