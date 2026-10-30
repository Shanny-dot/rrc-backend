"""Daily caps on emails a member can make us send to other people (event guest invitations,
referral invitations), so the app can't be used to send large numbers of emails from our address.

Kept in memory like login_guard: the server runs as a single instance, and a restart only
resets the counts early.
"""
import threading
import time

from fastapi import HTTPException

DAY = 24 * 60 * 60
LIMITS = {"guest_invites": 30, "referral_invites": 30}

_lock = threading.Lock()
_sent: dict = {}


def use(member_id: str, kind: str, count: int = 1) -> None:
    """Counts `count` more sends for the member today, or refuses (429) past the daily cap."""
    now = time.time()
    key = (member_id, kind)
    with _lock:
        recent = [t for t in _sent.get(key, []) if now - t < DAY]
        if len(recent) + count > LIMITS[kind]:
            _sent[key] = recent
            raise HTTPException(status_code=429, detail="You've sent a lot of invitations today. Please try again tomorrow.")
        _sent[key] = recent + [now] * count


def reset_all() -> None:
    """Tests only."""
    with _lock:
        _sent.clear()
