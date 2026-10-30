from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import time
from app.core.config import settings
from app.core.supabase_client import supabase_admin, supabase_anon

security = HTTPBearer()

# The previous code signed tokens with this value hard-coded in the repository,
# so it must never be accepted again, even if someone copies it into JWT_SECRET.
_LEAKED_SECRETS = {"rrc_secret_jwt_key_2026"}
_MIN_SECRET_LENGTH = 32

_secret = (settings.JWT_SECRET or "").strip()
APP_TOKENS_ENABLED = len(_secret) >= _MIN_SECRET_LENGTH and _secret not in _LEAKED_SECRETS
if not APP_TOKENS_ENABLED:
    print(
        "WARNING: JWT_SECRET is missing, too short (<32 chars) or a leaked value. "
        "Backend-issued tokens (Apple Sign-In fallback) are disabled until it is set."
    )

APP_TOKEN_ISSUER = "rrc-backend"
# Members stay signed in for 6 months; the app renews the token every time it opens.
APP_TOKEN_TTL_SECONDS = 86400 * 180


def issue_app_token(user_id: str, email: str = None) -> str:
    """Issue a long-lived backend-signed sign-in token for the app."""
    if not APP_TOKENS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sign-in is temporarily unavailable. Please try again later.",
        )
    now = int(time.time())
    return jwt.encode(
        {"sub": user_id, "email": email, "iss": APP_TOKEN_ISSUER, "iat": now, "exp": now + APP_TOKEN_TTL_SECONDS},
        _secret,
        algorithm="HS256",
    )


def _is_deleted(user_id: str) -> bool:
    """True when staff have deleted this member (soft delete) or the profile row is gone."""
    try:
        resp = supabase_admin.table("users").select("*").eq("id", user_id).execute()
        row = resp.data[0] if resp.data else None
    except Exception as e:
        print("Deleted-user check failed:", e)
        row = None
    if row and row.get("deleted_at"):
        return True
    # Legacy: deletions recorded only in deleted_users.json before the DB column was used
    from app.api.routes.admin import load_deleted_users_map
    return user_id in load_deleted_users_map()


def _session_aal(token: str) -> str:
    """'aal2' when the Supabase session was confirmed with a two-step (authenticator app) code.
    Read only after Supabase has accepted the token, so the signature is already checked."""
    try:
        return jwt.decode(token, options={"verify_signature": False}).get("aal") or ""
    except Exception:
        return ""


def _authenticate(token: str) -> dict:
    # 1. Supabase-issued session tokens
    try:
        user_response = supabase_anon.auth.get_user(token)
        if user_response and user_response.user:
            return {"sub": user_response.user.id, "email": user_response.user.email, "role": "authenticated",
                    "user_metadata": getattr(user_response.user, "user_metadata", None) or {},
                    "aal": _session_aal(token)}
    except Exception:
        pass

    # 2. Backend-issued tokens (Apple Sign-In fallback), signed with JWT_SECRET from the environment
    if APP_TOKENS_ENABLED:
        try:
            payload = jwt.decode(
                token, _secret, algorithms=["HS256"], issuer=APP_TOKEN_ISSUER,
                options={"require": ["exp", "sub", "iss"]},
            )
            return {"sub": payload["sub"], "email": payload.get("email"), "role": "authenticated"}
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user = _authenticate(credentials.credentials)
    if _is_deleted(user["sub"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account has been deleted.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_admin(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    resp = supabase_admin.table("users").select("is_admin").eq("id", user_id).execute()
    if not resp.data or not resp.data[0].get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions. Admin access required.",
        )

    # Staff must sign in to the admin site with their password AND an authenticator-app code.
    # App tokens (member sign-in) never carry that, so they can't be used for admin access.
    if current_user.get("aal") != "aal2":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="two_step_required: please sign in again and enter the code from your authenticator app.",
        )

    return current_user
