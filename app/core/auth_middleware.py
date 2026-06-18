from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import os
from app.core.config import settings
from app.core.supabase_client import supabase_admin, supabase_anon

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    # Always verify via Supabase Auth (handles both HS256 and ES256 tokens correctly)
    try:
        user_response = supabase_anon.auth.get_user(token)
        if user_response and user_response.user:
            return {"sub": user_response.user.id, "email": user_response.user.email, "role": "authenticated"}
    except Exception as e:
        pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
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
