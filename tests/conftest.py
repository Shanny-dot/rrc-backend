import datetime
import os
import sys

import pytest

# Settings the app requires at import time (dummy values; no network is used).
os.environ.update({
    "DATABASE_URL": "postgresql://test",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_ANON_KEY": "aaaa.bbbb.cccc",
    "SUPABASE_SERVICE_KEY": "aaaa.bbbb.dddd",
    "RESEND_API_KEY": "",
    "FROM_EMAIL": "",
    "FIREBASE_CREDENTIALS_JSON": "",
    "JWT_SECRET": "test-secret-0123456789-0123456789-abcdef",
    "ADMIN_EMAIL": "admin@rrc.com",
    "FRONTEND_URL": "https://rrc-admin.vercel.app",
    "JOB_SECRET": "test-job-key",
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.fake_supabase import FakeSupabase  # noqa: E402

# Production schema after migrations 002-005 (checked against rrc-production on 2026-10-13).
COLUMNS = {
    "users": ["id", "full_name", "email", "mobile", "dob", "gender", "industry", "street_address", "city", "state",
              "postal_code", "country", "home_ownership", "annual_income", "total_points", "bonus_points_granted",
              "profile_complete", "referral_code", "referred_by", "is_admin", "fcm_token", "created_at", "deleted_at",
              "loan_settled_on", "notification_prefs"],
    "events": ["id", "title", "description", "location", "event_date", "image_url", "points_for_attending",
               "points_for_referring", "capacity", "is_active", "created_at", "category", "thank_you_sent_at"],
    "rewards": ["id", "title", "description", "category", "points_required", "image_url", "stock", "is_active",
                "created_at", "what_you_get", "delivery_info", "expiry_info", "terms", "dollar_value"],
    "redemptions": ["id", "user_id", "reward_id", "status", "points_used", "admin_note", "requested_at",
                    "actioned_at", "sent_at"],
    "referrals": ["id", "referrer_id", "referred_name", "referred_mobile", "referred_email", "referred_user_id",
                  "status", "points_earned", "created_at", "channel", "stage_updated_at", "admin_note",
                  "consent_given", "notes"],
    "event_rsvps": ["id", "event_id", "user_id", "qr_token", "attended", "points_awarded", "rsvp_at", "attended_at",
                    "cancelled", "cancelled_at"],
    "event_guests": ["id", "rsvp_id", "inviter_user_id", "guest_name", "guest_mobile", "guest_email", "attended",
                     "points_awarded_to_inviter"],
    "transactions": ["id", "user_id", "type", "points", "reference_id", "description", "created_at"],
    "app_content": ["key", "value", "label", "updated_at"],
    "wishlist": ["id", "user_id", "reward_id", "created_at"],
    "tiers": ["id", "name", "min_points", "benefits", "sort_order"],
    # 006_feedback_invites.sql
    "feedback": ["id", "user_id", "category", "message", "app_version", "platform", "status", "created_at"],
    "invite_clicks": ["id", "referral_code", "ip_hash", "created_at"],
    # 007_alerts_bonuses_loans.sql
    "notification_log": ["id", "user_id", "kind", "ref", "title", "body", "created_at"],
    "loan_reviews": ["id", "user_id", "status", "note", "staff_note", "created_at", "updated_at"],
}
DEFAULTS = {
    "users": {"total_points": 0, "bonus_points_granted": False, "profile_complete": False, "is_admin": False,
              "deleted_at": None, "fcm_token": None},
    "referrals": {"points_earned": 0, "consent_given": False, "status": "pending"},
    "event_rsvps": {"attended": False, "points_awarded": False, "cancelled": False},
    "events": {"is_active": True, "points_for_attending": 0, "points_for_referring": 0},
    "rewards": {"is_active": True},
    "feedback": {"status": "new"},
    "loan_reviews": {"status": "new"},
}
CHECKS = {
    "transactions": {"type": {"signup_bonus", "referral", "event_attend", "event_guest", "redemption",
                              "redemption_refund", "admin_adjustment", "bonus", "points_expired"}},
    "redemptions": {"status": {"pending", "approved", "sent", "rejected"}},
    "feedback": {"status": {"new", "read", "resolved"}},
    "loan_reviews": {"status": {"new", "contacted", "closed"}},
    "referrals": {"status": {"pending", "invited", "registered", "contacted", "loan_in_progress", "settled",
                             "rewarded", "closed"}},
}

ADMIN_ID = "00000000-0000-0000-0000-00000000000a"
MEMBER_ID = "00000000-0000-0000-0000-0000000000b1"
FRIEND_ID = "00000000-0000-0000-0000-0000000000c2"


def _iso(days):
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).isoformat()


def seed(db):
    t = db.tables
    t["users"] = [
        {"id": ADMIN_ID, "full_name": "Admin", "email": "admin@rrc.com", "is_admin": True, "total_points": 0,
         "referral_code": "ADMIN001", "deleted_at": None},
        {"id": MEMBER_ID, "full_name": "Manoj Kumar", "email": "manoj@example.com", "is_admin": False,
         "total_points": 2050, "referral_code": "MANOJ123", "deleted_at": None, "fcm_token": None},
        {"id": FRIEND_ID, "full_name": "Old Member", "email": "old@example.com", "is_admin": False,
         "total_points": 100, "referral_code": "OLD00001", "deleted_at": None},
    ]
    t["rewards"] = [
        {"id": "22222222-0000-4000-8000-000000000001", "title": "Tandem Skydive", "category": "Experiences", "points_required": 300, "stock": 15,
         "is_active": True, "created_at": _iso(-10), "description": "Jump!", "what_you_get": "One tandem jump",
         "delivery_info": None, "expiry_info": "12 months", "terms": "T&Cs", "dollar_value": 350},
        {"id": "22222222-0000-4000-8000-000000000002", "title": "Exclusive VIP Property Tour", "category": "Experiences", "points_required": 5000,
         "stock": 2, "is_active": True, "created_at": _iso(-9)},
        {"id": "22222222-0000-4000-8000-000000000003", "title": "Toy World Card", "category": "Shopping", "points_required": 50, "stock": None,
         "is_active": True, "created_at": _iso(-8)},
    ]
    t["events"] = [
        {"id": "11111111-0000-4000-8000-000000000001", "title": "First Home Buyers Breakfast", "category": "Real Estate", "location": "Sydney CBD",
         "event_date": _iso(7), "points_for_attending": 100, "points_for_referring": 50, "is_active": True,
         "created_at": _iso(-3)},
        {"id": "11111111-0000-4000-8000-000000000002", "title": "Market Update", "location": "Chatswood", "event_date": _iso(-20),
         "points_for_attending": 50, "points_for_referring": 0, "is_active": True, "created_at": _iso(-30)},
    ]
    t["redemptions"] = [
        {"id": "33333333-0000-4000-8000-000000000001", "user_id": MEMBER_ID, "reward_id": "22222222-0000-4000-8000-000000000003", "status": "pending", "points_used": 50,
         "requested_at": _iso(-2), "actioned_at": None, "sent_at": None},
    ]
    t["transactions"] = [
        {"id": "55555555-0000-4000-8000-000000000001", "user_id": MEMBER_ID, "type": "signup_bonus", "points": 100, "description": "Welcome Bonus",
         "created_at": _iso(-40)},
        {"id": "55555555-0000-4000-8000-000000000002", "user_id": MEMBER_ID, "type": "admin_adjustment", "points": 2000, "description": "Event bonus",
         "created_at": _iso(-5)},
        {"id": "55555555-0000-4000-8000-000000000003", "user_id": MEMBER_ID, "type": "redemption", "points": -50,
         "description": "Redeemed Toy World Card", "created_at": _iso(-2)},
    ]
    t["referrals"] = [
        {"id": "44444444-0000-4000-8000-000000000001", "referrer_id": MEMBER_ID, "referred_name": "Chaitanya", "referred_mobile": "0412345678",
         "referred_email": "chai@example.com", "status": "pending", "points_earned": 0, "created_at": _iso(-1)},
    ]
    t["tiers"] = [
        {"id": "66666666-0000-4000-8000-000000000001", "name": "Silver", "min_points": 0, "benefits": "Earn points", "sort_order": 1},
        {"id": "66666666-0000-4000-8000-000000000002", "name": "Gold", "min_points": 1000, "benefits": "Everything in Silver\nPriority invites", "sort_order": 2},
        {"id": "66666666-0000-4000-8000-000000000003", "name": "Platinum", "min_points": 5000, "benefits": "Everything in Gold", "sort_order": 3},
    ]
    t["app_content"] = [
        {"key": "referral_points", "value": "500"}, {"key": "tier_basis", "value": "lifetime"},
        {"key": "invite_link", "value": "https://reliance.example/join"},
        {"key": "reward_delivery_default", "value": "Emailed within 5 business days"},
        {"key": "min_app_version", "value": "3.0.0"}, {"key": "latest_app_version", "value": "3.1.0"},
    ]
    t["wishlist"], t["event_rsvps"], t["event_guests"] = [], [], []


@pytest.fixture(scope="module")
def env():
    db = FakeSupabase(COLUMNS, DEFAULTS, CHECKS)
    seed(db)
    import main  # noqa: F401  (imports every route module)
    for mod in list(sys.modules.values()):
        name = getattr(mod, "__name__", "") or ""
        if name.startswith("app.") or name == "main":
            if hasattr(mod, "supabase_admin"):
                mod.supabase_admin = db
            if hasattr(mod, "supabase_anon"):
                mod.supabase_anon = db
    from fastapi.testclient import TestClient
    from app.core.auth_middleware import issue_app_token
    client = TestClient(main.app, raise_server_exceptions=False)
    tok = lambda uid, email: {"Authorization": f"Bearer {issue_app_token(uid, email)}"}  # noqa: E731
    return {
        "db": db, "c": client,
        "admin": tok(ADMIN_ID, "admin@rrc.com"),
        "member": tok(MEMBER_ID, "manoj@example.com"),
        "old": tok(FRIEND_ID, "old@example.com"),
    }
