from app.core.supabase_client import supabase_admin
resp = supabase_admin.table("users").select("email, is_admin").execute()
print(resp.data)
