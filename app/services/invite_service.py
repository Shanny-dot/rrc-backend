"""Personal invite links: https://<site>/join/<CODE> opens a welcome page for the friend,
which records the visit so the app can fill the code in after the friend installs it."""
import datetime
import hashlib
import hmac
import re
from fastapi import Request
from app.core.client_ip import client_ip
from app.core.config import settings
from app.core.supabase_client import supabase_admin
from app.services.program_service import get_setting

CLICK_TTL = datetime.timedelta(hours=48)
_CODE_RE = re.compile(r"^[A-Z0-9]{4,8}$")


def clean_code(code: str) -> str:
    code = (code or "").strip().upper()
    return code if _CODE_RE.match(code) else ""


def personal_link(code: str) -> str:
    base = (get_setting("invite_base_url") or "").rstrip("/")
    return f"{base}/{code}" if base and code else (get_setting("invite_link") or "")


def _ip_hash(request: Request) -> str:
    ip = client_ip(request)
    return hmac.new(settings.JWT_SECRET.encode(), ip.encode(), hashlib.sha256).hexdigest() if ip else ""


def _cutoff() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc) - CLICK_TTL


def _parse(ts) -> datetime.datetime:
    try:
        parsed = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def is_launch_code(code: str) -> bool:
    """The code behind the launch QR codes (Program settings), not a member's referral code."""
    launch = clean_code(get_setting("launch_code"))
    return bool(launch) and clean_code(code) == launch


def inviter_for(code: str):
    code = clean_code(code)
    if not code:
        return None
    rows = supabase_admin.table("users").select("id, full_name, deleted_at").eq("referral_code", code).execute().data or []
    return next((r for r in rows if not r.get("deleted_at")), None)


def record_click(code: str, request: Request) -> None:
    ip_hash = _ip_hash(request)
    if not ip_hash:
        return
    try:
        supabase_admin.table("invite_clicks").insert({"referral_code": code, "ip_hash": ip_hash}).execute()
        supabase_admin.table("invite_clicks").delete().lt("created_at", _cutoff().isoformat()).execute()
    except Exception as e:
        print(f"Invite click warning: {e}")


def pending_code(request: Request) -> str:
    """The code from the most recent invite link opened on this network in the last 48 hours."""
    ip_hash = _ip_hash(request)
    if not ip_hash:
        return ""
    try:
        rows = supabase_admin.table("invite_clicks").select("referral_code, created_at").eq("ip_hash", ip_hash) \
            .order("created_at", desc=True).execute().data or []
    except Exception as e:
        print(f"Pending invite warning: {e}")
        return ""
    cutoff = _cutoff()
    fresh = [r for r in rows if _parse(r.get("created_at")) >= cutoff]
    return fresh[0]["referral_code"] if fresh else ""


def link_new_member(user_id: str, code: str, full_name: str, email: str = None, mobile: str = None) -> None:
    """Connect a brand-new member to the member whose code they joined with, and move the
    matching referral (if the inviter added them first) to "Joined the app"."""
    inviter = inviter_for(code)
    if not inviter or inviter["id"] == user_id:
        return
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        supabase_admin.table("users").update({"referred_by": inviter["id"]}).eq("id", user_id).execute()
        update = {"status": "registered", "referred_user_id": user_id, "stage_updated_at": now}
        mobile_digits = re.sub(r"\D", "", mobile or "")[-9:]
        mine = supabase_admin.table("referrals").select("id, referred_email, referred_mobile, status, referred_user_id") \
            .eq("referrer_id", inviter["id"]).execute().data or []
        match = next((r for r in mine if not r.get("referred_user_id") and (
            (email and (r.get("referred_email") or "").lower() == email.lower()) or
            (mobile_digits and re.sub(r"\D", "", r.get("referred_mobile") or "")[-9:] == mobile_digits))), None)
        if match:
            # Don't move a referral backwards if staff have already progressed it.
            if match.get("status") in (None, "pending", "invited"):
                supabase_admin.table("referrals").update(update).eq("id", match["id"]).execute()
            else:
                supabase_admin.table("referrals").update({"referred_user_id": user_id}).eq("id", match["id"]).execute()
        else:
            supabase_admin.table("referrals").insert({
                "referrer_id": inviter["id"],
                "referred_name": full_name or "New member",
                "referred_email": email,
                "referred_mobile": mobile,
                "channel": "code",
                "consent_given": True,
                **update,
            }).execute()
    except Exception as e:
        print(f"Referral link warning: {e}")
        return
    # "Your friend joined" email to the member who invited them
    try:
        from app.services.email_service import EmailService
        from app.services.program_service import get_int_setting
        rows = supabase_admin.table("users").select("full_name, email").eq("id", inviter["id"]).execute().data or []
        if rows and rows[0].get("email"):
            EmailService.send_friend_joined(rows[0]["email"], rows[0].get("full_name"), full_name or "Your friend",
                                            get_int_setting("referral_points"))
    except Exception as e:
        print(f"Friend joined email warning: {e}")
