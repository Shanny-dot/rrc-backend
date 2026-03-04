import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(url, key)

email = "admin@rrc.com"
password = "AdminPassword123!"

print(f"Creating admin user: {email}...")

try:
    # Use admin api to auto-confirm the email
    res = supabase.auth.admin.create_user({
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {"full_name": "System Admin"}
    })
    
    if res.user:
        print(f"Auth user created successfully! ID: {res.user.id}")
        # The database trigger will have created the public.users row. We just need to update is_admin.
        update_res = supabase.table("users").update({"is_admin": True}).eq("id", res.user.id).execute()
        print("Granted Admin Access in public.users table.")
        print(f"\n--- SUCCESS ---\nEMAIL: {email}\nPASSWORD: {password}\n---------------")
    else:
        print("Could not retrieve user from response.")
except Exception as e:
    print(f"Error: {str(e)}")
