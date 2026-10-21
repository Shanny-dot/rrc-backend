from fastapi import APIRouter, HTTPException, Depends, Body
from app.core.supabase_client import supabase_admin
from app.core.auth_middleware import get_current_admin
import datetime
import json

router = APIRouter()

DEFAULTS = {
    "hero_title": "Total Points",
    "tier_gold_label": "Gold Tier",
    "tier_platinum_threshold": "1000 to Platinum",
    "quick_action_refer": "Refer Friend",
    "quick_action_redeem": "Redeem",
    "quick_action_events": "Events",
    "announcement_banner": "",
    "announcement_active": "false",
    # Help & contact page and the "Contact us" card (edited on the admin Help & Contact page)
    "contact_card_title": "Contact us",
    "book_time_message": "Choose a day and time that suits you. A team member will be in touch soon.",
    "tiers_intro": "",
    "welcome_points": "100",
    "launch_code": "LAUNCH",
    "launch_bonus_points": "100",
    "launch_date": "2026-10-25",
    "contact_name": "Your Reliiance broker",
    "contact_phone": "",
    "contact_email": "",
    "contact_booking_url": "",
    "contact_hours": "",
    "terms_url": "https://rrc-admin.vercel.app/terms-of-service",
    "privacy_url": "https://rrc-admin.vercel.app/privacy-policy",
    "help_faq": json.dumps([
        {"q": "How do I earn points?",
         "a": "You earn points when a friend you refer joins Reliiance Rewards, when you attend Reliiance events, and through occasional bonuses."},
        {"q": "When do I get points for a referral?",
         "a": "Your referral bonus is added once our team confirms your friend's referral. You can follow each referral's progress (Invited, Pending, Signed up, Points added) on the Referrals tab."},
        {"q": "How do I redeem a reward?",
         "a": "Open the Rewards tab, choose a reward you have enough points for and tap Redeem. Our team reviews the request and you'll get an update when it's approved and sent."},
        {"q": "Why haven't my points shown up yet?",
         "a": "Points for referrals are added after the loan settles, and event points after you check in at the event. If something looks wrong, tap Contact us below."},
        {"q": "How do I change my details?",
         "a": "Tap your initial on the Home screen to open your profile, update your details and tap Save details."},
    ]),
}

DEFAULT_LABELS = {
    "hero_title": "Home Hero Title",
    "tier_gold_label": "Gold Tier Label",
    "tier_platinum_threshold": "Points to Platinum Text",
    "quick_action_refer": "Quick Action: Refer Label",
    "quick_action_redeem": "Quick Action: Redeem Label",
    "quick_action_events": "Quick Action: Events Label",
    "announcement_banner": "Announcement Banner Text",
    "announcement_active": "Show Announcement Banner",
    "contact_card_title": "Contact card title on Home",
    "book_time_message": "Message at the top of the in-app Book a time form",
    "tiers_intro": "Intro text on the member tiers page",
    "welcome_points": "Welcome points for new members",
    "contact_name": "Contact: name shown on the broker card",
    "contact_phone": "Contact: phone number",
    "contact_email": "Contact: email address",
    "contact_booking_url": "Contact: book-a-time link",
    "contact_hours": "Contact: opening hours",
    "terms_url": "Program terms link",
    "privacy_url": "Privacy policy link",
    "help_faq": "Help page questions and answers (JSON)",
}

@router.get("")
def get_all_content():
    """Public endpoint — returns all app content key-value pairs."""
    try:
        resp = supabase_admin.table("app_content").select("key,value").execute()
        if resp.data:
            result = dict(DEFAULTS)
            result.update({row["key"]: row["value"] for row in resp.data})
            return result
    except Exception as e:
        print(f"Content fetch warning: {e}")
    return DEFAULTS

@router.get("/all")
def get_all_content_admin(admin: dict = Depends(get_current_admin)):
    """Admin endpoint — returns full content rows with labels."""
    try:
        resp = supabase_admin.table("app_content").select("*").order("key").execute()
        if resp.data:
            db_keys = {row["key"] for row in resp.data}
            rows = list(resp.data)
            # Add any defaults not yet in DB
            for k, v in DEFAULTS.items():
                if k not in db_keys:
                    rows.append({"key": k, "value": v, "label": DEFAULT_LABELS.get(k, k), "updated_at": None})
            return rows
    except Exception as e:
        print(f"Content admin fetch warning: {e}")
    return [{"key": k, "value": v, "label": DEFAULT_LABELS.get(k, k), "updated_at": None} for k, v in DEFAULTS.items()]

@router.put("/{key}")
def update_content(key: str, value: str = Body(..., embed=True), admin: dict = Depends(get_current_admin)):
    """Admin endpoint — upsert a content block by key."""
    if key == "help_faq":
        try:
            items = json.loads(value)
            assert isinstance(items, list) and all(isinstance(i, dict) and i.get("q") and i.get("a") for i in items)
        except Exception:
            raise HTTPException(status_code=400, detail="Each help item needs a question and an answer.")
    try:
        row = {"key": key, "value": value, "updated_at": datetime.datetime.utcnow().isoformat()}
        # Keep labels set by migrations (e.g. referral_points) for keys this file doesn't know
        if key in DEFAULT_LABELS:
            row["label"] = DEFAULT_LABELS[key]
        resp = supabase_admin.table("app_content").upsert(row).execute()
        return {"key": key, "value": value, "message": "Content updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update content: {str(e)}")
