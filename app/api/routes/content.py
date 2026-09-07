from fastapi import APIRouter, HTTPException, Depends, Body
from app.core.supabase_client import supabase_admin
from app.core.auth_middleware import get_current_admin
import datetime

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
    try:
        resp = supabase_admin.table("app_content").upsert({
            "key": key,
            "value": value,
            "label": DEFAULT_LABELS.get(key, key),
            "updated_at": datetime.datetime.utcnow().isoformat()
        }).execute()
        return {"key": key, "value": value, "message": "Content updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update content: {str(e)}")
