from supabase import create_client, Client
from app.core.config import settings

supabase_anon: Client = create_client(str(settings.SUPABASE_URL), settings.SUPABASE_ANON_KEY)
supabase_admin: Client = create_client(str(settings.SUPABASE_URL), settings.SUPABASE_SERVICE_KEY)
