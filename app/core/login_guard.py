"""Per-account protection against password guessing and reset-email flooding.

Per-address limits on top of the per-IP limits (slowapi), so an attacker spreading attempts
over many IP addresses still can't keep guessing one member's password. Kept in memory: the
server runs as a single instance, and a restart only clears the counters early.
"""
import threading
import time

from fastapi import HTTPException

FAILS_BEFORE_LOCK = 5          # wrong passwords allowed per address ...
FAIL_WINDOW = 15 * 60          # ... within this many seconds
LOCK_SECONDS = 15 * 60         # first lock; each further lock doubles, up to MAX_LOCK
MAX_LOCK = 4 * 60 * 60
RESETS_PER_HOUR = 3            # password-reset emails per address per hour

_lock = threading.Lock()
_fails: dict[str, list[float]] = {}
_locked_until: dict[str, float] = {}
_lock_count: dict[str, int] = {}
_resets: dict[str, list[float]] = {}


def _key(email: str) -> str:
    return (email or "").strip().lower()


def check_login_allowed(email: str) -> None:
    key, now = _key(email), time.time()
    with _lock:
        until = _locked_until.get(key, 0)
    if until > now:
        minutes = max(1, round((until - now) / 60))
        raise HTTPException(status_code=429, detail=(
            f"Too many unsuccessful sign-in attempts. For your security, please wait {minutes} minute"
            f"{'s' if minutes != 1 else ''} and try again, or use Forgot password."))


def record_login_failure(email: str) -> int:
    """Returns the lock number when this failure locks the account (1, 2, ...), else 0."""
    key, now = _key(email), time.time()
    locked = 0
    with _lock:
        recent = [t for t in _fails.get(key, []) if now - t < FAIL_WINDOW] + [now]
        if len(recent) >= FAILS_BEFORE_LOCK:
            locked = _lock_count.get(key, 0) + 1
            _lock_count[key] = locked
            _locked_until[key] = now + min(LOCK_SECONDS * 2 ** (locked - 1), MAX_LOCK)
            recent = []
            print(f"Security: sign-in locked for an account after {FAILS_BEFORE_LOCK} failed attempts (lock #{locked})")
        _fails[key] = recent
    return locked


def lock_minutes(lock_number: int) -> int:
    return min(LOCK_SECONDS * 2 ** (lock_number - 1), MAX_LOCK) // 60


def record_login_success(email: str) -> None:
    key = _key(email)
    with _lock:
        _fails.pop(key, None)
        _locked_until.pop(key, None)
        _lock_count.pop(key, None)


def reset_email_allowed(email: str) -> bool:
    """False once an address has had RESETS_PER_HOUR reset emails in the last hour."""
    key, now = _key(email), time.time()
    with _lock:
        recent = [t for t in _resets.get(key, []) if now - t < 3600]
        if len(recent) >= RESETS_PER_HOUR:
            _resets[key] = recent
            return False
        _resets[key] = recent + [now]
        return True


def reset_all() -> None:
    """Tests only."""
    with _lock:
        _fails.clear(); _locked_until.clear(); _lock_count.clear(); _resets.clear()
