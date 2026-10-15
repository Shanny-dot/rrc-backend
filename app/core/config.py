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
    # Staff address for feedback and broker-request emails. Empty = no staff emails.
    ADMIN_EMAIL: str = ""
    FRONTEND_URL: HttpUrl
    # Comma-separated audiences accepted for Sign in with Apple tokens
    # (the iOS bundle ID, plus a Services ID if web sign-in is ever added).
    APPLE_CLIENT_IDS: str = "com.rrc.referralapp"
    # Google sign-in: comma-separated OAuth client IDs whose ID tokens are accepted
    # (the Web client ID the app passes as serverClientId). Empty = Google sign-in off.
    GOOGLE_CLIENT_IDS: str = ""
    # Facebook sign-in. Empty = Facebook sign-in off.
    FACEBOOK_APP_ID: str = ""
    FACEBOOK_APP_SECRET: str = ""
    # Guni SMS App Token used to send mobile OTPs. Empty = SMS off.
    GUNI_SMS_API_KEY: str = ""
    GUNI_SMS_SENDER: str = "Reliiance"
    # Shared secret the daily GitHub Actions job sends in X-Job-Key. Empty = daily job off.
    JOB_SECRET: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
