from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import os
from app.core.config import settings
from app.core.supabase_client import supabase_admin, supabase_anon

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        # Try local offline verification first using the configured secret or bypass secret
        jwt_secret = os.environ.get("SUPABASE_JWT_SECRET", settings.JWT_SECRET)
        payload = jwt.decode(
            credentials.credentials,
            jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False}
        )
        return payload
    except Exception as base_err:
        try:
            # Fallback: Remote verification if the local .env JWT_SECRET is incorrect
            user_response = supabase_anon.auth.get_user(credentials.credentials)
            if user_response and user_response.user:
                return {"sub": user_response.user.id, "email": user_response.user.email}
        except Exception as e:
            print(f"Auth Fallback Error: {e} | Base Error: {base_err}")
            
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {base_err}",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_current_admin(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    resp = supabase_admin.table("users").select("is_admin").eq("id", user_id).execute()
    if not resp.data or not resp.data[0].get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions. Admin access required.",
        )
        
    return current_user
