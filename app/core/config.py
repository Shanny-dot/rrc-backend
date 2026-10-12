from pydantic_settings import BaseSettings
from pydantic import HttpUrl

class Settings(BaseSettings):
    DATABASE_URL: str
    SUPABASE_URL: HttpUrl
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_KEY: str
    RESEND_API_KEY: str
    FROM_EMAIL: str
    FIREBASE_CREDENTIALS_JSON: str
    JWT_SECRET: str
    ADMIN_EMAIL: str
    FRONTEND_URL: HttpUrl
    # Comma-separated audiences accepted for Sign in with Apple tokens
    # (the iOS bundle ID, plus a Services ID if web sign-in is ever added).
    APPLE_CLIENT_IDS: str = "com.rrc.referralapp"

    class Config:
        env_file = ".env"

settings = Settings()
