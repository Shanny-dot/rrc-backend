from fastapi import APIRouter, Depends
from app.core.auth_middleware import get_current_user
from app.services.program_service import activity_for_user

router = APIRouter()

@router.get("/")
def list_transactions(current_user: dict = Depends(get_current_user)):
    """Member activity, newest first. Each row keeps its original fields and adds
    `title`, `status_label` (Pending / Approved / Sent / Refunded / Points added / Points removed)
    and, for redemptions, `redemption_id`."""
    return activity_for_user(current_user.get("sub"))
