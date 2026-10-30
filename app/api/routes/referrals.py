import re
import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import List
from slowapi import Limiter
from app.core.client_ip import client_ip
from app.core import send_limits
from app.core.supabase_client import supabase_admin
from app.core.auth_middleware import get_current_user
from app.schemas.referral import ReferralCreate, ReferralInDB, REFERRAL_CHANNELS
from app.services.email_service import EmailService
from app.services.program_service import get_int_setting
from app.services import invite_service

router = APIRouter()
limiter = Limiter(key_func=client_ip)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Australian mobile: 04XXXXXXXX, 4XXXXXXXX or +614XXXXXXXX (spaces/dashes ignored)
_AU_MOBILE_RE = re.compile(r"^(?:\+?61|0)?4\d{8}$")
# Sent from the member's own phone (share sheet), so not emailed again.
_SELF_SENT = {"sms", "whatsapp", "share"}


def _normalise_mobile(mobile: str) -> str:
    return re.sub(r"[\s\-()]", "", mobile or "")


@router.post("/", response_model=ReferralInDB)
def create_referral(referral: ReferralCreate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    name = (referral.referred_name or "").strip()
    email = (referral.referred_email or "").strip().lower() or None
    mobile = _normalise_mobile(referral.referred_mobile) or None

    # App 3.0.0 (still live in the stores) sends neither field. Keep accepting its
    # referrals as before: no consent box existed, and its form always required an email.
    legacy_client = referral.channel is None and referral.consent_given is None
    channel = (referral.channel or "form").lower()
    if channel not in REFERRAL_CHANNELS:
        channel = "form"

    if not name:
        raise HTTPException(status_code=400, detail="Please enter your friend's name.")
    if not email and not mobile:
        raise HTTPException(status_code=400, detail="Please enter a mobile number or email address.")
    if email and not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if mobile and not _AU_MOBILE_RE.match(mobile):
        if legacy_client and email:
            pass  # old app didn't validate mobiles; the email is enough to follow up
        else:
            raise HTTPException(status_code=400, detail="Please enter a valid Australian mobile number.")
    if not legacy_client and not referral.consent_given:
        raise HTTPException(status_code=400, detail="Please confirm your friend is happy to be contacted.")

    # Already a member?
    if email:
        member = supabase_admin.table("users").select("id").eq("email", email).execute()
        if member.data:
            raise HTTPException(status_code=400, detail="This person is already a Reliiance Rewards member.")

    # Already referred by this member?
    for field, value in (("referred_email", email), ("referred_mobile", mobile)):
        if value:
            dup = supabase_admin.table("referrals").select("id").eq("referrer_id", user_id).eq(field, value).execute()
            if dup.data:
                raise HTTPException(status_code=400, detail="You've already referred this person.")

    user_resp = supabase_admin.table("users").select("full_name, referral_code").eq("id", user_id).execute()
    inviter = user_resp.data[0] if user_resp.data else {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    resp = supabase_admin.table("referrals").insert({
        "referrer_id": user_id,
        "referred_name": name,
        "referred_mobile": mobile,
        "referred_email": email,
        "status": "invited",
        "channel": channel,
        "consent_given": bool(referral.consent_given),
        "stage_updated_at": now,
        "notes": (referral.notes or "").strip()[:500] or None,
    }).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create referral record")

    # The invitation email comes from no-reply. The app opens the member's own mail app
    # instead when invite_emailed is false (email not set up yet).
    emailed = False
    if email and channel not in _SELF_SENT:
        try:
            send_limits.use(user_id, "referral_invites")
        except HTTPException:
            # Past today's cap: the referral is still saved; the app offers the member's own mail app instead
            return {**resp.data[0], "invite_emailed": False}
        emailed = EmailService.send_referral_invite(
            to_email=email,
            inviter_name=inviter.get("full_name") or "A friend",
            referral_code=inviter.get("referral_code"),
            invite_link=invite_service.personal_link(inviter.get("referral_code")) or None,
            friend_name=name,
        )
    return {**resp.data[0], "invite_emailed": bool(emailed)}


@router.get("/", response_model=List[ReferralInDB])
def list_referrals(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    resp = supabase_admin.table("referrals").select("*").eq("referrer_id", user_id).order("created_at", desc=True).execute()
    return resp.data


@router.get("/summary")
def referral_summary(current_user: dict = Depends(get_current_user)):
    """Points card and share message for the Referrals screen."""
    user_id = current_user.get("sub")
    refs = supabase_admin.table("referrals").select("points_earned").eq("referrer_id", user_id).execute().data or []
    tx = supabase_admin.table("transactions").select("points").eq("user_id", user_id).eq("type", "referral").execute().data or []
    earned = max(sum(r.get("points_earned") or 0 for r in refs), sum(t.get("points") or 0 for t in tx))
    user = supabase_admin.table("users").select("full_name, referral_code").eq("id", user_id).execute().data or [{}]
    return {
        "points_earned": earned,
        "points_per_referral": get_int_setting("referral_points"),
        "referral_code": user[0].get("referral_code"),
        "invite_link": invite_service.personal_link(user[0].get("referral_code")),
        "inviter_name": user[0].get("full_name"),
    }


# ── Personal invite links (public: the friend isn't a member yet) ──────────
@router.post("/invite/{code}")
@limiter.limit("30/minute")
def open_invite(request: Request, code: str):
    """Called by the invite link's welcome page. Returns who invited them (first name only)
    and remembers the visit so the app can fill in the code after it's installed.
    The launch QR codes use this too, with the launch code (no inviter)."""
    if invite_service.is_launch_code(code):
        clean = invite_service.clean_code(code)
        invite_service.record_click(clean, request)
        return {"valid": True, "code": clean, "inviter_first_name": None, "launch": True}
    inviter = invite_service.inviter_for(code)
    if not inviter:
        return {"valid": False}
    clean = invite_service.clean_code(code)
    invite_service.record_click(clean, request)
    first = (inviter.get("full_name") or "").strip().split(" ")[0]
    return {"valid": True, "code": clean, "inviter_first_name": first or None}


@router.get("/pending-invite")
@limiter.limit("10/minute")
def pending_invite(request: Request):
    """Called by the app on the sign-up screen: the code from an invite link recently opened
    on this phone's network, if any."""
    return {"code": invite_service.pending_code(request) or None}
