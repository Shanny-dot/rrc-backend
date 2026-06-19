from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from typing import Optional
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.supabase_client import supabase_anon, supabase_admin
from app.core.auth_middleware import get_current_user
from app.schemas.user import UserCreate, UserUpdate, TokenResponse
from app.services.email_service import EmailService
from app.services.points_service import PointsService
import random
import string

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

class RegisterCredentials(BaseModel):
    full_name: str
    email: str
    password: str
    mobile: Optional[str] = None
    referral_code: Optional[str] = None

class LoginCredentials(BaseModel):
    email: str
    password: str

class FCMTokenRequest(BaseModel):
    fcm_token: str

def generate_referral_code(length=8):
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for i in range(length))

@router.post("/register", response_model=TokenResponse)
@limiter.limit("5/minute")
def register(request: Request, creds: RegisterCredentials):
    try:
        if not creds.mobile:
             raise HTTPException(status_code=400, detail="Mobile number is required for SMS auth")
             
        # 1. Sign up with Supabase Auth bypassing Rate Limits (Admin API)
        # Bypasses the 3 emails/hour GoTrue limits
        try:
            auth_response = supabase_admin.auth.admin.create_user({
                "email": creds.email,
                "password": creds.password,
                "email_confirm": True,
                "user_metadata": {
                    "full_name": creds.full_name,
                }
            })
            user = auth_response.user
        except Exception as create_err:
            if "already exists" in str(create_err).lower():
                raise HTTPException(status_code=400, detail="An account with this email already exists.")
            raise create_err
        
        if not user:
            raise HTTPException(status_code=400, detail="Signup failed")
        
        # 2. Check for referral code validity
        referred_by_id = None
        if creds.referral_code:
            ref_resp = supabase_admin.table("users").select("id").eq("referral_code", creds.referral_code.upper()).execute()
            if ref_resp.data:
                referred_by_id = ref_resp.data[0]["id"]
            
        # 3. Create public.users profile record
        unique_ref_code = generate_referral_code()
        
        user_data = {
            "id": user.id, # Link directly to the Auth UUID
            "full_name": creds.full_name,
            "email": creds.email,
            "mobile": creds.mobile,
            "referral_code": unique_ref_code,
            "referred_by": referred_by_id,
            "total_points": 0,
            "bonus_points_granted": False
        }
        
        # Insert user via admin to bypass constraints if needed on registration
        supabase_admin.table("users").insert(user_data).execute()
        
        # 4. Handle Referral Tracking if they used a code
        if referred_by_id:
             # Find the pending referral and update it
             ref_update_resp = supabase_admin.table("referrals").update({
                   "status": "registered",
                   "referred_user_id": user.id
             }).eq("referrer_id", referred_by_id).eq("referred_email", creds.email).execute()

             # If no explicit referral invite existed but they used a code anyway:
             if not ref_update_resp.data:
                  supabase_admin.table("referrals").insert({
                      "referrer_id": referred_by_id,
                      "referred_name": creds.full_name,
                      "referred_email": creds.email,
                      "referred_mobile": creds.mobile,
                      "status": "registered",
                      "referred_user_id": user.id
                  }).execute()
        # Auto-format phone numbers for Twilio E.164
        formatted_mobile = creds.mobile.strip()
        # If it doesn't already start with a '+', attempt to map Aus/Ind
        if not formatted_mobile.startswith('+'):
            # Indian numbers are exactly 10 digits
            if len(formatted_mobile) == 10:
                formatted_mobile = f"+91{formatted_mobile}"
            # Australian numbers without leading zero are 9 digits (e.g., 412 345 678)
            elif len(formatted_mobile) == 9:
                formatted_mobile = f"+61{formatted_mobile}"
            # Australian mobile with leading zero (e.g., 0412 345 678)
            elif len(formatted_mobile) == 10 and formatted_mobile.startswith('0'):
                formatted_mobile = f"+61{formatted_mobile[1:]}"
            else:
                formatted_mobile = f"+{formatted_mobile}"

        # 5. Trigger Twilio SMS via Supabase OTP Sign In
        # Even though they just signed up, calling OTP sign-in issues the SMS for verification
        supabase_anon.auth.sign_in_with_otp({
             "phone": formatted_mobile
        })
        
        # 6. Award 100 pt Signup Bonus
        PointsService.award_points(
            user_id=user.id,
            points=100,
            type="signup_bonus",
            description="Welcome Bonus"
        )
        supabase_admin.table("users").update({"bonus_points_granted": True}).eq("id", user.id).execute()
        
        # Note: Email welcome disabled as per user instruction. 
        # For the admin creation path, we don't have a session inherently returned, 
        # but the OTP sign_in_with_otp above will issue the session upon verification!
        return TokenResponse(access_token="pending_verification")

    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Registration Error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

