from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

class EventBase(BaseModel):
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    event_date: datetime
    image_url: Optional[str] = None
    points_for_attending: int = 0
    points_for_referring: int = 0
    capacity: Optional[int] = None
    is_active: bool = True

class EventCreate(EventBase):
    pass

class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    event_date: Optional[datetime] = None
    image_url: Optional[str] = None
    points_for_attending: Optional[int] = None
    points_for_referring: Optional[int] = None
    capacity: Optional[int] = None
    is_active: Optional[bool] = None

class EventInDB(EventBase):
    id: uuid.UUID
    created_at: datetime

class GuestCreate(BaseModel):
    guest_name: str
    guest_mobile: Optional[str] = None
    guest_email: Optional[str] = None

class GuestInDB(GuestCreate):
    id: uuid.UUID
    rsvp_id: uuid.UUID
    inviter_user_id: uuid.UUID
    attended: bool
    points_awarded_to_inviter: bool

class RSVPInDB(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID
    qr_token: str
    attended: bool
    points_awarded: bool
    rsvp_at: datetime
    attended_at: Optional[datetime] = None

class QRScanRequest(BaseModel):
    qr_token: str
