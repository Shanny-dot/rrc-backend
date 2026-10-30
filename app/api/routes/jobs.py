"""Daily job, run each morning by the GitHub Actions workflow .github/workflows/daily-jobs.yml.

Sends event reminders for tomorrow (phone alert and email), birthday and loan-anniversary
bonuses, and points-expiry alerts (and expiry) when a
points_expiry_months setting is in force. Every alert is logged, so running it twice in a
day (e.g. a retry) never sends or pays anything twice."""
import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Header, HTTPException
from app.core.config import settings
from app.core.supabase_client import supabase_admin
from app.services import notify_service
from app.services.bonus_service import BonusService
from app.services.points_service import PointsService
from app.services.program_service import get_int_setting, _parse_ts, event_when
from app.services.email_service import EmailService
import hmac


def _job_key_ok(key: str) -> bool:
    """The scheduled jobs' shared key, compared in constant time so it can't be guessed byte by byte."""
    return bool(settings.JOB_SECRET) and hmac.compare_digest((key or "").encode(), settings.JOB_SECRET.encode())

router = APIRouter()

PROGRAM_TZ = ZoneInfo("Australia/Sydney")
LOAN_CHECKIN_ENABLED = False
EXPIRY_NOTICE_DAYS = 30
# Points that are "earned" and so can expire; refunds just give back spent points.
_EARNING_TYPES = {"signup_bonus", "referral", "event_attend", "event_guest", "admin_adjustment", "bonus"}


def _today() -> datetime.date:
    return datetime.datetime.now(PROGRAM_TZ).date()