class ResendOTPRequest(BaseModel):
    mobile: str

@router.post("/resend-otp")
@limiter.limit("5/minute")
def resend_otp(request: Request, req: ResendOTPRequest):
    try:
        formatted_mobile = req.mobile.strip()
        if not formatted_mobile.startswith('+'):
            if len(formatted_mobile) == 10:
                formatted_mobile = f"+91{formatted_mobile}"
            elif len(formatted_mobile) == 9:
                formatted_mobile = f"+61{formatted_mobile}"
            elif len(formatted_mobile) == 10 and formatted_mobile.startswith('0'):
                formatted_mobile = f"+61{formatted_mobile[1:]}"
            else:
                formatted_mobile = f"+{formatted_mobile}"
                
        supabase_anon.auth.sign_in_with_otp({
             "phone": formatted_mobile
        })
        return {"success": True, "message": "OTP sent successfully"}
    except Exception as e:
        print(f"Resend OTP Error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

class VerifyMobileRequest(BaseModel):
    mobile: str
    code: str

@router.post("/verify-mobile")
@limiter.limit("10/minute")
def verify_mobile(request: Request, req: VerifyMobileRequest):
    try:
        # Normalise phone to E.164 (must match what was used when OTP was sent)
        formatted_mobile = req.mobile.strip()
        if not formatted_mobile.startswith('+'):
            if len(formatted_mobile) == 10 and not formatted_mobile.startswith('0'):
                formatted_mobile = f"+91{formatted_mobile}"
            elif len(formatted_mobile) == 9:
                formatted_mobile = f"+61{formatted_mobile}"
            elif len(formatted_mobile) == 10 and formatted_mobile.startswith('0'):
                formatted_mobile = f"+61{formatted_mobile[1:]}"
            else:
                formatted_mobile = f"+{formatted_mobile}"

        # Normal Flow: Verify the Twilio SMS via Supabase
        verify_response = supabase_anon.auth.verify_otp({
            "phone": formatted_mobile,
            "token": req.code,
            "type": "sms"
        })
        
        if not verify_response.session:
             raise HTTPException(status_code=400, detail="Invalid OTP code or session expired")
             
        return {"success": True, "message": "Mobile number verified", "access_token": verify_response.session.access_token}

    except Exception as e:
         raise HTTPException(status_code=400, detail=str(e))

@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, creds: LoginCredentials):
    try:
        auth_response = supabase_anon.auth.sign_in_with_password({
            "email": creds.email,
            "password": creds.password
        })
        if not auth_response.session:
             raise Exception("Invalid credentials")
        return TokenResponse(access_token=auth_response.session.access_token)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid login credentials")

@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    print(f"DEBUG /me: Looking up user_id={user_id}")
    resp = supabase_admin.table("users").select("*").eq("id", user_id).execute()
    print(f"DEBUG /me: Supabase response={resp.data}")
    if not resp.data:
        raise HTTPException(status_code=404, detail="User not found")
    return resp.data[0]

@router.put("/profile")
def update_profile(profile: UserUpdate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    
    update_data = {k: v for k, v in profile.dict(exclude_unset=True).items()}
    
    if update_data:
         # simple logic to check profile complete
         # if all essential fields are there, set profile_complete = true
         # (omitted for brevity, assume simple update)
         resp = supabase_admin.table("users").update(update_data).eq("id", user_id).execute()
         return resp.data[0] if resp.data else {}
    return {"message": "No data provided"}

@router.put("/fcm-token")
def update_fcm_token(req: FCMTokenRequest, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    resp = supabase_admin.table("users").update({"fcm_token": req.fcm_token}).eq("id", user_id).execute()
    return {"message": "FCM token updated successfully"}
