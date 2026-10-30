"""The activity log (audit_log table) and security alerts.

Every change made on the admin site is recorded with who did it, when, from where and what was
sent; security events (locked sign-ins, staff access changes, sign-outs) are recorded too. Rows
can only be added - the database refuses edits and deletions. Recording never fails a request.
"""
import datetime
import threading
import time

from app.core.config import settings
from app.core.supabase_client import supabase_admin

_REDACT = {"password", "new_password", "token", "access_token", "code", "secret"}
_MAX_TEXT = 300

# Alerts: at most one per subject+target per hour, and 30 per day in total, so an attack
# can't flood the inbox.
_alert_lock = threading.Lock()
_alerts_sent: dict = {}
_alerts_today: list = []


def clean(value, depth: int = 0):
    """Request details safe to keep: no passwords or codes, no image data, long text shortened."""
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _REDACT:
                out[k] = "[hidden]"
            elif k == "data_base64":
                out[k] = "[image]"
            else:
                out[k] = clean(v, depth + 1)
        return out
    if isinstance(value, list):
        return [clean(v, depth + 1) for v in value[:50]]
    if isinstance(value, str) and len(value) > _MAX_TEXT:
        return value[:_MAX_TEXT] + "..."
    return value


def record(kind: str, action: str, actor: dict = None, target: str = None, details: dict = None,
           status: int = None, ip: str = None, user_agent: str = None) -> None:
    actor = actor or {}
    try:
        supabase_admin.table("audit_log").insert({
            "kind": kind, "action": action, "actor_id": actor.get("sub"), "actor_email": actor.get("email"),
            "actor_role": actor.get("admin_role"), "target": target, "details": clean(details) if details else None,
            "status": status, "ip": ip, "user_agent": (user_agent or "")[:200] or None,
        }).execute()
    except Exception as e:
        print(f"Activity log write failed ({action}): {e}")


def security(action: str, target: str = None, details: dict = None, ip: str = None, actor: dict = None) -> None:
    record("security", action, actor=actor, target=target, details=details, ip=ip)


def _alert_email() -> str:
    from app.services.program_service import get_setting
    return (get_setting("security_alert_email") or "").strip() or settings.ADMIN_EMAIL


def alert(subject: str, rows: list, note: str = "", key: str = "") -> bool:
    """Emails the business a security alert (security_alert_email setting, else ADMIN_EMAIL)."""
    now = time.time()
    with _alert_lock:
        dedupe = f"{subject}|{key}"
        if now - _alerts_sent.get(dedupe, 0) < 3600:
            return False
        _alerts_today[:] = [t for t in _alerts_today if now - t < 86400]
        if len(_alerts_today) >= 30:
            return False
        _alerts_sent[dedupe] = now
        _alerts_today.append(now)
    to = _alert_email()
    if not to:
        return False
    from app.services.email_service import EmailService
    when = datetime.datetime.now(datetime.timezone.utc).astimezone(_sydney()).strftime("%a %d %b %Y, %I:%M %p")
    return EmailService.send_security_alert(to, subject, [("When", when)] + rows, note)


def _sydney():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Australia/Sydney")
    except Exception:
        return datetime.timezone.utc


def sydney_now_text() -> str:
    return datetime.datetime.now(datetime.timezone.utc).astimezone(_sydney()).strftime("%a %d %b %Y, %I:%M %p (Sydney time)")


def reset_alerts() -> None:
    """Tests only."""
    with _alert_lock:
        _alerts_sent.clear(); _alerts_today.clear()
