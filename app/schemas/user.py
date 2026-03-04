from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import date, datetime
import uuid

class UserBase(BaseModel):
    full_name: str
    email: EmailStr
    mobile: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None
    industry: Optional[str] = None
    street_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = "Australia"
    home_ownership: Optional[str] = None
    annual_income: Optional[str] = None

class UserCreate(UserBase):
    referral_code: Optional[str] = None # Code they used to sign up

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    mobile: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None
    industry: Optional[str] = None
    street_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    home_ownership: Optional[str] = None
    annual_income: Optional[str] = None
    fcm_token: Optional[str] = None

class UserInDB(UserBase):
    id: uuid.UUID
    total_points: int
    bonus_points_granted: bool
    profile_complete: bool
    referral_code: str
    referred_by: Optional[uuid.UUID] = None
    is_admin: bool
    fcm_token: Optional[str] = None
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
