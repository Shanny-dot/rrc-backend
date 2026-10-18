from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List
from app.core.supabase_client import supabase_admin
from app.core.auth_middleware import get_current_admin
from app.schemas.event import EventCreate, EventUpdate, EventInDB, QRScanRequest
from app.schemas.reward import RewardCreate, RewardUpdate, RewardInDB
from app.schemas.redemption import RedemptionRejectRequest
from app.services.points_service import PointsService
from app.services.email_service import EmailService
from app.services import notify_service
from app.services.bonus_service import BonusService
from app.schemas.referral import ReferralStageUpdate
from app.services.program_service import get_int_setting, redemption_templates, REDEMPTION_STATUSES
from app.services import redemption_service
import datetime
import json
import os

# Every route in this router requires a signed-in admin. Applying the check at
# router level means a newly added admin route can't be left unprotected by mistake.
router = APIRouter(dependencies=[Depends(get_current_admin)])

DELETED_USERS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "deleted_users.json")

def load_deleted_users_map() -> dict:
    try:
        if os.path.exists(DELETED_USERS_FILE):
            with open(DELETED_USERS_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print("Error loading deleted_users.json:", e)
    return {}

def save_deleted_users_map(data: dict):
    try:
        with open(DELETED_USERS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("Error saving deleted_users.json:", e)

@router.get("/users")
def list_users(admin: dict = Depends(get_current_admin)):
    resp = supabase_admin.table("users").select("*").order("created_at", desc=True).execute()
    dmap = load_deleted_users_map()
    active_users = []
    for u in (resp.data or []):
        uid = u.get("id")
        if not u.get("deleted_at") and uid not in dmap:
            active_users.append(u)
    return active_users

@router.get("/deleted-users")
def list_deleted_users(admin: dict = Depends(get_current_admin)):
    thirty_days_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).isoformat()
    resp = supabase_admin.table("users").select("*").order("created_at", desc=True).execute()
    dmap = load_deleted_users_map()
    deleted_users = []
    for u in (resp.data or []):
        uid = u.get("id")
        del_time = u.get("deleted_at") or dmap.get(uid)
        if del_time and str(del_time) >= thirty_days_ago:
            u_copy = dict(u)
            u_copy["deleted_at"] = del_time
            deleted_users.append(u_copy)
    return deleted_users

@router.get("/users/{id}")
def get_user(id: str, admin: dict = Depends(get_current_admin)):
    resp = supabase_admin.table("users").select("*").eq("id", id).single().execute()
    if not resp.data:
         raise HTTPException(status_code=404, detail="User not found")
    return resp.data

@router.delete("/users/{id}")
def delete_user(id: str, admin: dict = Depends(get_current_admin)):
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        supabase_admin.table("users").update({"deleted_at": now_iso}).eq("id", id).execute()
    except Exception as e:
        print("DB deleted_at update note:", e)

    dmap = load_deleted_users_map()
    dmap[id] = now_iso
    save_deleted_users_map(dmap)
    return {"message": "User deleted successfully", "id": id}

@router.post("/users/{id}/restore")
def restore_user(id: str, admin: dict = Depends(get_current_admin)):
    try:
        supabase_admin.table("users").update({"deleted_at": None}).eq("id", id).execute()
    except Exception as e:
        print("DB deleted_at restore note:", e)

    dmap = load_deleted_users_map()
    if id in dmap:
        del dmap[id]
        save_deleted_users_map(dmap)
    return {"message": "User restored successfully", "id": id}

@router.put("/users/{id}")
def update_user_profile(id: str, data: dict = Body(...), admin: dict = Depends(get_current_admin)):
    """Update user profile fields from admin panel."""
    ALLOWED_FIELDS = {
        "full_name", "mobile", "gender", "dob", "industry",
        "home_ownership", "home_ownership_status", "annual_income", "street_address",
        "city", "state", "postal_code", "role", "loan_settled_on"
    }
    update_data = {k: v for k, v in data.items() if k in ALLOWED_FIELDS}
    if "loan_settled_on" in update_data:
        value = (update_data["loan_settled_on"] or "").strip()
        try:
            update_data["loan_settled_on"] = datetime.date.fromisoformat(value).isoformat() if value else None
        except ValueError:
            raise HTTPException(status_code=400, detail="Loan settlement date must be YYYY-MM-DD.")
    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    resp = supabase_admin.table("users").update(update_data).eq("id", id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="User not found")
    return resp.data[0]


@router.put("/users/{id}/points")
def update_user_points(id: str, new_points: int = Body(..., embed=True), reason: str = Body("Admin adjustment", embed=True), admin: dict = Depends(get_current_admin)):
    user_resp = supabase_admin.table("users").select("total_points").eq("id", id).execute()
    if not user_resp.data:
        raise HTTPException(status_code=404, detail="User not found")

    current_points = user_resp.data[0].get("total_points", 0) or 0
    diff = new_points - current_points

    resp = supabase_admin.table("users").update({"total_points": new_points}).eq("id", id).execute()

    if diff != 0:
        # Logged to the same table the app reads, with a signed amount, so members see it in Recent Activity.
        try:
            supabase_admin.table("transactions").insert({
                "user_id": id,
                "points": diff,
                "type": "admin_adjustment",
                "description": (reason or "Admin adjustment").strip(),
            }).execute()
        except Exception as e:
            print("Transaction log warning:", e)
        if diff > 0:
            notify_service.push(id, "points", f"+{diff:,} points added", (reason or "Points added by Reliiance").strip())

    return {"message": f"Points updated to {new_points}", "data": resp.data[0]}

@router.get("/events")
def list_all_events():
    resp = supabase_admin.table("events").select("*").order("event_date", desc=False).execute()
    return resp.data

def _check_points_range(data: dict, current: dict = None):
    """A range's top must be above its starting points; an empty or equal top means a fixed amount."""
    for base_key, max_key, label in (("points_for_attending", "points_for_attending_max", "attending"),
                                     ("points_for_referring", "points_for_referring_max", "bringing a friend")):
        if max_key not in data:
            continue
        top = data.get(max_key)
        base = data.get(base_key, (current or {}).get(base_key)) or 0
        if top in (None, 0) or top == base:
            data[max_key] = None
        elif top < base:
            raise HTTPException(status_code=400, detail=f"The 'up to' points for {label} must be more than the starting points.")


@router.post("/events", response_model=EventInDB)
def create_event(event: EventCreate):
    # Image upload to supabase storage should be handled by a separate script or directly from frontend to storage,
    # and then the URL is passed here in `event.image_url`. Just taking the URL for now.
    insert_data = json.loads(event.json())
    _check_points_range(insert_data)
    resp = supabase_admin.table("events").insert(insert_data).execute()
    if not resp.data:
         raise HTTPException(status_code=500, detail="Failed to create event")
    return resp.data[0]

@router.put("/events/{id}", response_model=EventInDB)
def update_event(id: str, event: EventUpdate):
    update_data = json.loads(event.json(exclude_unset=True))
    current = supabase_admin.table("events").select("*").eq("id", id).execute().data or [{}]
    _check_points_range(update_data, current[0])
    resp = supabase_admin.table("events").update(update_data).eq("id", id).execute()
    if not resp.data:
         raise HTTPException(status_code=404, detail="Event not found")
    return resp.data[0]

@router.delete("/events/{id}")
def delete_event(id: str):
    supabase_admin.table("events").delete().eq("id", id).execute()
    return {"message": "Event deleted"}

@router.post("/rewards", response_model=RewardInDB)
def create_reward(reward: RewardCreate):
    resp = supabase_admin.table("rewards").insert(reward.dict()).execute()
    if not resp.data:
         raise HTTPException(status_code=500, detail="Failed to create reward")
    return resp.data[0]

@router.put("/rewards/{id}", response_model=RewardInDB)
def update_reward(id: str, reward: RewardUpdate):
    update_data = {k: v for k, v in reward.dict(exclude_unset=True).items()}
    resp = supabase_admin.table("rewards").update(update_data).eq("id", id).execute()
    if not resp.data:
         raise HTTPException(status_code=404, detail="Reward not found")
    return resp.data[0]

@router.delete("/rewards/{id}")
def delete_reward(id: str):
    # Check if reward has any redemptions
    redemptions = supabase_admin.table("redemptions").select("id").eq("reward_id", id).execute()
    if redemptions.data:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete this reward — it has {len(redemptions.data)} redemption(s). Disable it instead."
        )
    try:
        supabase_admin.table("rewards").delete().eq("id", id).execute()
        return {"message": "Reward deleted"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to delete reward: {str(e)}")

@router.get("/redemptions")
def list_redemptions():
    resp = supabase_admin.table("redemptions").select("*, users(full_name, email), rewards(title, points_required)").order("requested_at", desc=True).execute()
    return resp.data

# Which status a reward request can move to from each status.
REDEMPTION_MOVES = {
    "pending": {"in_progress", "approved", "rejected", "sent"},
    "in_progress": {"approved", "rejected", "sent"},
    "approved": {"sent"},
    "sent": set(),
    "rejected": set(),
}


def _set_redemption_status(id: str, status: str, note: str = None) -> dict:
    """Moves a reward request on, refunds points when rejected, and emails/alerts the member."""
    rows = supabase_admin.table("redemptions").select("*, rewards(title)").eq("id", id).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Redemption not found")
    redemption = rows[0]
    current = redemption.get("status") or "pending"
    if status not in REDEMPTION_MOVES:
        raise HTTPException(status_code=400, detail="Unknown status.")
    if status not in REDEMPTION_MOVES.get(current, set()):
        raise HTTPException(status_code=400, detail=f"This request is already {current.replace('_', ' ')} and can't be moved to {status.replace('_', ' ')}.")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    update = {"status": status, "actioned_at": now}
    if status == "sent":
        update["sent_at"] = now
        if redemption.get("actioned_at"):
            update.pop("actioned_at")
    note = (note or "").strip() or None
    if note:
        update["admin_note"] = note
    supabase_admin.table("redemptions").update(update).eq("id", id).execute()

    if status == "rejected":
        title = (redemption.get("rewards") or {}).get("title") or "reward"
        PointsService.award_points(
            user_id=redemption["user_id"], points=redemption["points_used"], type="redemption_refund",
            description=f"Refund for rejected redemption: {title}")
        rew = supabase_admin.table("rewards").select("stock").eq("id", redemption["reward_id"]).execute().data
        if rew and rew[0].get("stock") is not None:
            supabase_admin.table("rewards").update({"stock": rew[0]["stock"] + 1}).eq("id", redemption["reward_id"]).execute()

    redemption_service.notify_status(id, status, note)
    return {"message": f"Redemption {status.replace('_', ' ')}", "status": status}


@router.put("/redemptions/{id}/status")
def update_redemption_status(id: str, status: str = Body(..., embed=True), admin_note: str = Body(None, embed=True)):
    return _set_redemption_status(id, (status or "").strip().lower(), admin_note)


@router.put("/redemptions/{id}/approve")
def approve_redemption(id: str):
    return _set_redemption_status(id, "approved")


@router.put("/redemptions/{id}/reject")
def reject_redemption(id: str, req: RedemptionRejectRequest):
    return _set_redemption_status(id, "rejected", req.admin_note)

@router.post("/events/scan-qr")
def scan_qr(req: QRScanRequest):
    # 1. Find the RSVP row by qr_token
    rsvp_resp = supabase_admin.table("event_rsvps").select("*, events(points_for_attending, points_for_referring)").eq("qr_token", req.qr_token).single().execute()
    if not rsvp_resp.data:
         raise HTTPException(status_code=404, detail="Invalid QR code: RSVP not found")

    rsvp = rsvp_resp.data

    if rsvp["attended"]:
         raise HTTPException(status_code=400, detail="QR code already scanned and attended")

    # 2. Mark as Attended and Award Points to Attendee
    now = datetime.datetime.utcnow().isoformat()
    supabase_admin.table("event_rsvps").update({"attended": True, "attended_at": now, "points_awarded": True}).eq("id", rsvp["id"]).execute()

    points_to_award = rsvp["events"]["points_for_attending"]
    if points_to_award > 0:
         PointsService.award_points(
              user_id=rsvp["user_id"],
              points=points_to_award,
              type="event_attend",
              description=f"Attended event {rsvp['event_id']}"
         )
         notify_service.push(rsvp["user_id"], "points", f"+{points_to_award:,} points added", "Thanks for coming to the event!")

    # 3. Check if they were invited as a guest (award referring points to inviter)
    guest_resp = supabase_admin.table("event_guests").select("*").eq("rsvp_id", rsvp["id"]).eq("points_awarded_to_inviter", False).execute()
    if guest_resp.data:
         for guest in guest_resp.data:
              inviter_points = rsvp["events"]["points_for_referring"]
              if inviter_points > 0:
                   PointsService.award_points(
                        user_id=guest["inviter_user_id"],
                        points=inviter_points,
                        type="event_guest",
                        description=f"Your invited guest attended event {rsvp['event_id']}"
                   )
                   notify_service.push(guest["inviter_user_id"], "points", f"+{inviter_points:,} points added",
                                       f"{guest.get('guest_name') or 'Your guest'} came to the event.")
              supabase_admin.table("event_guests").update({"attended": True, "points_awarded_to_inviter": True}).eq("id", guest["id"]).execute()

    return {"message": "QR Scan Successful, Points Awarded"}

@router.get("/transactions")
def admin_list_transactions(user_id: str = None):
    query = supabase_admin.table("transactions").select("*, users(id, full_name, email)")
    if user_id:
         query = query.eq("user_id", user_id)
    resp = query.order("created_at", desc=True).execute()
    return resp.data


@router.put("/redemptions/{id}/sent")
def mark_redemption_sent(id: str, body: dict = Body(default={})):
    """Mark a redemption as sent to the member (optional note, e.g. a gift card code)."""
    return _set_redemption_status(id, "sent", (body or {}).get("admin_note"))


@router.get("/redemption-statuses")
def get_redemption_statuses():
    """Status names and the email sent for each, as edited on the Redemptions page."""
    return {"order": REDEMPTION_STATUSES, "statuses": redemption_templates()}


@router.put("/redemption-statuses")
def save_redemption_statuses(statuses: dict = Body(..., embed=True)):
    clean = {}
    for key in REDEMPTION_STATUSES:
        item = statuses.get(key) or {}
        label = str(item.get("label") or "").strip()
        if not label:
            raise HTTPException(status_code=400, detail="Every status needs a name.")
        clean[key] = {"label": label[:40], "subject": str(item.get("subject") or "").strip()[:150],
                      "message": str(item.get("message") or "").strip()[:2000]}
    supabase_admin.table("app_content").upsert({
        "key": "redemption_statuses", "value": json.dumps(clean), "label": "Reward status names and emails (JSON)",
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }).execute()
    return {"order": REDEMPTION_STATUSES, "statuses": redemption_templates()}


# ── Member tiers (names, points needed, benefits) ──────────────────────────
@router.get("/tiers")
def admin_list_tiers():
    return supabase_admin.table("tiers").select("*").order("min_points", desc=False).execute().data or []


@router.put("/tiers")
def admin_save_tiers(tiers: list = Body(..., embed=True)):
    """Replaces the tier list. Each item: {id?, name, min_points, benefits (one per line)}."""
    clean = []
    for t in tiers:
        name = str(t.get("name") or "").strip()
        try:
            min_points = int(t.get("min_points"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Points needed for {name or 'each tier'} must be a whole number.")
        if not name or min_points < 0:
            raise HTTPException(status_code=400, detail="Each tier needs a name and the points needed (0 or more).")
        clean.append({"id": t.get("id"), "name": name[:40], "min_points": min_points,
                      "benefits": "\n".join(b.strip() for b in str(t.get("benefits") or "").splitlines() if b.strip())})
    if not clean:
        raise HTTPException(status_code=400, detail="Keep at least one tier.")
    clean.sort(key=lambda t: t["min_points"])
    if clean[0]["min_points"] != 0:
        raise HTTPException(status_code=400, detail="The first tier must start at 0 points, so every member has a tier.")
    if len({t["min_points"] for t in clean}) != len(clean):
        raise HTTPException(status_code=400, detail="Two tiers can't need the same number of points.")

    existing = {r["id"] for r in (supabase_admin.table("tiers").select("id").execute().data or [])}
    keep = set()
    for order, t in enumerate(clean, start=1):
        row = {"name": t["name"], "min_points": t["min_points"], "benefits": t["benefits"], "sort_order": order}
        if t["id"] and t["id"] in existing:
            supabase_admin.table("tiers").update(row).eq("id", t["id"]).execute()
            keep.add(t["id"])
        else:
            supabase_admin.table("tiers").insert(row).execute()
    for old in existing - keep:
        supabase_admin.table("tiers").delete().eq("id", old).execute()
    return admin_list_tiers()


# Members see three stages: Invited → Pending / signed up → Points added (or Not proceeding).
# contacted / loan_in_progress / settled are older stages, still accepted and shown as the middle one.
REFERRAL_STAGES = ["invited", "registered", "contacted", "loan_in_progress", "settled", "rewarded", "closed"]
REFERRAL_PUSH_TEXT = {
    "registered": "{name} has signed up to Reliiance Rewards.",
    "contacted": "Reliiance has contacted {name}.",
    "loan_in_progress": "{name}'s loan is in progress.",
    "settled": "{name}'s loan has settled. Your points are on the way!",
}

@router.get("/referrals")
def admin_list_referrals():
    refs = supabase_admin.table("referrals").select("*").order("created_at", desc=True).execute().data or []
    ids = list({r["referrer_id"] for r in refs if r.get("referrer_id")})
    people = {}
    if ids:
        rows = supabase_admin.table("users").select("id, full_name, email").in_("id", ids).execute().data or []
        people = {u["id"]: u for u in rows}
    for r in refs:
        r["referrer"] = people.get(r.get("referrer_id"))
    return refs

@router.put("/referrals/{id}/stage")
def update_referral_stage(id: str, body: ReferralStageUpdate):
    """Move a referral along: invited → contacted → loan_in_progress → settled → rewarded (or closed).
    Moving to "rewarded" awards the referral points once."""
    status = (body.status or "").strip().lower()
    if status not in REFERRAL_STAGES:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {', '.join(REFERRAL_STAGES)}")
    ref_resp = supabase_admin.table("referrals").select("*").eq("id", id).execute()
    if not ref_resp.data:
        raise HTTPException(status_code=404, detail="Referral not found")
    ref = ref_resp.data[0]

    update = {"status": status, "stage_updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if body.admin_note is not None:
        update["admin_note"] = body.admin_note

    if status == "rewarded" and not (ref.get("points_earned") or 0):
        points = body.points if body.points is not None else get_int_setting("referral_points")
        if not points or points <= 0:
            raise HTTPException(status_code=400, detail="Set the referral points (in the request or the referral_points setting) before rewarding.")
        PointsService.award_points(
            user_id=ref["referrer_id"], points=points, type="referral",
            description=f"Referral reward: {ref.get('referred_name') or 'your friend'}", reference_id=id,
        )
        update["points_earned"] = points

    resp = supabase_admin.table("referrals").update(update).eq("id", id).execute()

    if status != (ref.get("status") or ""):
        friend = ref.get("referred_name") or "Your friend"
        if status == "rewarded" and update.get("points_earned"):
            title, body = f"+{update['points_earned']:,} points added", f"Thanks for referring {friend}!"
        else:
            title, body = "Referral update", REFERRAL_PUSH_TEXT.get(status, "").format(name=friend)
        if body:
            notify_service.push(ref["referrer_id"], "points" if status == "rewarded" else "referral", title, body, {"referral_id": id})
        if status in ("settled", "rewarded"):
            BonusService.first_referral(ref["referrer_id"], friend)
    return resp.data[0] if resp.data else update

# ── Member feedback from the app ───────────────────────────────────────────
FEEDBACK_STATUSES = {"new", "read", "resolved"}


@router.get("/feedback")
def list_feedback():
    rows = supabase_admin.table("feedback").select("*, users(full_name, email, mobile)").order("created_at", desc=True).execute().data or []
    return rows


@router.put("/feedback/{id}")
def update_feedback(id: str, status: str = Body(..., embed=True)):
    if status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail="Status must be new, read or resolved.")
    resp = supabase_admin.table("feedback").update({"status": status}).eq("id", id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return resp.data[0]


# ── Broker requests (Book a time / loan reviews) ──────────────────────────
BROKER_REQUEST_STATUSES = {"new", "contacted", "closed"}


@router.get("/broker-requests")
def list_broker_requests():
    return supabase_admin.table("loan_reviews").select("*, users(full_name, email, mobile, loan_settled_on)") \
        .order("created_at", desc=True).execute().data or []


@router.put("/broker-requests/{id}")
def update_broker_request(id: str, status: str = Body(None, embed=True), staff_note: str = Body(None, embed=True)):
    update = {"updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if status is not None:
        if status not in BROKER_REQUEST_STATUSES:
            raise HTTPException(status_code=400, detail="Status must be new, contacted or closed.")
        update["status"] = status
    if staff_note is not None:
        update["staff_note"] = staff_note.strip()[:1000] or None
    resp = supabase_admin.table("loan_reviews").update(update).eq("id", id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Request not found")
    return resp.data[0]


# ── Thank-you after an event ───────────────────────────────────────────────
@router.post("/events/{id}/thank-you")
def send_event_thank_you(id: str, message: str = Body(..., embed=True), slides_url: str = Body(None, embed=True),
                         recording_url: str = Body(None, embed=True), extra_url: str = Body(None, embed=True)):
    """Sends everyone who checked in a thank-you: phone alert, in-app update and (when email
    is set up) an email with the key points, links and a Contact us button."""
    from app.services.email_service import _EMAIL_ENABLED
    from app.services.program_service import get_setting

    message = (message or "").strip()
    if len(message) < 5:
        raise HTTPException(status_code=400, detail="Please write a short message with the key points.")
    links = []
    for label, url in (("Slides", slides_url), ("Recording", recording_url), ("More information", extra_url)):
        url = (url or "").strip()
        if url:
            if not url.startswith(("https://", "http://")):
                raise HTTPException(status_code=400, detail=f"{label} link must start with https://")
            links.append((label, url))

    ev = supabase_admin.table("events").select("id, title").eq("id", id).execute().data
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    title = ev[0]["title"]
    rsvps = supabase_admin.table("event_rsvps").select("user_id, attended, cancelled, users(full_name, email)") \
        .eq("event_id", id).execute().data or []
    attendees = [r for r in rsvps if r.get("attended") and not r.get("cancelled")]
    if not attendees:
        raise HTTPException(status_code=400, detail="Nobody has been checked in to this event yet.")

    broker_url = get_setting("contact_booking_url") or (f"mailto:{get_setting('contact_email')}" if get_setting("contact_email") else None)
    body = message + "".join(f"\n{label}: {url}" for label, url in links)
    notified = emailed = 0
    for r in attendees:
        if notify_service.notify_once(r["user_id"], "event_thanks", str(id), f"Thanks for coming to {title}", body, {"event_id": id}):
            notified += 1
            user = r.get("users") or {}
            if user.get("email") and EmailService.send_event_thank_you(
                    user["email"], (user.get("full_name") or "").split(" ")[0], title, message, links,
                    broker_url, get_setting("contact_name"), get_setting("contact_card_title") or "Contact us"):
                emailed += 1
    supabase_admin.table("events").update({"thank_you_sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}).eq("id", id).execute()
    return {"attendees": len(attendees), "notified": notified, "emailed": emailed, "email_enabled": _EMAIL_ENABLED}
