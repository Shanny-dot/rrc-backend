from fastapi import APIRouter, Depends
from typing import List
from app.core.supabase_client import supabase_admin
from app.core.auth_middleware import get_current_user

router = APIRouter()

@router.get("/")
def list_transactions(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    resp = supabase_admin.table("transactions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return resp.data
