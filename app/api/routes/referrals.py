from fastapi import APIRouter, Depends, HTTPException
from typing import List
from app.core.supabase_client import supabase_admin
from app.core.auth_middleware import get_current_user
from app.schemas.referral import ReferralCreate, ReferralInDB
from app.services.email_service import EmailService

router = APIRouter()

@router.post("/", response_model=ReferralInDB)
def create_referral(referral: ReferralCreate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    
    # 1. Check if they already referred this email
    existing = supabase_admin.table("referrals").select("*").eq("referrer_id", user_id).eq("referred_email", referral.referred_email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="You have already referred this email address.")
    
    # 2. Get inviter's name
    user_resp = supabase_admin.table("users").select("full_name").eq("id", user_id).single().execute()
    inviter_name = user_resp.data["full_name"] if user_resp.data else "A friend"

    # 3. Insert pending referral
    new_ref = {
        "referrer_id": user_id,
        "referred_name": referral.referred_name,
        "referred_mobile": referral.referred_mobile,
        "referred_email": referral.referred_email,
        "status": "pending"
    }
    
    resp = supabase_admin.table("referrals").insert(new_ref).execute()
    
    if not resp.data:
         raise HTTPException(status_code=500, detail="Failed to create referral record")
         
    # 4. Send Email invite via Resend
    EmailService.send_referral_invite(
         to_email=referral.referred_email,
         inviter_name=inviter_name
    )

    return resp.data[0]

@router.get("/", response_model=List[ReferralInDB])
def list_referrals(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    resp = supabase_admin.table("referrals").select("*").eq("referrer_id", user_id).order("created_at", desc=True).execute()
    return resp.data
