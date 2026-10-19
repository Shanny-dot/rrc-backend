"""Member alerts: phone push (if the member allows that kind) and, for alerts sent by the
daily job, a notification_log row so the same alert never goes out twice and the in-app
Updates list can show it."""
from app.core.supabase_client import supabase_admin
from app.services.push_service import PushService

# Settings screen switches. Missing keys mean "on".
PREF_KEYS = ["points", "referrals", "rewards", "events", "expiry", "loan"]

_PREF_FOR_KIND = {
    "points": "points",
    "bonus_birthday": "points",
    "bonus_loan_anniversary": "points",
    "bonus_first_referral": "points",
    "referral": "referrals",
    "reward": "rewards",
    "event_reminder": "events",
    "event_reminder_7d": "events",
    "event_thanks": "events",
    "points_expiring": "expiry",
    "points_expired": "expiry",
    "loan_checkin": "loan",
}


def prefs_for(row: dict) -> dict:
    stored = row.get("notification_prefs") or {}
    return {k: bool(stored.get(k, True)) for k in PREF_KEYS}


def already_sent(user_id: str, kind: str, ref: str) -> bool:
    rows = supabase_admin.table("notification_log").select("id").eq("user_id", user_id).eq("kind", kind).eq("ref", ref).execute().data
    return bool(rows)


def log_once(user_id: str, kind: str, ref: str, title: str, body: str) -> bool:
    """Records the alert; False if this exact alert was already recorded."""
    if already_sent(user_id, kind, ref):
        return False
    try:
        supabase_admin.table("notification_log").insert({"user_id": user_id, "kind": kind, "ref": ref, "title": title, "body": body}).execute()
        return True
    except Exception as e:  # unique (user_id, kind, ref): sent by a parallel run
        print(f"Notification log warning: {e}")
        return False


def push(user_id: str, kind: str, title: str, body: str, data: dict = None) -> str:
    """Phone alert if the member has the app and allows this kind. Never raises."""
    try:
        rows = supabase_admin.table("users").select("fcm_token, notification_prefs, deleted_at").eq("id", user_id).execute().data
        if not rows or rows[0].get("deleted_at") or not rows[0].get("fcm_token"):
            return "skipped"
        if not prefs_for(rows[0]).get(_PREF_FOR_KIND.get(kind, ""), True):
            return "muted"
        result = PushService.send_push_notification(rows[0]["fcm_token"], title, body, {"type": kind, **(data or {})})
        if result == "invalid_token":
            supabase_admin.table("users").update({"fcm_token": None}).eq("id", user_id).execute()
        return result
    except Exception as e:
        print(f"Push warning ({kind}): {e}")
        return "failed"


def notify_once(user_id: str, kind: str, ref: str, title: str, body: str, data: dict = None) -> bool:
    """Log + push, at most once per (member, kind, ref). Returns True if it was new."""
    if not log_once(user_id, kind, ref, title, body):
        return False
    push(user_id, kind, title, (body or "")[:180], data)
    return True
