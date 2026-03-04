import asyncio
from app.core.supabase_client import supabase_admin

def diagnosis():
    try:
        # Check public.users
        users_resp = supabase_admin.table("users").select("id, email, full_name").execute()
        print("Users in DB mapping:", users_resp.data)
        
        # Check auth.users
        auth_users = supabase_admin.auth.admin.list_users()
        print("\nAuth Users:")
        for u in auth_users:
            if hasattr(u, 'users'): # The response is actually a ListUsersResponse object
                for user in u.users:
                    print(user.id, user.email)
            else:
                pass
                
    except Exception as e:
        print(f"Error: {e}")

diagnosis()
