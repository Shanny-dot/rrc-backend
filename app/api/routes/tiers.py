from fastapi import APIRouter
from app.services.program_service import list_tiers, get_setting

router = APIRouter()

@router.get("")
@router.get("/")
def get_tiers():
    """Public: tier names, thresholds and benefits, lowest first."""
    return {
        "basis": get_setting("tier_basis").strip().lower() or "lifetime",
        "tiers": [
            {"name": t["name"], "min_points": t["min_points"], "benefits": t["benefits_list"]}
            for t in list_tiers()
        ],
    }
