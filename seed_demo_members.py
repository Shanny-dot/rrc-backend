"""Creates (or resets) two demo member logins with sample data that shows every app feature.

    python seed_demo_members.py

Needs SUPABASE_URL and SUPABASE_SERVICE_KEY in the environment (or .env). Safe to re-run:
it wipes and rebuilds only these two demo accounts' data.

  demo1@reliiance-demo.com  — established Gold member: points history, referrals at every
                              stage, a reward sent and one pending, events (upcoming, attended
                              with a thank-you), wish list, loan check-in due today
  demo2@reliiance-demo.com  — brand-new member who joined with demo1's invite code: welcome
                              tour, profile still to complete, first referral sent
"""
import datetime
import os
import uuid
import httpx
from dotenv import load_dotenv

load_dotenv()
URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

DEMO_PASSWORD = {"demo1@reliiance-demo.com": "RewardsDemo1!", "demo2@reliiance-demo.com": "RewardsDemo2!"}
NOW = datetime.datetime.now(datetime.timezone.utc)
SYD = datetime.timezone(datetime.timedelta(hours=11))
TODAY = NOW.astimezone(SYD).date()


def at(date_str, hour=10):
    return datetime.datetime.fromisoformat(f"{date_str}T{hour:02d}:00:00+11:00").isoformat()


def ago(days, hour=10):
    return at((TODAY - datetime.timedelta(days=days)).isoformat(), hour)


