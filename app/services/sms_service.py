import hashlib
import hmac
import threading
import time
import httpx
from app.core.config import settings
from app.core.auth_middleware import APP_TOKENS_ENABLED

GUNI_GATEWAY_URL = "https://api.gunisms.com.au/api/v1/gateway"
_SMS_ENABLED = bool(settings.GUNI_SMS_API_KEY)

# OTPs are derived (HMAC of phone + time window) rather than stored, so no DB table is needed.
# A code stays valid for the window it was issued in plus the following one (5–10 minutes).
# Codes are keyed on JWT_SECRET, so they are refused while that secret is missing or the leaked value.
OTP_WINDOW_SECONDS = 300
OTP_DIGITS = 6


def format_mobile(mobile: str) -> str:
    """Normalise a mobile number to E.164 (AU/IN defaults). Must be identical for send and verify."""
    formatted = mobile.strip().replace(" ", "")
    if formatted.startswith('+'):
        return formatted
    if len(formatted) == 10 and formatted.startswith('0'):
        return f"+61{formatted[1:]}"   # Australian mobile with leading zero, e.g. 0412345678
    if len(formatted) == 10:
        return f"+91{formatted}"       # Indian mobile
    if len(formatted) == 9:
        return f"+61{formatted}"       # Australian mobile without leading zero
    return f"+{formatted}"


def _otp_for_window(mobile: str, window: int) -> str:
    if not APP_TOKENS_ENABLED:
        raise Exception("Mobile verification unavailable: JWT_SECRET is missing, too short or a leaked value")
    digest = hmac.new(settings.JWT_SECRET.strip().encode(), f"{mobile}:{window}".encode(), hashlib.sha256).digest()
    return str(int.from_bytes(digest[:8], "big") % (10 ** OTP_DIGITS)).zfill(OTP_DIGITS)


def issue_code(subject: str) -> str:
    """The current 6-digit code for a subject: a formatted mobile, or "email:<address>"."""
    return _otp_for_window(subject, int(time.time()) // OTP_WINDOW_SECONDS)


# Guessing: after MAX_CODE_FAILS wrong codes for one mobile / email within CODE_FAIL_WINDOW,
# every code for it is refused until the window has passed (even from other internet
# addresses), so a 6-digit code can't be found by trying many.
MAX_CODE_FAILS = 5
CODE_FAIL_WINDOW = 15 * 60
_code_lock = threading.Lock()
_code_fails: dict = {}


def code_matches(subject: str, code: str, windows: int = 2) -> bool:
    """True if code was issued for subject in the current window or the (windows - 1) before it."""
    code = (code or "").strip()
    now = time.time()
    with _code_lock:
        recent = [t for t in _code_fails.get(subject, []) if now - t < CODE_FAIL_WINDOW]
        _code_fails[subject] = recent
        if len(recent) >= MAX_CODE_FAILS:
            print(f"Security: verification codes blocked for a mobile/email after {MAX_CODE_FAILS} wrong codes")
            return False
    current = int(now) // OTP_WINDOW_SECONDS
    ok = any(hmac.compare_digest(_otp_for_window(subject, current - i), code) for i in range(windows))
    with _code_lock:
        if ok:
            _code_fails.pop(subject, None)
        else:
            _code_fails.setdefault(subject, []).append(now)
    return ok


def reset_code_attempts() -> None:
    """Tests only."""
    with _code_lock:
        _code_fails.clear()


class SmsService:

    @staticmethod
    def send_sms(mobile: str, message: str):
        if not _SMS_ENABLED:
            raise Exception("SMS not configured: GUNI_SMS_API_KEY is missing")
        response = httpx.post(
            GUNI_GATEWAY_URL,
            headers={
                "Authorization": f"Bearer {settings.GUNI_SMS_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "sender": settings.GUNI_SMS_SENDER,
                "message": message,
                "contacts": [mobile.lstrip('+')],
            },
            timeout=15,
        )
        data = response.json() if response.content else {}
        if response.status_code >= 400 or not data.get("status"):
            raise Exception(f"Guni SMS failed ({response.status_code}): {data.get('message') or response.text}")
        return data

    @staticmethod
    def send_otp(mobile: str):
        mobile = format_mobile(mobile)
        code = issue_code(mobile)
        return SmsService.send_sms(
            mobile,
            f"Your Reliiance verification code is {code}. It expires in 5 minutes. Do not share this code.",
        )

    @staticmethod
    def verify_otp(mobile: str, code: str) -> bool:
        return code_matches(format_mobile(mobile), code)
