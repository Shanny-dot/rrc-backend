from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from app.core.supabase_client import supabase_admin
from app.core.auth_middleware import get_current_user
from app.schemas.reward import RewardInDB
from app.schemas.redemption import RedemptionInDB
from app.services.points_service import PointsService
from app.services.email_service import EmailService
from app.services.program_service import get_setting, get_int_setting
from app.services import redemption_service

router = APIRouter()


def _with_defaults(reward: dict, default_delivery: str) -> dict:
    if not reward.get("delivery_info") and default_delivery:
        reward = dict(reward)
        reward["delivery_info"] = default_delivery
    return reward


@router.get("", response_model=List[RewardInDB], include_in_schema=False)
@router.get("/", response_model=List[RewardInDB])
def list_rewards(category: Optional[str] = None):
    query = supabase_admin.table("rewards").select("*").eq("is_active", True)
    if category:
        query = query.eq("category", category)
    resp = query.order("points_required", desc=False).execute()
    default_delivery = get_setting("reward_delivery_default")
    return [_with_defaults(r, default_delivery) for r in (resp.data or [])]


# Fixed paths are declared before "/{id}" so they aren't captured by it.
@router.get("/redemptions", response_model=List[RedemptionInDB])
def list_user_redemptions(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    resp = supabase_admin.table("redemptions").select("*").eq("user_id", user_id).order("requested_at", desc=True).execute()
    return resp.data


@router.get("/wishlist")
def get_wishlist(current_user: dict = Depends(get_current_user)):
    """IDs of rewards the member saved to their wish list."""
    resp = supabase_admin.table("wishlist").select("reward_id").eq("user_id", current_user.get("sub")).execute()
    return [r["reward_id"] for r in (resp.data or [])]


@router.get("/{id}", response_model=RewardInDB)
def get_reward(id: str):
    resp = supabase_admin.table("rewards").select("*").eq("id", id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Reward not found")
    return _with_defaults(resp.data[0], get_setting("reward_delivery_default"))


@router.post("/{id}/wishlist")
def add_to_wishlist(id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    existing = supabase_admin.table("wishlist").select("id").eq("user_id", user_id).eq("reward_id", id).execute()
    if not existing.data:
        supabase_admin.table("wishlist").insert({"user_id": user_id, "reward_id": id}).execute()
    return {"saved": True}


@router.delete("/{id}/wishlist")
def remove_from_wishlist(id: str, current_user: dict = Depends(get_current_user)):
    supabase_admin.table("wishlist").delete().eq("user_id", current_user.get("sub")).eq("reward_id", id).execute()
    return {"saved": False}


@router.post("/{id}/redeem", response_model=RedemptionInDB)
def redeem_reward(id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")

    # 1. Reward must exist, be active and in stock
    reward_resp = supabase_admin.table("rewards").select("*").eq("id", id).execute()
    if not reward_resp.data:
        raise HTTPException(status_code=404, detail="Reward not found")
    reward = reward_resp.data[0]
    if not reward.get("is_active", True):
        raise HTTPException(status_code=400, detail="This reward is no longer available")
    if reward.get("stock") is not None and reward["stock"] <= 0:
        raise HTTPException(status_code=400, detail="Reward out of stock")

    # 2. Check the balance before creating anything
    user_resp = supabase_admin.table("users").select("total_points, email, full_name").eq("id", user_id).execute()
    if not user_resp.data:
        raise HTTPException(status_code=404, detail="User not found")
    user = user_resp.data[0]
    balance = user.get("total_points") or 0
    # The minimum only applies to a member's first reward; rejected requests don't count.
    minimum = get_int_setting("min_points_to_redeem")
    first_reward = minimum > 0 and not supabase_admin.table("redemptions").select("id").eq("user_id", user_id) \
        .neq("status", "rejected").limit(1).execute().data
    if first_reward and balance < minimum:
        raise HTTPException(status_code=400, detail=(
            f"You need at least {minimum:,} points in your account before you can redeem your first reward "
            f"(you have {balance:,}). Earn more by referring friends and attending events."))
    if balance < reward["points_required"]:
        raise HTTPException(status_code=400, detail="Insufficient points balance")

    # 3. Create the pending redemption first, so the points transaction can reference it
    red_resp = supabase_admin.table("redemptions").insert({
        "user_id": user_id,
        "reward_id": id,
        "status": "pending",
        "points_used": reward["points_required"],
    }).execute()
    if not red_resp.data:
        raise HTTPException(status_code=500, detail="Failed to create redemption request")
    redemption = red_resp.data[0]

    # 4. Deduct points, linked to the redemption; undo the redemption if that fails
    try:
        PointsService.deduct_points(
            user_id=user_id,
            points=reward["points_required"],
            type="redemption",
            description=f"Redeemed {reward['title']}",
            reference_id=redemption["id"],
        )
    except HTTPException:
        supabase_admin.table("redemptions").delete().eq("id", redemption["id"]).execute()
        raise

    # 5. Decrease stock
    if reward.get("stock") is not None:
        supabase_admin.table("rewards").update({"stock": reward["stock"] - 1}).eq("id", id).execute()

    # 6. Emails: confirmation to the member, alert to staff
    redemption_service.notify_status(redemption["id"], "pending")
    EmailService.notify_admin_new_redemption(reward_name=reward["title"], member_name=user.get("full_name"))

    return redemption
