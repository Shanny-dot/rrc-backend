from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List
from app.core.supabase_client import supabase_admin
from app.core.auth_middleware import get_current_admin
from app.schemas.event import EventCreate, EventUpdate, EventInDB, QRScanRequest
from app.schemas.reward import RewardCreate, RewardUpdate, RewardInDB
from app.schemas.redemption import RedemptionRejectRequest
from app.services.points_service import PointsService
from app.services.email_service import EmailService
from app.services.push_service import PushService
import datetime
import json
import os

# For now, get_current_admin is a placeholder or simplistic check in auth_middleware
# Assuming the route is protected by depends
router = APIRouter()

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

@router.put("/users/{id}/points")
def update_user_points(id: str, new_points: int = Body(..., embed=True), reason: str = Body("Admin adjustment", embed=True), admin: dict = Depends(get_current_admin)):
    user_resp = supabase_admin.table("users").select("total_points").eq("id", id).execute()
    if not user_resp.data:
        raise HTTPException(status_code=404, detail="User not found")
    
    current_points = user_resp.data[0].get("total_points", 0) or 0
    diff = new_points - current_points
    
    resp = supabase_admin.table("users").update({"total_points": new_points}).eq("id", id).execute()
    
    if diff != 0:
        tx_type = "admin_award" if diff > 0 else "admin_deduct"
        try:
            supabase_admin.table("point_transactions").insert({
                "user_id": id,
                "points": abs(diff),
                "type": tx_type,
                "description": f"{reason} (Updated from {current_points} to {new_points} pts)"
            }).execute()
        except Exception as e:
            print("Transaction log warning:", e)
            
    return {"message": f"Points updated to {new_points}", "data": resp.data[0]}

@router.get("/events")
def list_all_events():
    resp = supabase_admin.table("events").select("*").order("event_date", desc=False).execute()
    return resp.data

@router.post("/events", response_model=EventInDB)
def create_event(event: EventCreate):
    # Image upload to supabase storage should be handled by a separate script or directly from frontend to storage,
    # and then the URL is passed here in `event.image_url`. Just taking the URL for now.
    insert_data = json.loads(event.json())
    resp = supabase_admin.table("events").insert(insert_data).execute()
    if not resp.data:
         raise HTTPException(status_code=500, detail="Failed to create event")
    return resp.data[0]

@router.put("/events/{id}", response_model=EventInDB)
def update_event(id: str, event: EventUpdate):
    update_data = json.loads(event.json(exclude_unset=True))
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

@router.put("/redemptions/{id}/approve")
def approve_redemption(id: str):
    red_resp = supabase_admin.table("redemptions").select("*, users(email, fcm_token), rewards(title)").eq("id", id).single().execute()
    if not red_resp.data:
         raise HTTPException(status_code=404, detail="Redemption not found")
         
    redemption = red_resp.data
    if redemption["status"] != "pending":
         raise HTTPException(status_code=400, detail="Redemption is not pending")
         
    # 1. Update Status
    now = datetime.datetime.utcnow().isoformat()
    supabase_admin.table("redemptions").update({"status": "approved", "actioned_at": now}).eq("id", id).execute()
    
    # 2. Points were already deducted on request. Log a separate success context if needed, but standard is fine.
    
    # 3. Notification
    user_email = redemption["users"]["email"] if redemption.get("users") else None
    if user_email:
         # Need remaining balance:
         user_resp = supabase_admin.table("users").select("total_points").eq("id", redemption["user_id"]).single().execute()
         bal = user_resp.data["total_points"] if user_resp.data else 0
         
         EmailService.send_redemption_approved(
              to_email=user_email,
              reward_name=redemption["rewards"]["title"],
              points_used=redemption["points_used"],
              remaining_balance=bal
         )
         
    fcm_token = redemption["users"]["fcm_token"] if redemption.get("users") else None
    if fcm_token:
         PushService.send_push_notification(fcm_token, "Reward Approved!", f"Your request for {redemption['rewards']['title']} was approved.")
         
    return {"message": "Redemption approved"}

@router.put("/redemptions/{id}/reject")
def reject_redemption(id: str, req: RedemptionRejectRequest):
    red_resp = supabase_admin.table("redemptions").select("*, users(email, fcm_token), rewards(title)").eq("id", id).single().execute()
    if not red_resp.data:
         raise HTTPException(status_code=404, detail="Redemption not found")
         
    redemption = red_resp.data
    if redemption["status"] != "pending":
         raise HTTPException(status_code=400, detail="Redemption is not pending")
         
    # 1. Update Status
    now = datetime.datetime.utcnow().isoformat()
    supabase_admin.table("redemptions").update({
        "status": "rejected", 
        "admin_note": req.admin_note,
        "actioned_at": now
    }).eq("id", id).execute()
    
    # 2. Refund Points
    PointsService.award_points(
         user_id=redemption["user_id"],
         points=redemption["points_used"],
         type="redemption_refund",
         description=f"Refund for rejected redemption: {redemption['rewards']['title']}"
    )
    
    # 3. Increase Stock back
    reward_id = redemption["reward_id"]
    rew_resp = supabase_admin.table("rewards").select("stock").eq("id", reward_id).single().execute()
    if rew_resp.data and rew_resp.data.get("stock") is not None:
         supabase_admin.table("rewards").update({"stock": rew_resp.data["stock"] + 1}).eq("id", reward_id).execute()

    # 4. Notification
    user_email = redemption["users"]["email"] if redemption.get("users") else None
    if user_email:
         user_resp = supabase_admin.table("users").select("total_points").eq("id", redemption["user_id"]).single().execute()
         bal = user_resp.data["total_points"] if user_resp.data else 0
         
         EmailService.send_redemption_rejected(
              to_email=user_email,
              reward_name=redemption["rewards"]["title"],
              refund_note=req.admin_note,
              remaining_balance=bal
         )
         
    fcm_token = redemption["users"]["fcm_token"] if redemption.get("users") else None
    if fcm_token:
         PushService.send_push_notification(fcm_token, "Reward Rejected", f"Your request for {redemption['rewards']['title']} was refunded.")

    return {"message": "Redemption rejected"}

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
              supabase_admin.table("event_guests").update({"attended": True, "points_awarded_to_inviter": True}).eq("id", guest["id"]).execute()

    return {"message": "QR Scan Successful, Points Awarded"}

@router.get("/transactions")
def admin_list_transactions(user_id: str = None):
    query = supabase_admin.table("transactions").select("*")
    if user_id:
         query = query.eq("user_id", user_id)
    resp = query.order("created_at", desc=True).execute()
    return resp.data
