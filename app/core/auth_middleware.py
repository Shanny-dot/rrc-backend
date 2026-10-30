from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import time
from app.core import permissions
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


def _member_row(user_id: str):
    try:
        resp = supabase_admin.table("users").select("*").eq("id", user_id).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        print("Member lookup failed:", e)
        return None


def _is_deleted(user_id: str, row: dict = None) -> bool:
    """True when the account is closed (soft delete)."""
    if row and row.get("deleted_at"):
        return True
    # Legacy: deletions recorded only in deleted_users.json before the DB column was used
    from app.api.routes.admin import load_deleted_users_map
    return user_id in load_deleted_users_map()


def _signed_out(row: dict, issued_at) -> bool:
    """True when the token was issued before the member (or staff) signed out of every device."""
    cutoff = (row or {}).get("signed_out_at")
    if not cutoff or not issued_at:
        return False
    try:
        import datetime
        cut = datetime.datetime.fromisoformat(str(cutoff).replace("Z", "+00:00"))
        return int(issued_at) < int(cut.timestamp())
    except Exception:
        return False


def _claims(token: str) -> dict:
    """The token's claims. Read only after the token has been accepted, so the signature is already checked."""
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return {}


def _authenticate(token: str) -> dict:
    # 1. Supabase-issued session tokens
    try:
        user_response = supabase_anon.auth.get_user(token)
        if user_response and user_response.user:
            claims = _claims(token)
            # aal2 = the session was confirmed with a two-step (authenticator app) code
            return {"sub": user_response.user.id, "email": user_response.user.email, "role": "authenticated",
                    "user_metadata": getattr(user_response.user, "user_metadata", None) or {},
                    "aal": claims.get("aal") or "", "iat": claims.get("iat")}
    except Exception:
        pass

    # 2. Backend-issued tokens (the app's long-lived sign-in), signed with JWT_SECRET from the environment
    if APP_TOKENS_ENABLED:
        try:
            payload = jwt.decode(
                token, _secret, algorithms=["HS256"], issuer=APP_TOKEN_ISSUER,
                options={"require": ["exp", "sub", "iss"]},
            )
            return {"sub": payload["sub"], "email": payload.get("email"), "role": "authenticated",
                    "iat": payload.get("iat")}
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user = _authenticate(credentials.credentials)
    row = _member_row(user["sub"])
    if _is_deleted(user["sub"], row):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account has been deleted.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if _signed_out(row, user.get("iat")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="You've been signed out. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user["profile"] = row or {}
    return user


def _route_template(request: Request) -> str:
    """The full route path with its parameters as placeholders, e.g. /api/v1/admin/users/{id}/points.
    Rebuilt from the request (some FastAPI versions keep only the router-relative path on the route)."""
    from urllib.parse import unquote
    segments = request.url.path.rstrip("/").split("/")
    for name, value in (request.path_params or {}).items():
        for i in range(len(segments) - 1, -1, -1):
            if unquote(segments[i]) == str(value):
                segments[i] = "{" + name + "}"
                break
    return "/".join(segments)


def get_current_admin(request: Request, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    row = current_user.get("profile") or {}
    if not row.get("is_admin"):
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

    # What this staff member's access level allows (app/core/permissions.py)
    role = permissions.role_of(row)
    rule = permissions.ROUTES.get((request.method, _route_template(request)))
    if not rule or not permissions.can(role, rule[0]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your access level doesn't allow this. Please ask the account owner.",
        )

    admin = {**current_user, "admin_role": role, "email": current_user.get("email") or row.get("email")}
    # Picked up by the activity-log middleware once the response is ready
    request.state.audit_actor = admin
    request.state.audit_action = rule[1]
    return admin
