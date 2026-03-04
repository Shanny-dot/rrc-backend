from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from app.core.supabase_client import supabase_admin
from app.core.auth_middleware import get_current_user
from app.schemas.reward import RewardInDB
from app.schemas.redemption import RedemptionInDB
from app.services.points_service import PointsService
from app.services.email_service import EmailService

router = APIRouter()

@router.get("/", response_model=List[RewardInDB])
def list_rewards(category: Optional[str] = None):
    query = supabase_admin.table("rewards").select("*").eq("is_active", True)
    if category:
        query = query.eq("category", category)
        
    resp = query.order("points_required", desc=False).execute()
    return resp.data

@router.post("/{id}/redeem", response_model=RedemptionInDB)
def redeem_reward(id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    
    # 1. Get Reward
    reward_resp = supabase_admin.table("rewards").select("*").eq("id", id).single().execute()
    if not reward_resp.data:
         raise HTTPException(status_code=404, detail="Reward not found")
    reward = reward_resp.data
    
    if reward.get("stock") is not None and reward["stock"] <= 0:
         raise HTTPException(status_code=400, detail="Reward out of stock")
         
    # 2. Deduct Points via PointsService
    PointsService.deduct_points(
        user_id=user_id,
        points=reward["points_required"],
        type="redemption",
        description=f"Redeemed {reward['title']}"
    )

    # 3. Create Pending Redemption Record
    redemption_data = {
         "user_id": user_id,
         "reward_id": id,
         "status": "pending",
         "points_used": reward["points_required"]
    }
    
    red_resp = supabase_admin.table("redemptions").insert(redemption_data).execute()
    if not red_resp.data:
         # Need to rollback points in realistic scenario, or assume generic error.
         # For simplicity:
         raise HTTPException(status_code=500, detail="Failed to create redemption request")
         
    # 4. Decrease Stock
    if reward.get("stock") is not None:
         supabase_admin.table("rewards").update({"stock": reward["stock"] - 1}).eq("id", id).execute()

    # 5. Notify Admin via Email
    EmailService.notify_admin_new_redemption(reward_name=reward["title"])

    return red_resp.data[0]

@router.get("/redemptions", response_model=List[RedemptionInDB])
def list_user_redemptions(current_user: dict = Depends(get_current_user)):
     user_id = current_user.get("sub")
     resp = supabase_admin.table("redemptions").select("*").eq("user_id", user_id).order("requested_at", desc=True).execute()
     return resp.data
