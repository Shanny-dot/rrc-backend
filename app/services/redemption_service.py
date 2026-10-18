"""Tells the member when their reward request changes status: an email (wording edited on
the admin website) and a phone alert."""
from app.core.supabase_client import supabase_admin
from app.services import notify_service
from app.services.email_service import EmailService
from app.services.program_service import redemption_templates


def reference(redemption_id) -> str:
    return str(redemption_id)[:8].upper()


def notify_status(redemption_id: str, status: str, note: str = None) -> None:
    rows = supabase_admin.table("redemptions").select("*, users(full_name, email), rewards(title)") \
        .eq("id", redemption_id).execute().data or []
    if not rows:
        return
    red = rows[0]
    member = red.get("users") or {}
    reward = (red.get("rewards") or {}).get("title") or "your reward"
    template = redemption_templates().get(status)
    if not template:
        return
    bal = supabase_admin.table("users").select("total_points").eq("id", red["user_id"]).execute().data or [{}]
    values = {
        "reward": reward,
        "points": f"{red.get('points_used') or 0:,}",
        "balance": f"{bal[0].get('total_points') or 0:,} points",
        "reference": reference(redemption_id),
    }
    if member.get("email"):
        EmailService.send_redemption_status(member["email"], member.get("full_name"), template, values, note)
    if status != "pending":  # the member is looking at the app when they redeem
        body = {
            "in_progress": f"We're working on your {reward}.",
            "approved": f"Your {reward} has been approved.",
            "sent": f"{reward} has been sent. Check your email.",
            "rejected": f"Your {values['points']} points have been refunded.",
        }.get(status, "")
        title = {"sent": "Your reward is on its way", "rejected": f"{reward} couldn't be processed"}.get(
            status, f"Reward {template['label'].lower()}")
        notify_service.push(red["user_id"], "reward", title, body, {"redemption_id": redemption_id})
