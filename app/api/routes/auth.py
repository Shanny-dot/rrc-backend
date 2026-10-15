from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from typing import Optional
from slowapi import Limiter
from app.core.client_ip import client_ip
from app.core.config import settings
from app.core.supabase_client import supabase_anon, supabase_admin
from app.core.auth_middleware import get_current_user, issue_app_token
from app.core.apple_auth import verify_apple_identity_token
from app.core.social_verify import (
    google_enabled, facebook_enabled, verify_google_id_token, verify_facebook_access_token,
)
from app.services.program_service import tier_status
from app.schemas.user import UserCreate, UserUpdate, TokenResponse
from app.services.email_service import EmailService
from app.services.points_service import PointsService
from app.services.sms_service import SmsService, format_mobile
from app.services.invite_service import link_new_member
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
    try:
        PointsService.award_points(user_id=user_id, points=100, type="signup_bonus", description="Welcome Bonus")
        supabase_admin.table("users").update({"bonus_points_granted": True}).eq("id", user_id).execute()
    except Exception as e:
        print(f"Welcome bonus warning (profile repair): {e}")
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
        supabase_admin.table("users").insert({
            "id": user_id,
            "email": email,
            "full_name": (full_name or email.split("@")[0]).strip(),
            "referral_code": generate_referral_code(),
            "profile_complete": False,
        }).execute()
        try:
            PointsService.award_points(user_id=user_id, points=100, type="signup_bonus", description="Welcome Bonus")
            supabase_admin.table("users").update({"bonus_points_granted": True}).eq("id", user_id).execute()
        except Exception as e:
            print(f"Welcome bonus warning ({provider}): {e}")
        if referral_code:
            link_new_member(user_id, referral_code, full_name, email=email)
    token = issue_app_token(user_id, email)
    return {"access_token": token, "refresh_token": token, "token_type": "bearer"}


@router.post("/social-login", response_model=TokenResponse)
def social_login(creds: SocialLoginRequest):
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
                    "profile_complete": False
                }).execute()
                if creds.referral_code:
                    link_new_member(user.id, creds.referral_code, full_name, email=user.email)

            return {
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "token_type": "bearer"
            }
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
                    "profile_complete": False
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

    raise HTTPException(status_code=400, detail="Social authentication failed. Please try again.")

@router.post("/register", response_model=TokenResponse)
@limiter.limit("5/minute")
def register(request: Request, creds: RegisterCredentials):
    try:
        if not creds.mobile:
             raise HTTPException(status_code=400, detail="Mobile number is required for SMS auth")
             
        # 1. Sign up with Supabase Auth bypassing Rate Limits (Admin API)
        # Bypasses the 3 emails/hour GoTrue limits
        try:
            auth_response = supabase_admin.auth.admin.create_user({
                "email": creds.email,
                "password": creds.password,
                "email_confirm": True,
                "user_metadata": {
                    "full_name": creds.full_name,
                }
            })
            user = auth_response.user
        except Exception as create_err:
            if "already exists" in str(create_err).lower():
                raise HTTPException(status_code=400, detail="An account with this email already exists.")
            raise create_err
        
        if not user:
            raise HTTPException(status_code=400, detail="Signup failed")
        
        # 2. Create public.users profile record
        unique_ref_code = generate_referral_code()
        
        user_data = {
            "id": user.id, # Link directly to the Auth UUID
            "full_name": creds.full_name,
            "email": creds.email,
            "mobile": creds.mobile,
            "referral_code": unique_ref_code,
            "total_points": 0,
            "bonus_points_granted": False
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
        # 5. Send verification OTP via Guni SMS
        try:
            SmsService.send_otp(creds.mobile)
        except Exception as otp_err:
            print(f"SMS OTP trigger skipped/error: {otp_err}")
        
        # 6. Award 100 pt Signup Bonus
        try:
            PointsService.award_points(
                user_id=user.id,
                points=100,
                type="signup_bonus",
                description="Welcome Bonus"
            )
            supabase_admin.table("users").update({"bonus_points_granted": True}).eq("id", user.id).execute()
        except Exception as pts_err:
            print(f"Points award warning: {pts_err}")
        
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

        token = issue_app_token(user_row["id"], user_row.get("email"))
        return {"success": True, "message": "Mobile number verified", "access_token": token}

    except HTTPException as e:
         raise e
    except Exception as e:
         raise HTTPException(status_code=400, detail=str(e))

@router.post("/login", response_model=TokenResponse)
def login(request: Request, creds: LoginCredentials):
    clean_email = creds.email.strip().lower()
    clean_password = creds.password.strip()

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
        raise HTTPException(status_code=400, detail="Invalid login credentials")

    user = auth_response.user or auth_response.session.user
    meta = getattr(user, "user_metadata", None) or {}
    member_id = _ensure_profile(str(user.id), user.email or clean_email, meta.get("full_name", ""))
    if member_id != str(user.id):
        # Profile is stored under a different id than the Supabase account: use a backend
        # token for that member so every screen finds the right profile.
        return TokenResponse(access_token=issue_app_token(member_id, user.email or clean_email))
    return TokenResponse(access_token=auth_response.session.access_token)

@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest):
    email = req.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email address is required")
        
    try:
        # The link opens the "Set a new password" page on the admin site, which works
        # on any phone or computer (the app itself has no reset screen).
        redirect_to = f"{str(settings.FRONTEND_URL).rstrip('/')}/reset-password"
        supabase_anon.auth.reset_password_for_email(email, {"redirect_to": redirect_to})
        return {"success": True, "message": "Password reset instructions sent to your email address."}
    except Exception as e:
        print("Forgot password error:", e)
        return {"success": True, "message": "If an account exists with this email, password reset instructions have been sent."}

@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    resp = supabase_admin.table("users").select("*").eq("id", user_id).execute()
    if not resp.data and current_user.get("email"):
        _ensure_profile(user_id, current_user.get("email"), (current_user.get("user_metadata") or {}).get("full_name", ""))
        resp = supabase_admin.table("users").select("*").eq("id", user_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="User not found")
    me = dict(resp.data[0])
    try:
        me["tier"] = tier_status(user_id, me.get("total_points") or 0)
    except Exception as e:
        print(f"Tier status warning: {e}")
        me["tier"] = None
    return me

@router.put("/profile")
def update_profile(profile: UserUpdate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    
    update_data = {k: v for k, v in profile.dict(exclude_unset=True).items()}
    
    if update_data:
         # Automatically mark profile as completed when profile details are saved
         update_data["profile_complete"] = True
         resp = supabase_admin.table("users").update(update_data).eq("id", user_id).execute()
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
        # Delete from public.users (triggers DB cascade deletes)
        supabase_admin.table("users").delete().eq("id", user_id).execute()
        # Delete from auth.users (Supabase Auth)
        supabase_admin.auth.admin.delete_user(user_id)
        return {"success": True, "message": "Account deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to delete account: {str(e)}")
