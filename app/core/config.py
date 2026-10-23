from pydantic_settings import BaseSettings
from pydantic import HttpUrl

class Settings(BaseSettings):
    DATABASE_URL: str
    SUPABASE_URL: HttpUrl
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_KEY: str
    RESEND_API_KEY: str
    # ZeptoMail (Zoho) — used instead of Resend when set. The key works only on its own
    # region's host; this account is on the Australian data centre.
    ZEPTOMAIL_API_KEY: str = ""
    ZEPTOMAIL_API_URL: str = "https://api.zeptomail.com.au/v1.1/email"
    FROM_NAME: str = "Reliiance Rewards"
    # Google Workspace sending (preferred over ZeptoMail when set). SMTP_PASSWORD is an
    # app password from the Google account (Security → App passwords), not its login password.
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = ""
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
    # "Reliiance" isn't a registered sender on the Guni account; the shared number is.
    GUNI_SMS_SENDER: str = "#SharedNum#"
    # Shared secret the daily GitHub Actions job sends in X-Job-Key. Empty = daily job off.
    JOB_SECRET: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
