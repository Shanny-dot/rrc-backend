"""Server-side verification of Google and Facebook sign-ins.

Tokens from the app are only trusted after they are verified with Google or Facebook,
so no one can sign in as someone else by sending a made-up token.
"""
import json
import urllib.parse
import urllib.request

import jwt
from jwt import PyJWKClient

from app.core.config import settings

GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_google_jwks = PyJWKClient(GOOGLE_JWKS_URL, cache_keys=True, lifespan=21600)

GRAPH = "https://graph.facebook.com/v19.0"


def _csv(value: str) -> list:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def google_enabled() -> bool:
    return bool(_csv(settings.GOOGLE_CLIENT_IDS))


def facebook_enabled() -> bool:
    return bool(settings.FACEBOOK_APP_ID and settings.FACEBOOK_APP_SECRET)


def verify_google_id_token(id_token: str) -> dict:
    """Return {email, name} for a valid Google ID token, or raise ValueError."""
    if not id_token:
        raise ValueError("Google didn't return a sign-in token")
    try:
        key = _google_jwks.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token, key.key, algorithms=["RS256"],
            audience=_csv(settings.GOOGLE_CLIENT_IDS),
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except Exception as e:
        raise ValueError(f"Invalid Google token: {e}")
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise ValueError("Invalid Google token issuer")
    if not claims.get("email") or not claims.get("email_verified"):
        raise ValueError("Your Google account has no verified email address")
    return {"email": claims["email"].strip().lower(), "name": claims.get("name") or ""}


def _graph_get(path: str, params: dict) -> dict:
    url = f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def verify_facebook_access_token(access_token: str) -> dict:
    """Return {email, name} for a valid Facebook user access token issued to our app, or raise ValueError."""
    if not access_token:
        raise ValueError("Facebook didn't return a sign-in token")
    app_token = f"{settings.FACEBOOK_APP_ID}|{settings.FACEBOOK_APP_SECRET}"
    try:
        info = _graph_get("debug_token", {"input_token": access_token, "access_token": app_token}).get("data", {})
    except Exception as e:
        raise ValueError(f"Could not verify Facebook token: {e}")
    if not info.get("is_valid") or str(info.get("app_id")) != str(settings.FACEBOOK_APP_ID):
        raise ValueError("Invalid Facebook token")
    try:
        me = _graph_get("me", {"fields": "id,name,email", "access_token": access_token})
    except Exception as e:
        raise ValueError(f"Could not read Facebook profile: {e}")
    if str(me.get("id")) != str(info.get("user_id")):
        raise ValueError("Facebook token and profile don't match")
    if not me.get("email"):
        raise ValueError("Facebook didn't share an email address. Please sign up with email instead.")
    return {"email": me["email"].strip().lower(), "name": me.get("name") or ""}