def rest(method, table, params=None, json=None, prefer="return=representation"):
    r = httpx.request(method, f"{URL}/rest/v1/{table}", params=params, json=json, headers={**H, "Prefer": prefer}, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {table}: {r.status_code} {r.text[:300]}")
    return r.json() if r.content else None


def find(table, select, **eq):
    return rest("GET", table, params={"select": select, **{k: f"eq.{v}" for k, v in eq.items()}})


def auth_user(email, full_name):
    """Supabase Auth account (email confirmed). Returns its id, creating it if needed."""
    r = httpx.post(f"{URL}/auth/v1/admin/users", headers=H, timeout=60,
                   json={"email": email, "password": DEMO_PASSWORD[email], "email_confirm": True, "user_metadata": {"full_name": full_name}})
    if r.status_code < 300:
        return r.json()["id"]
    page = httpx.get(f"{URL}/auth/v1/admin/users", params={"per_page": 1000}, headers=H, timeout=60).json()
    existing = next(u for u in page["users"] if u["email"] == email)
    httpx.put(f"{URL}/auth/v1/admin/users/{existing['id']}", headers=H, timeout=60,
              json={"password": DEMO_PASSWORD[email], "email_confirm": True})
    return existing["id"]


def wipe(user_id):
    for table, col in (("notification_log", "user_id"), ("loan_reviews", "user_id"), ("feedback", "user_id"),
                       ("wishlist", "user_id"), ("event_rsvps", "user_id"), ("redemptions", "user_id"),
                       ("transactions", "user_id"), ("referrals", "referrer_id")):
        rest("DELETE", table, params={col: f"eq.{user_id}"}, prefer="return=minimal")
    rest("PATCH", "referrals", params={"referred_user_id": f"eq.{user_id}"}, json={"referred_user_id": None}, prefer="return=minimal")


def profile(user_id, row):
    if find("users", "id", id=user_id):
        rest("PATCH", "users", params={"id": f"eq.{user_id}"}, json=row)
    else:
        rest("POST", "users", json={"id": user_id, "referral_code": row.pop("referral_code"), **row})


def by_title(table, title):
    rows = find(table, "id,title", title=title)
    if not rows:
        raise RuntimeError(f"{table} '{title}' not found")
    return rows[0]["id"]


def main():
    demo1 = auth_user("demo1@reliiance-demo.com", "Alex Morgan (Demo)")
    demo2 = auth_user("demo2@reliiance-demo.com", "Sam Taylor (Demo)")
    for uid in (demo1, demo2):
        wipe(uid)

    # ── Demo 1: established Gold member ─────────────────────────────────
    history = [
        ("signup_bonus", 100, "Welcome Bonus", "2025-06-01"),
        ("event_attend", 100, "Attended First Home Buyers Breakfast", "2025-08-20"),
        ("referral", 500, "Referral reward: Priya Shah", "2025-11-10"),
        ("event_attend", 150, "Attended Property Investment Workshop", "2026-03-12"),
        ("bonus", 50, "Birthday bonus", "2026-04-12"),
        ("admin_adjustment", 1500, "Thank-you bonus for being a loyal client", "2026-05-02"),
        ("redemption", -300, "Redeemed Tandem Skydive", "2026-07-15"),
        ("redemption", -150, "Redeemed David Jones Gift Card ($50)", "2026-09-30"),
        ("bonus", 250, "Loan anniversary bonus (3 years)", TODAY.isoformat()),
    ]
    total = sum(p for _, p, _, _ in history)
    profile(demo1, {
        "full_name": "Alex Morgan (Demo)", "email": "demo1@reliiance-demo.com", "mobile": "+61491570006",
        "referral_code": "DEMOALEX", "dob": "1986-04-12", "gender": "Prefer not to say", "industry": "Information Technology",
        "street_address": "1 Demo Street", "city": "Sydney", "state": "NSW", "postal_code": "2000", "country": "Australia",
        "home_ownership": "Own with a mortgage", "annual_income": "$150,000 – $200,000", "total_points": total,
        "bonus_points_granted": True, "profile_complete": True, "created_at": at("2025-06-01"), "deleted_at": None,
        "loan_settled_on": TODAY.replace(year=TODAY.year - 3).isoformat(), "notification_prefs": {}, "referred_by": None,
    })
    rest("POST", "transactions", json=[{"user_id": demo1, "type": t, "points": p, "description": d, "created_at": at(day)}
                                       for t, p, d, day in history])

    skydive, dj50 = by_title("rewards", "Tandem Skydive"), by_title("rewards", "David Jones Gift Card ($50)")
    rest("POST", "redemptions", json=[
        {"user_id": demo1, "reward_id": skydive, "status": "sent", "points_used": 300, "requested_at": at("2026-07-15"),
         "actioned_at": at("2026-07-16"), "sent_at": at("2026-07-20"), "admin_note": "Voucher emailed"},
        {"user_id": demo1, "reward_id": dj50, "status": "pending", "points_used": 150, "requested_at": at("2026-09-30"),
         "actioned_at": None, "sent_at": None, "admin_note": None},
    ])
    rest("POST", "wishlist", json=[{"user_id": demo1, "reward_id": by_title("rewards", "Apple AirPods Pro")},
                                   {"user_id": demo1, "reward_id": by_title("rewards", "Bridge Climb")}])

    referrals = [
        ("Priya Shah", "+61491570010", "rewarded", "share", 500, "2025-11-10"),
        ("Daniel Lee", "+61491570011", "loan_in_progress", "whatsapp", 0, ago(6)[:10]),
        ("Mia Chen", "+61491570012", "contacted", "sms", 0, ago(2)[:10]),
        ("Tom Wilson", "+61491570013", "invited", "email", 0, ago(1)[:10]),
    ]
    rest("POST", "referrals", json=[
        {"referrer_id": demo1, "referred_name": n, "referred_mobile": m, "status": s, "channel": ch, "points_earned": pts,
         "consent_given": True, "created_at": at(day, 9), "stage_updated_at": at(day, 15)}
        for n, m, s, ch, pts, day in referrals])

    workshop = by_title("events", "Property Investment Workshop")
    rest("POST", "event_rsvps", json=[
        {"event_id": workshop, "user_id": demo1, "qr_token": str(uuid.uuid4()), "attended": True, "points_awarded": True,
         "rsvp_at": at("2026-03-01"), "attended_at": at("2026-03-12", 19)},
        {"event_id": by_title("events", "Property Investment Webinar"), "user_id": demo1, "qr_token": str(uuid.uuid4()),
         "attended": False, "points_awarded": False, "rsvp_at": ago(3), "attended_at": None},
        {"event_id": by_title("events", "Members Networking Evening"), "user_id": demo1, "qr_token": str(uuid.uuid4()),
         "attended": False, "points_awarded": False, "rsvp_at": ago(1), "attended_at": None},
    ])
    rest("POST", "notification_log", json=[
        {"user_id": demo1, "kind": "event_thanks", "ref": str(workshop), "title": "Thanks for coming to Property Investment Workshop",
         "body": "It was great to see you! Key points from the night:\n• Rates have eased this quarter — worth a review\n"
                 "• Offset accounts can save thousands in interest\n"
                 "Slides: https://rrc-admin.vercel.app/support\nRecording: https://rrc-admin.vercel.app/support",
         "created_at": at("2026-03-13")},
        {"user_id": demo1, "kind": "loan_checkin", "ref": str(TODAY.year), "title": "Is your loan still competitive?",
         "body": "It's been 3 years since your home loan settled. Rates change — ask your broker for a free review.",
         "created_at": NOW.isoformat()},
        {"user_id": demo1, "kind": "bonus_loan_anniversary", "ref": str(TODAY.year), "title": "Happy loan anniversary! +250 points",
         "body": "Thanks for 3 years with Reliance.", "created_at": NOW.isoformat()},
    ])

    # ── Demo 2: new member who joined with Alex's invite link ───────────
    profile(demo2, {
        "full_name": "Sam Taylor (Demo)", "email": "demo2@reliiance-demo.com", "mobile": "+61491570007",
        "referral_code": "DEMOSAM1", "total_points": 100, "bonus_points_granted": True, "profile_complete": False,
        "created_at": NOW.isoformat(), "deleted_at": None, "referred_by": demo1, "loan_settled_on": None,
        "notification_prefs": {}, "dob": None, "city": None, "state": None, "postal_code": None,
    })
    rest("POST", "transactions", json=[{"user_id": demo2, "type": "signup_bonus", "points": 100, "description": "Welcome Bonus", "created_at": NOW.isoformat()}])
    rest("POST", "referrals", json=[
        {"referrer_id": demo1, "referred_name": "Sam Taylor", "referred_mobile": "+61491570007", "referred_email": "demo2@reliiance-demo.com",
         "referred_user_id": demo2, "status": "registered", "channel": "code", "consent_given": True,
         "created_at": NOW.isoformat(), "stage_updated_at": NOW.isoformat()},
        {"referrer_id": demo2, "referred_name": "Jordan Blake", "referred_mobile": "+61491570014", "referred_email": None,
         "referred_user_id": None, "status": "invited",
         "channel": "whatsapp", "consent_given": True, "created_at": NOW.isoformat(), "stage_updated_at": NOW.isoformat()},
    ])
    print(f"Demo 1 (Alex): {total:,} points, id {demo1}")
    print(f"Demo 2 (Sam): 100 points, id {demo2}")


if __name__ == "__main__":
    main()
