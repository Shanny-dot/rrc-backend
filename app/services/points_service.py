from app.core.supabase_client import supabase_admin
from fastapi import HTTPException


def db_error(e: Exception) -> str:
    """The reason raised by a points function (e.g. 'insufficient_points'), or ''."""
    text = str(getattr(e, "message", "") or e)
    for reason in ("insufficient_points", "user_not_found", "reward_not_found", "reward_inactive",
                   "out_of_stock", "below_minimum", "negative_balance"):
        if reason in text:
            return reason
    return ""


class PointsService:
    """Every balance change goes through a database function that updates the balance and
    writes the ledger row in one step (migration 012), so simultaneous requests can't spend
    the same points twice or lose an update."""

    @staticmethod
    def award_points(user_id: str, points: int, type: str, description: str, reference_id: str = None):
        try:
            supabase_admin.rpc("apply_points", {"p_user": user_id, "p_points": points, "p_type": type,
                                                "p_description": description, "p_reference": reference_id}).execute()
        except Exception as e:
            print(f"Error awarding points: {e}")
            raise HTTPException(status_code=500, detail="Failed to award points")
        # "Points added" / "tier upgrade" emails (never raises)
        from app.services.member_alerts import after_points_added
        after_points_added(user_id, points, type, description)
        return True

    @staticmethod
    def deduct_points(user_id: str, points: int, type: str, description: str, reference_id: str = None):
        try:
            supabase_admin.rpc("apply_points", {"p_user": user_id, "p_points": -abs(points), "p_type": type,
                                                "p_description": description, "p_reference": reference_id}).execute()
            return True
        except Exception as e:
            print(f"Error deducting points: {e}")
            if db_error(e) == "insufficient_points":
                raise HTTPException(status_code=400, detail="Insufficient points balance")
            raise HTTPException(status_code=500, detail="Failed to process point deduction")

    @staticmethod
    def set_points(user_id: str, new_points: int, description: str) -> int:
        """Staff set a balance to an exact figure; the difference is logged."""
        try:
            supabase_admin.rpc("set_points", {"p_user": user_id, "p_new": new_points,
                                              "p_description": description}).execute()
            return new_points
        except Exception as e:
            reason = db_error(e)
            if reason == "user_not_found":
                raise HTTPException(status_code=404, detail="User not found")
            if reason == "negative_balance":
                raise HTTPException(status_code=400, detail="Points can't be below zero")
            print(f"Error setting points: {e}")
            raise HTTPException(status_code=500, detail="Failed to update points")
