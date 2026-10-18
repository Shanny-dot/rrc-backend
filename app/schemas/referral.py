from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

# How the member sent the invite. sms/whatsapp/share are sent from the member's own phone
# (share sheet); email/form/contacts get the backend's invite email from no-reply.
REFERRAL_CHANNELS = {"sms", "whatsapp", "share", "email", "form", "contacts", "code"}

class ReferralCreate(BaseModel):
    referred_name: str
    referred_mobile: Optional[str] = None
    referred_email: Optional[str] = None
    # Both are None when the request comes from app 3.0.0, which predates them.
    channel: Optional[str] = None
    consent_given: Optional[bool] = None
    notes: Optional[str] = None

class ReferralInDB(BaseModel):
    id: uuid.UUID
    referrer_id: uuid.UUID
    referred_name: str
    referred_mobile: Optional[str] = None
    referred_email: Optional[str] = None
    referred_user_id: Optional[uuid.UUID] = None
    status: str
    points_earned: int
    channel: Optional[str] = None
    stage_updated_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    invite_emailed: Optional[bool] = None  # only on create: true when we emailed the invitation

class ReferralStageUpdate(BaseModel):
    status: str
    admin_note: Optional[str] = None
    points: Optional[int] = None   # only used when moving to "rewarded"
