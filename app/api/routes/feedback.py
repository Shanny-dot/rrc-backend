from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from app.core.auth_middleware import get_current_user
from app.core.client_ip import client_ip
from app.core.config import settings
from app.core.supabase_client import supabase_admin
from app.services.email_service import EmailService

router = APIRouter()
limiter = Limiter(key_func=client_ip)

CATEGORIES = {"idea", "problem", "praise", "other"}


class FeedbackCreate(BaseModel):
    message: str
    category: Optional[str] = None
    app_version: Optional[str] = None
    platform: Optional[str] = None


@router.post("")
@router.post("/")
@limiter.limit("5/minute")
def send_feedback(request: Request, body: FeedbackCreate, current_user: dict = Depends(get_current_user)):
    """The app's "Send feedback" form. Saved for the admin website and emailed to staff."""
    message = (body.message or "").strip()
    if len(message) < 3:
        raise HTTPException(status_code=400, detail="Please write a little more so we can help.")
    category = (body.category or "other").lower()
    row = {
        "user_id": current_user.get("sub"),
        "category": category if category in CATEGORIES else "other",
        "message": message[:4000],
        "app_version": (body.app_version or "")[:20] or None,
        "platform": (body.platform or "")[:20] or None,
    }
    resp = supabase_admin.table("feedback").insert(row).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="Couldn't send your feedback. Please try again.")

    if settings.ADMIN_EMAIL:
        member = supabase_admin.table("users").select("full_name, email, mobile").eq("id", row["user_id"]).execute().data or [{}]
        EmailService.send_staff_feedback(settings.ADMIN_EMAIL, member[0], row)
    return {"success": True}
