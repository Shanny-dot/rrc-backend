import asyncio
import os
import random
import string
from app.core.supabase_client import supabase_admin

def generate_referral_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def fix():
    # Find the auth user
    users = supabase_admin.auth.admin.list_users()
    target_user = None
    for user in users:
        print(f"Found Auth User: {user.email}")
        if user.email == "shantanufadnavis2005@outlook.com":
            target_user = user
            break
            
    if not target_user:
        print("User not found in Auth!")
        return
        
    print(f"Fixing User: {target_user.email} with ID: {target_user.id}")
    
    # Check if they exist in DB
    check = supabase_admin.table("users").select("*").eq("id", target_user.id).execute()
    if check.data:
        print("User already inside public.users DB!")
        return
        
    # Insert them
    user_data = {
         "id": target_user.id,
         "full_name": "Shantanu",
         "email": target_user.email,
         "mobile": "+918000000000",
         "referral_code": generate_referral_code(),
         "total_points": 100,
         "bonus_points_granted": True
    }
    supabase_admin.table("users").insert(user_data).execute()
    print("User successfully synchronized into public.users database!")

fix()
