import datetime
from fastapi import APIRouter, Depends
from app.core.supabase_client import supabase_admin
from app.core.auth_middleware import get_current_user
from app.services.program_service import activity_for_user, _parse_ts

router = APIRouter()

REFERRAL_STAGE_TEXT = {
    "pending": "We're following up with {name}.",
    "contacted": "Reliiance has contacted {name}.",
    "loan_in_progress": "{name}'s loan is in progress.",
    "settled": "{name}'s loan has settled. Your points are on the way.",
    "rewarded": "You earned points for referring {name}.",
    "registered": "{name} has signed up to Reliiance Rewards.",
}

LOGGED_KINDS = {"loan_checkin": "loan", "points_expiring": "points", "event_thanks": "event",
                "event_reminder": "event", "event_reminder_7d": "event", "event_update": "event",
                "event_cancelled": "event", "tier_upgrade": "points"}


def _iso(ts):
    return ts.isoformat() if ts else None

@router.get("")
@router.get("/")
def list_notifications(current_user: dict = Depends(get_current_user)):
    """Member updates, newest first: points changes, reward status, referral progress
    and reminders for events the member is going to in the next 48 hours."""
    user_id = current_user.get("sub")
    items = []

    for a in activity_for_user(user_id)[:30]:
        pts = a.get("points") or 0
        sign = "+" if pts > 0 else ""
        items.append({
            "id": f"tx-{a['id']}", "kind": "points",
            "title": a.get("title") or "Points update",
            "body": f"{sign}{pts} pts" + (f" · {a['status_label']}" if a.get("status_label") else ""),
            "at": a.get("created_at"),
        })

    reds = supabase_admin.table("redemptions").select("id, status, requested_at, actioned_at, sent_at, rewards(title)") \
        .eq("user_id", user_id).execute().data or []
    for r in reds:
        title = (r.get("rewards") or {}).get("title") or "Your reward"
        if r.get("requested_at"):
            items.append({"id": f"red-new-{r['id']}", "kind": "reward", "title": f"{title} requested",
                          "body": f"Reference {str(r['id'])[:8].upper()} — we'll keep you updated.", "at": r["requested_at"]})
        if r.get("status") == "in_progress" and r.get("actioned_at"):
            items.append({"id": f"red-wip-{r['id']}", "kind": "reward", "title": f"{title} in progress",
                          "body": "Our team is working on your reward.", "at": r["actioned_at"]})
        if r.get("status") == "sent" and r.get("sent_at"):
            items.append({"id": f"red-sent-{r['id']}", "kind": "reward", "title": f"{title} has been sent",
                          "body": "Check your email for your reward.", "at": r["sent_at"]})
        if r.get("status") in ("approved", "sent") and r.get("actioned_at"):
            items.append({"id": f"red-ok-{r['id']}", "kind": "reward", "title": f"{title} approved",
                          "body": "We're preparing your reward.", "at": r["actioned_at"]})
        if r.get("status") == "rejected" and r.get("actioned_at"):
            items.append({"id": f"red-no-{r['id']}", "kind": "reward", "title": f"{title} couldn't be processed",
                          "body": "Your points have been refunded.", "at": r["actioned_at"]})

    refs = supabase_admin.table("referrals").select("id, referred_name, status, stage_updated_at") \
        .eq("referrer_id", user_id).execute().data or []
    for f in refs:
        text = REFERRAL_STAGE_TEXT.get(f.get("status") or "")
        if text and f.get("stage_updated_at"):
            items.append({"id": f"ref-{f['id']}-{f['status']}", "kind": "referral", "title": "Referral update",
                          "body": text.format(name=f.get("referred_name") or "Your friend"), "at": f["stage_updated_at"]})

    now = datetime.datetime.now(datetime.timezone.utc)
    rsvps = supabase_admin.table("event_rsvps").select("id, cancelled, rsvp_at, cancelled_at, attended, attended_at, events(title, event_date, location)") \
        .eq("user_id", user_id).execute().data or []
    for v in rsvps:
        ev = v.get("events") or {}
        start = _parse_ts(ev.get("event_date"))
        name = ev.get("title") or "the event"
        if v.get("rsvp_at"):
            items.append({"id": f"rsvp-{v['id']}", "kind": "event", "title": f"You're going: {name}",
                          "body": ev.get("location") or "RSVP confirmed.", "at": v["rsvp_at"]})
        if v.get("cancelled") and v.get("cancelled_at"):
            items.append({"id": f"rsvp-x-{v['id']}", "kind": "event", "title": f"RSVP cancelled: {name}",
                          "body": "You're no longer booked in.", "at": v["cancelled_at"]})
        if v.get("attended") and v.get("attended_at"):
            items.append({"id": f"rsvp-in-{v['id']}", "kind": "event", "title": f"Checked in: {name}",
                          "body": "Thanks for coming!", "at": v["attended_at"]})
        if v.get("cancelled") or not start:
            continue
        if now <= start <= now + datetime.timedelta(hours=48):
            items.append({"id": f"evt-{v['id']}", "kind": "event", "title": f"Coming up: {ev.get('title')}",
                          "body": ev.get("location") or "", "at": _iso(now - datetime.timedelta(minutes=1))})

    # Alerts from the daily job and staff (loan check-ins, expiry warnings, event thank-yous).
    # Bonuses and expiries already appear above as points activity.
    logged = supabase_admin.table("notification_log").select("id, kind, title, body, created_at") \
        .eq("user_id", user_id).execute().data or []
    for n in logged:
        kind = LOGGED_KINDS.get(n.get("kind"))
        if kind:
            items.append({"id": f"log-{n['id']}", "kind": kind, "type": n["kind"], "title": n.get("title") or "",
                          "body": n.get("body") or "", "at": n.get("created_at")})

    items.sort(key=lambda i: str(i.get("at") or ""), reverse=True)
    return items[:50]
