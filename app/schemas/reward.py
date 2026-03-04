from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

class RewardBase(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    points_required: int
    image_url: Optional[str] = None
    stock: Optional[int] = None
    is_active: bool = True

class RewardCreate(RewardBase):
    pass

class RewardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    points_required: Optional[int] = None
    image_url: Optional[str] = None
    stock: Optional[int] = None
    is_active: Optional[bool] = None

class RewardInDB(RewardBase):
    id: uuid.UUID
    created_at: datetime
