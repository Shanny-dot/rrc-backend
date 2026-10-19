"""Emails that follow a change to a member's points: "points added" and "tier upgrade".
Called after points are added, wherever that happens (staff, event check-in, referral,
bonus). Never raises: an email problem must not undo the points."""
from app.core.supabase_client import supabase_admin
from app.services import notify_service
from app.services.email_service import EmailService
from app.services.program_service import get_setting, lifetime_points, list_tiers

# Points that get their own "points added" email. Welcome points are in the welcome email,
# and refunds in the "reward declined" email.
EMAILED_TYPES = {"referral", "event_attend", "event_guest", "bonus", "admin_adjustment"}
_NON_EARNING = {"redemption", "redemption_refund", "points_expired"}


def _tier_for(points: int, tiers: list):
    current = None
    for t in tiers:
        if points >= (t.get("min_points") or 0):
            current = t
    return current


def after_points_added(user_id: str, points: int, type: str, reason: str) -> None:
    if points <= 0:
        return
    try:
        rows = supabase_admin.table("users").select("full_name, email, total_points, deleted_at").eq("id", user_id).execute().data
        if not rows or rows[0].get("deleted_at"):
            return
        member = rows[0]
        balance = member.get("total_points") or 0
        if type in EMAILED_TYPES and member.get("email"):
            EmailService.send_points_added(member["email"], member.get("full_name"), points, reason, balance)

        # Tier upgrade: did these points carry the member into a higher tier?
        if type in _NON_EARNING:
            return
        tiers = list_tiers()
        if len(tiers) < 2:
            return
        basis = (get_setting("tier_basis") or "lifetime").strip().lower()
        after = balance if basis == "balance" else lifetime_points(user_id, balance)
        before_tier, after_tier = _tier_for(after - points, tiers), _tier_for(after, tiers)
        if after_tier and after_tier is not before_tier and (before_tier is None or
                                                            (after_tier.get("min_points") or 0) > (before_tier.get("min_points") or 0)):
            if notify_service.log_once(user_id, "tier_upgrade", str(after_tier.get("name")),
                                       f"You've reached {after_tier['name']} tier", "See your new benefits in Help & contact."):
                notify_service.push(user_id, "points", f"You've reached {after_tier['name']} tier!",
                                    "See your new benefits in Help & contact.")
                if member.get("email"):
                    EmailService.send_tier_upgrade(member["email"], member.get("full_name"), after_tier["name"],
                                                   after_tier.get("benefits_list") or [])
    except Exception as e:
        print(f"Points alert warning: {e}")
