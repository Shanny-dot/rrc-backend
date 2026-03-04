from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

class RedemptionCreate(BaseModel):
     pass # Usually just the ID is sent in the URL, but empty schema is good for structured POST bodies if needed

class RedemptionInDB(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    reward_id: uuid.UUID
    status: str
    points_used: int
    admin_note: Optional[str] = None
    requested_at: datetime
    actioned_at: Optional[datetime] = None

class RedemptionRejectRequest(BaseModel):
    admin_note: str