def _same_day(d: datetime.date, today: datetime.date) -> bool:
    """Birthdays/anniversaries on 29 Feb are celebrated on 28 Feb in other years."""
    if d.month == 2 and d.day == 29 and not _is_leap(today.year):
        return today.month == 2 and today.day == 28
    return (d.month, d.day) == (today.month, today.day)


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _add_months(d: datetime.date, months: int) -> datetime.date:
    m = d.month - 1 + months
    year, month = d.year + m // 12, m % 12 + 1
    days_in_month = [31, 29 if _is_leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return datetime.date(year, month, min(d.day, days_in_month))


def _date(value):
    try:
        return datetime.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def event_reminders(today: datetime.date, days: int = 1) -> int:
    """Phone alert + email to everyone booked in, the day before (days=1) or a week before (days=7)."""
    target = today + datetime.timedelta(days=days)
    kind = "event_reminder" if days == 1 else f"event_reminder_{days}d"
    sent = 0
    events = supabase_admin.table("events").select("*").execute().data or []
    for ev in events:
        start = _parse_ts(ev.get("event_date"))
        if not start or ev.get("is_active") is False or start.astimezone(PROGRAM_TZ).date() != target:
            continue
        local = start.astimezone(PROGRAM_TZ)
        when = local.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
        day = "Tomorrow" if days == 1 else f"{local:%A} {local.day} {local:%B}"
        body = f"{day} at {when}" + (f" · {ev['location']}" if ev.get("location") else "")
        title = f"See you tomorrow: {ev['title']}" if days == 1 else f"Coming up next week: {ev['title']}"
        rsvps = supabase_admin.table("event_rsvps").select("user_id, cancelled, users(full_name, email)") \
            .eq("event_id", ev["id"]).execute().data or []
        for r in rsvps:
            if not r.get("cancelled") and notify_service.notify_once(r["user_id"], kind, str(ev["id"]), title, body, {"event_id": ev["id"]}):
                sent += 1
                member = r.get("users") or {}
                if member.get("email"):
                    EmailService.send_event_reminder(member["email"], member.get("full_name"), ev, event_when(ev), days)
    return sent


def birthdays_and_anniversaries(today: datetime.date, members: list) -> dict:
    out = {"birthday_bonuses": 0, "loan_checkins": 0, "anniversary_bonuses": 0}
    for m in members:
        dob = _date(m.get("dob"))
        if dob and _same_day(dob, today) and BonusService.birthday(m["id"], today.year):
            out["birthday_bonuses"] += 1
        settled = _date(m.get("loan_settled_on"))
        if settled and settled.year < today.year and _same_day(settled, today):
            years = today.year - settled.year
            # The yearly "Is your loan still competitive?" check-in is switched off for launch
            # (the program isn't only about home loans). Turn it back on with LOAN_CHECKIN_ENABLED.
            if LOAN_CHECKIN_ENABLED:
                label = "a year" if years == 1 else f"{years} years"
                if notify_service.notify_once(
                        m["id"], "loan_checkin", str(today.year), "Is your loan still competitive?",
                        f"It's been {label} since your home loan settled. Rates change — ask your broker for a free review.",
                        {"years": years}):
                    out["loan_checkins"] += 1
            # The loan anniversary bonus was removed from the program (client request, Oct 2026).
    return out


def expiry_amounts(transactions: list, balance: int, months: int, today: datetime.date) -> tuple:
    """(expire_now, expiring_within_notice): oldest points are used first, so points expire
    only if earned before the cutoff and not already used by redemptions or earlier expiry."""
    cutoff_now = _add_months(today, -months)
    cutoff_soon = cutoff_now + datetime.timedelta(days=EXPIRY_NOTICE_DAYS)
    used = 0
    earned_now = earned_soon = 0
    for t in transactions:
        pts = t.get("points") or 0
        created = _parse_ts(t.get("created_at"))
        day = created.astimezone(PROGRAM_TZ).date() if created else today
        if pts < 0:
            used += -pts
        elif t.get("type") == "redemption_refund":
            used -= pts
        elif t.get("type") in _EARNING_TYPES:
            if day < cutoff_now:
                earned_now += pts
            if day < cutoff_soon:
                earned_soon += pts
    used = max(0, used)
    expire_now = max(0, min(balance, earned_now - used))
    soon = max(0, min(balance - expire_now, earned_soon - used - expire_now))
    return expire_now, soon


def points_expiry(today: datetime.date, members: list) -> dict:
    out = {"expired_members": 0, "expiry_alerts": 0}
    months = get_int_setting("points_expiry_months")
    if months <= 0:
        return out
    all_tx = supabase_admin.table("transactions").select("user_id, type, points, created_at").execute().data or []
    by_user = {}
    for t in all_tx:
        by_user.setdefault(str(t["user_id"]), []).append(t)
    rewards = None  # loaded once, only if an expiry email goes out
    for m in members:
        balance = m.get("total_points") or 0
        if balance <= 0:
            continue
        expire_now, soon = expiry_amounts(by_user.get(str(m["id"]), []), balance, months, today)
        if expire_now > 0 and notify_service.log_once(m["id"], "points_expired", today.isoformat(),
                                                      f"{expire_now:,} points expired",
                                                      f"Points earned more than {months} months ago have expired."):
            PointsService.deduct_points(m["id"], expire_now, "points_expired", f"Points expired (earned before {_add_months(today, -months):%d %b %Y})")
            notify_service.push(m["id"], "points_expired", f"{expire_now:,} points expired",
                                f"Points earned more than {months} months ago have expired.")
            out["expired_members"] += 1
        if soon > 0:
            by = today + datetime.timedelta(days=EXPIRY_NOTICE_DAYS)
            if notify_service.notify_once(m["id"], "points_expiring", by.strftime("%Y-%m"),
                                          f"{soon:,} points expire soon",
                                          f"Use them by {by:%d %b} — browse rewards in the app."):
                out["expiry_alerts"] += 1
                if m.get("email"):
                    if rewards is None:
                        rewards = supabase_admin.table("rewards").select("title, points_required, is_active, stock") \
                            .execute().data or []
                    affordable = sorted((r for r in rewards if r.get("is_active", True) and r.get("stock") != 0
                                         and (r.get("points_required") or 0) <= balance),
                                        key=lambda r: -(r.get("points_required") or 0))[:5]
                    EmailService.send_points_expiring(m["email"], m.get("full_name"), soon, f"{by:%d %B %Y}", balance,
                                                      [(r["title"], r["points_required"]) for r in affordable])
    return out


@router.post("/daily-report")
def run_daily_report(x_job_key: str = Header(default=""), date: str = None):
    """End-of-day staff report (Excel by email). ?date=YYYY-MM-DD for another Sydney day."""
    if not _job_key_ok(x_job_key):
        raise HTTPException(status_code=403, detail="Not allowed")
    from app.services import daily_report
    day = datetime.date.fromisoformat(date) if date else None
    summary, xlsx = daily_report.build(day)
    when = day or datetime.datetime.now(ZoneInfo("Australia/Sydney")).date()
    sent = EmailService.send_daily_report(summary, xlsx, f"Reliiance_Daily_Report_{when.isoformat()}.xlsx")
    print(f"Daily report {when}: sent={sent} {summary}")
    return {**summary, "emailed": sent}


@router.post("/daily")
def run_daily(x_job_key: str = Header(default="")):
    if not _job_key_ok(x_job_key):
        raise HTTPException(status_code=403, detail="Not allowed")
    today = _today()
    members = [m for m in (supabase_admin.table("users").select("id, full_name, email, dob, loan_settled_on, total_points, deleted_at")
                           .execute().data or []) if not m.get("deleted_at")]
    summary = {"date": today.isoformat(), "event_reminders": 0}
    for name, task in (("event_reminders", lambda: {"event_reminders": event_reminders(today),
                                                    "event_reminders_week": event_reminders(today, 7)}),
                       ("occasions", lambda: birthdays_and_anniversaries(today, members)),
                       ("expiry", lambda: points_expiry(today, members))):
        try:
            summary.update(task())
        except Exception as e:  # one failing task shouldn't stop the others
            print(f"Daily job {name} failed: {e}")
            summary[f"{name}_error"] = str(e)[:200]
    print(f"Daily job: {summary}")
    return summary
