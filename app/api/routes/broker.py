import datetime
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

TIME_LABELS = {"morning": "morning", "afternoon": "afternoon", "evening": "evening", "anytime": "any time"}
KINDS = {"call": "Call booking", "loan_review": "Loan review"}


class BrokerRequestCreate(BaseModel):
    kind: str = "call"                    # call | loan_review
    preferred_date: Optional[str] = None  # YYYY-MM-DD
    preferred_time: Optional[str] = None  # morning | afternoon | evening | anytime
    note: Optional[str] = None


def describe(kind: str, preferred_date: Optional[str], preferred_time: Optional[str], note: Optional[str]) -> str:
    """One readable line for staff, e.g. "Call booking: Tue 21 Oct 2026, morning. Best on mobile."."""
    parts = [KINDS.get(kind, "Call booking")]
    when = []
    if preferred_date:
        try:
            when.append(datetime.date.fromisoformat(preferred_date).strftime("%a %d %b %Y"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Please pick a valid date.")
    if preferred_time in TIME_LABELS:
        when.append(TIME_LABELS[preferred_time])
    text = parts[0] + (f": {', '.join(when)}" if when else "")
    note = (note or "").strip()
    return f"{text}. {note[:1000]}" if note else f"{text}."


@router.post("/requests")
@limiter.limit("5/minute")
def create_request(request: Request, body: BrokerRequestCreate, current_user: dict = Depends(get_current_user)):
    """"Book a time" (when no booking link is set) and the yearly loan check-in's
    "Request a review": the member asks their broker to get in touch."""
    if body.kind not in KINDS:
        raise HTTPException(status_code=400, detail="Unknown request type.")
    if body.preferred_date:
        try:
            if datetime.date.fromisoformat(body.preferred_date) < datetime.date.today() - datetime.timedelta(days=1):
                raise HTTPException(status_code=400, detail="Please pick a date from today onwards.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Please pick a valid date.")
    user_id = current_user.get("sub")
    note = describe(body.kind, body.preferred_date, body.preferred_time, body.note)
    resp = supabase_admin.table("loan_reviews").insert({"user_id": user_id, "note": note}).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="Couldn't send your request. Please try again.")
    if settings.ADMIN_EMAIL:
        member = supabase_admin.table("users").select("full_name, email, mobile").eq("id", user_id).execute().data or [{}]
        EmailService.send_staff_broker_request(settings.ADMIN_EMAIL, member[0], note)
    return {"success": True, "id": resp.data[0]["id"]}
