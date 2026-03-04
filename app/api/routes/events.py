from fastapi import APIRouter, Depends, HTTPException
from typing import List
from app.core.supabase_client import supabase_admin
from app.core.auth_middleware import get_current_user
from app.schemas.event import EventInDB, RSVPInDB, GuestCreate
from app.services.qr_service import QRService
from app.services.email_service import EmailService
import uuid

router = APIRouter()

@router.get("/", response_model=List[EventInDB])
def list_events():
    resp = supabase_admin.table("events").select("*").eq("is_active", True).order("event_date", desc=False).execute()
    return resp.data

@router.get("/{id}", response_model=EventInDB)
def get_event(id: str):
    resp = supabase_admin.table("events").select("*").eq("id", id).single().execute()
    if not resp.data:
         raise HTTPException(status_code=404, detail="Event not found")
    return resp.data

@router.post("/{id}/rsvp", response_model=RSVPInDB)
def rsvp_event(id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    
    # 1. Check if event exists
    event_resp = supabase_admin.table("events").select("*").eq("id", id).single().execute()
    if not event_resp.data:
         raise HTTPException(status_code=404, detail="Event not found")
    event = event_resp.data
    
    # 2. Check if already RSVP'd
    existing = supabase_admin.table("event_rsvps").select("*").eq("event_id", id).eq("user_id", user_id).execute()
    if existing.data:
         raise HTTPException(status_code=400, detail="You have already RSVP'd to this event")
         
    # 3. Generate Unique QR Token
    qr_token = f"evt_{uuid.uuid4().hex[:16]}"
    
    # 4. Create RSVP
    rsvp_data = {
         "event_id": id,
         "user_id": user_id,
         "qr_token": qr_token,
    }
    
    rsvp_resp = supabase_admin.table("event_rsvps").insert(rsvp_data).execute()
    if not rsvp_resp.data:
         raise HTTPException(status_code=500, detail="Failed to RSVP")
         
    # 5. Generate QR Image & Send Email
    user_resp = supabase_admin.table("users").select("email").eq("id", user_id).single().execute()
    user_email = user_resp.data["email"] if user_resp.data else None
    
    if user_email:
         qr_base64 = QRService.generate_qr_base64(qr_token)
         # Format date for email simply
         event_date_str = str(event["event_date"])
         EmailService.send_rsvp_confirmation(
              to_email=user_email,
              event_name=event["title"],
              event_date=event_date_str,
              event_location=event["location"],
              qr_base64=qr_base64
         )
         
    return rsvp_resp.data[0]

@router.post("/{id}/invite-guests")
def invite_guests(id: str, guests: List[GuestCreate], current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    
    # 1. Get Event and Inviter Details
    event_resp = supabase_admin.table("events").select("title").eq("id", id).single().execute()
    if not event_resp.data:
         raise HTTPException(status_code=404, detail="Event not found")
    event_title = event_resp.data["title"]
    
    user_resp = supabase_admin.table("users").select("full_name").eq("id", user_id).single().execute()
    inviter_name = user_resp.data["full_name"] if user_resp.data else "A Friend"
    
    # 2. Check if user RSVP'd
    rsvp_resp = supabase_admin.table("event_rsvps").select("id").eq("event_id", id).eq("user_id", user_id).execute()
    if not rsvp_resp.data:
        # Create a Ghost RSVP for the inviter so they can link guests
        import uuid
        qr_token = f"evt_{uuid.uuid4().hex[:16]}"
        new_rsvp = supabase_admin.table("event_rsvps").insert({
             "event_id": id,
             "user_id": user_id,
             "qr_token": qr_token
        }).execute()
        rsvp_id = new_rsvp.data[0]["id"]
    else:
        rsvp_id = rsvp_resp.data[0]["id"]
    
    # 3. Insert Guests and send emails
    inserted_guests = []
    for guest in guests:
         guest_data = {
              "rsvp_id": rsvp_id,
              "inviter_user_id": user_id,
              "guest_name": guest.guest_name,
              "guest_mobile": guest.guest_mobile,
              "guest_email": guest.guest_email
         }
         res = supabase_admin.table("event_guests").insert(guest_data).execute()
         if res.data:
             inserted_guests.append(res.data[0])
             
             # Send Invite Email if email exists
             if guest.guest_email:
                  EmailService.send_guest_invite(
                       to_email=guest.guest_email,
                       inviter_name=inviter_name,
                       event_name=event_title
                  )
                  
    return {"message": f"Successfully invited {len(inserted_guests)} guests", "guests": inserted_guests}

@router.post("/{id}/scan-attendance")
def scan_attendance(id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    user_email = current_user.get("email")
    
    # 1. Check Event
    event_resp = supabase_admin.table("events").select("*").eq("id", id).single().execute()
    if not event_resp.data:
        raise HTTPException(status_code=404, detail="Event not found")
    event = event_resp.data
    
    # 2. Fetch or Create RSVP
    rsvp_resp = supabase_admin.table("event_rsvps").select("*").eq("event_id", id).eq("user_id", user_id).execute()
    if not rsvp_resp.data:
        import uuid
        qr_token = f"evt_{uuid.uuid4().hex[:16]}"
        new_rsvp = supabase_admin.table("event_rsvps").insert({
            "event_id": id, "user_id": user_id, "qr_token": qr_token
        }).execute()
        rsvp = new_rsvp.data[0]
    else:
        rsvp = rsvp_resp.data[0]
        
    if rsvp["attended"]:
        raise HTTPException(status_code=400, detail="You have already claimed points for this event.")
        
    # 3. Mark Attended
    import datetime
    now = datetime.datetime.utcnow().isoformat()
    supabase_admin.table("event_rsvps").update({"attended": True, "attended_at": now, "points_awarded": True}).eq("id", rsvp["id"]).execute()
    
    # 4. Award User Attendance Points
    from app.services.points_service import PointsService
    if event.get("points_for_attending", 0) > 0:
        PointsService.award_points(user_id=user_id, points=event["points_for_attending"], type="event_attend", description=f"Attended {event['title']}")
        
    # 5. Check if they were invited by someone else to THIS specific event
    guest_resp = supabase_admin.table("event_guests").select("*").eq("guest_email", user_email).eq("points_awarded_to_inviter", False).execute()
    if guest_resp.data:
        for guest in guest_resp.data:
            inv_rsvp = supabase_admin.table("event_rsvps").select("event_id").eq("id", guest["rsvp_id"]).single().execute()
            if inv_rsvp.data and inv_rsvp.data["event_id"] == id:
                # Award Inviter Points
                if event.get("points_for_referring", 0) > 0:
                    PointsService.award_points(user_id=guest["inviter_user_id"], points=event["points_for_referring"], type="event_guest", description=f"Your invited guest attended {event['title']}")
                supabase_admin.table("event_guests").update({"attended": True, "points_awarded_to_inviter": True}).eq("id", guest["id"]).execute()
                break # Only process one inviter
                
    return {"message": "Attendance confirmed! Points awarded."}
