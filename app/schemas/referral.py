from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

class ReferralCreate(BaseModel):
    referred_name: str
    referred_mobile: Optional[str] = None
    referred_email: Optional[str] = None

class ReferralInDB(ReferralCreate):
    id: uuid.UUID
    referrer_id: uuid.UUID
    referred_user_id: Optional[uuid.UUID] = None
    status: str
    points_earned: int
    created_at: datetime
