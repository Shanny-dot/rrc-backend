"""Verification of Sign in with Apple identity tokens.

Apple signs identity tokens with RS256 keys published at APPLE_JWKS_URL.
A token is only trusted after its signature, issuer, audience and expiry
have been checked, and (when the app sent one) its nonce.
"""
import hashlib

import jwt
from jwt import PyJWKClient

from app.core.config import settings

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"

# Keys are cached in memory and refreshed when Apple rotates them.
_jwk_client = PyJWKClient(APPLE_JWKS_URL, cache_keys=True, lifespan=86400)


def _allowed_audiences() -> list:
    return [a.strip() for a in settings.APPLE_CLIENT_IDS.split(",") if a.strip()]


def verify_apple_identity_token(id_token: str, raw_nonce: str = None) -> dict:
    """Return the verified claims of an Apple identity token, or raise ValueError."""
    try:
        signing_key = _jwk_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=_allowed_audiences(),
            issuer=APPLE_ISSUER,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except Exception as e:
        raise ValueError(f"Invalid Apple identity token: {e}")

    # When the app supplies the raw nonce, the token must carry its SHA-256 hash.
    if raw_nonce:
        expected = hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest()
        if claims.get("nonce") not in (expected, raw_nonce):
            raise ValueError("Apple identity token nonce mismatch")

    return claims
