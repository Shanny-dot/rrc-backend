import os
import uuid
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(url, key)

email = "admin@rrc.com"
# fetch the user_id from auth if possible, or just insert
from app.core.supabase_client import supabase_admin
auth_users = supabase_admin.auth.admin.list_users()

admin_id = None
for usr in auth_users:
    if usr.email == email:
        admin_id = usr.id
        break

if admin_id:
    # Check if row exists in public.users
    existing = supabase.table("users").select("id").eq("id", admin_id).execute()
    if not existing.data:
        print(f"Inserting {admin_id} into public.users")
        supabase.table("users").insert({
            "id": admin_id,
            "email": email,
            "full_name": "System Admin",
            "is_admin": True,
            "referral_code": "ADMIN123"
        }).execute()
        print("Done.")
    else:
        print(f"User {admin_id} already exists in public.users. Forcing is_admin=True")
        supabase.table("users").update({"is_admin": True}).eq("id", admin_id).execute()
else:
    print("Admin user not found in auth.users.")
