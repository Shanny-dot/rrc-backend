"""Program settings, tiers and member activity helpers shared by several routes."""
import datetime
from app.core.supabase_client import supabase_admin

SETTING_DEFAULTS = {
    "referral_points": "0",
    "tier_basis": "lifetime",
    "invite_link": "",
    "reward_delivery_default": "",
    "min_app_version": "3.0.0",
    "latest_app_version": "3.1.0",
    "ios_store_url": "",
    "android_store_url": "https://play.google.com/store/apps/details?id=com.rrc.app",
    "update_message": "",
    "invite_base_url": "https://rrc-admin.vercel.app/join",
}

# Points that count towards "lifetime earned": everything except redemptions and their refunds.
_NON_EARNING_TYPES = {"redemption", "redemption_refund"}


def get_setting(key: str) -> str:
    try:
        resp = supabase_admin.table("app_content").select("value").eq("key", key).execute()
        if resp.data and resp.data[0].get("value") is not None:
            return str(resp.data[0]["value"])
    except Exception as e:
        print(f"Setting read warning ({key}): {e}")
    return SETTING_DEFAULTS.get(key, "")


def get_int_setting(key: str) -> int:
    try:
        return int(float(get_setting(key) or 0))
    except ValueError:
        return 0


def list_tiers() -> list:
    try:
        resp = supabase_admin.table("tiers").select("*").order("min_points", desc=False).execute()
        tiers = resp.data or []
    except Exception as e:
        print(f"Tiers read warning: {e}")
        tiers = []
    for t in tiers:
        t["benefits_list"] = [b.strip() for b in (t.get("benefits") or "").splitlines() if b.strip()]
    return tiers


def lifetime_points(user_id: str, balance: int) -> int:
    """Points earned over the member's lifetime.

    Staff adjustments made before the transaction log was fixed were never recorded,
    so the result is never allowed to fall below the current balance.
    """
    try:
        resp = supabase_admin.table("transactions").select("type, points").eq("user_id", user_id).execute()
        earned = sum((r.get("points") or 0) for r in (resp.data or []) if r.get("type") not in _NON_EARNING_TYPES)
    except Exception as e:
        print(f"Lifetime points warning: {e}")
        earned = 0
    return max(earned, balance or 0)


def tier_status(user_id: str, balance: int) -> dict:
    """The member's current tier, next tier and progress towards it."""
    tiers = list_tiers()
    basis = get_setting("tier_basis").strip().lower()
    qualifying = balance if basis == "balance" else lifetime_points(user_id, balance)

    if not tiers:
        return {"name": None, "next_name": None, "points_to_next": None, "progress": 0.0,
                "qualifying_points": qualifying, "basis": basis}

    current = tiers[0]
    nxt = None
    for i, t in enumerate(tiers):
        if qualifying >= (t.get("min_points") or 0):
            current = t
            nxt = tiers[i + 1] if i + 1 < len(tiers) else None

    if nxt:
        span = max((nxt["min_points"] or 0) - (current.get("min_points") or 0), 1)
        progress = min(max((qualifying - (current.get("min_points") or 0)) / span, 0.0), 1.0)
        to_next = max((nxt["min_points"] or 0) - qualifying, 0)
    else:
        progress, to_next = 1.0, 0

    return {
        "name": current["name"],
        "next_name": nxt["name"] if nxt else None,
        "points_to_next": to_next if nxt else None,
        "progress": round(progress, 4),
        "qualifying_points": qualifying,
        "basis": basis,
    }


def _parse_ts(value):
    if not value:
        return None
    try:
        ts = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None


def redemption_status_label(status: str) -> str:
    return {"pending": "Pending", "approved": "Approved", "sent": "Sent", "rejected": "Refunded"}.get(status or "", "Pending")


def activity_for_user(user_id: str) -> list:
    """Transactions newest first, each with a member-facing title and status label.

    Redemption rows are linked to their redemption (by reference_id, or for older rows
    by matching points and time) so the app can show Pending / Approved / Sent.
    """
    tx = supabase_admin.table("transactions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute().data or []
    reds = supabase_admin.table("redemptions").select("id, status, points_used, requested_at").eq("user_id", user_id).execute().data or []
    by_id = {r["id"]: r for r in reds}
    unmatched = list(reds)

    out = []
    for t in tx:
        item = dict(t)
        ttype = t.get("type") or ""
        pts = t.get("points") or 0
        status = "Points added" if pts > 0 else ""
        title = t.get("description") or ttype.replace("_", " ").capitalize()

        if ttype == "redemption":
            red = by_id.get(t.get("reference_id"))
            if not red:
                t_at = _parse_ts(t.get("created_at"))
                for r in unmatched:
                    r_at = _parse_ts(r.get("requested_at"))
                    if r.get("points_used") == abs(pts) and t_at and r_at and abs((t_at - r_at).total_seconds()) <= 180:
                        red = r
                        break
            if red:
                if red in unmatched:
                    unmatched.remove(red)
                item["redemption_id"] = red["id"]
                status = redemption_status_label(red.get("status"))
            else:
                status = "Pending"
        elif ttype == "redemption_refund":
            status = "Refunded"
        elif ttype in ("admin_adjustment", "admin_award", "admin_deduct"):
            reason = (t.get("description") or "").strip()
            item["reason"] = reason
            title = "Points added by Reliance team" if pts > 0 else "Points adjusted by Reliance team"
            status = "Points added" if pts > 0 else "Points removed"

        item["title"] = title
        item["status_label"] = status
        out.append(item)
    return out
