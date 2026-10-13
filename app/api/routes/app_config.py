from fastapi import APIRouter
from app.services.program_service import get_setting

router = APIRouter()


@router.get("/version")
def version_config():
    """Public. The app compares its own version with these on launch.
    Below min_version: blocking "Update required" screen. Below latest_version: optional prompt.
    All values are edited in the app_content table, no deploy needed."""
    return {
        "min_version": get_setting("min_app_version") or "0.0.0",
        "latest_version": get_setting("latest_app_version") or "0.0.0",
        "ios_store_url": get_setting("ios_store_url"),
        "android_store_url": get_setting("android_store_url"),
        "message": get_setting("update_message"),
    }
