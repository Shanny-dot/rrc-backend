"""End-to-end API checks for the 3.1 release: every endpoint the new app screens and the
admin site call, run against the real route code with an in-memory database."""
import time

import jwt

from tests.conftest import ADMIN_ID, FRIEND_ID, MEMBER_ID


def tx(db, uid):
    return [t for t in db.tables["transactions"] if t["user_id"] == uid]


def user(db, uid):
    return next(u for u in db.tables["users"] if u["id"] == uid)


# ── Security ───────────────────────────────────────────────────────────────
def test_health(env):
    assert env["c"].get("/health").json() == {"status": "ok"}


def test_admin_routes_require_admin(env):
    c = env["c"]
    for method, path in [("get", "/api/v1/admin/redemptions"), ("get", "/api/v1/admin/transactions"),
                         ("get", "/api/v1/admin/referrals"), ("put", "/api/v1/admin/redemptions/red-old/approve"),
                         ("post", "/api/v1/admin/events")]:
        assert getattr(c, method)(path).status_code in (401, 403), f"{path} open without login"
        assert getattr(c, method)(path, headers=env["member"]).status_code == 403, f"{path} open to members"


def test_forged_token_rejected(env):
    forged = jwt.encode({"sub": MEMBER_ID, "exp": int(time.time()) + 600}, "rrc_secret_jwt_key_2026", algorithm="HS256")
    r = env["c"].get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


# ── Home: tier, activity, notifications ───────────────────────────────────
def test_me_includes_tier(env):
    r = env["c"].get("/api/v1/auth/me", headers=env["member"])
    assert r.status_code == 200, r.text
    tier = r.json()["tier"]
    assert tier["name"] == "Gold" and tier["next_name"] == "Platinum"
    assert tier["points_to_next"] == 2900 and tier["qualifying_points"] == 2100


def test_tiers_public(env):
    r = env["c"].get("/api/v1/tiers")
    assert r.status_code == 200
    assert [t["name"] for t in r.json()["tiers"]] == ["Silver", "Gold", "Platinum"]
    assert r.json()["tiers"][1]["benefits"] == ["Everything in Silver", "Priority invites"]


def test_activity_status_labels(env):
    r = env["c"].get("/api/v1/transactions/", headers=env["member"])
    assert r.status_code == 200, r.text
    by_id = {a["id"]: a for a in r.json()}
    assert by_id["tx2"]["title"] == "Points added by Reliance team"
    assert by_id["tx2"]["status_label"] == "Points added" and by_id["tx2"]["reason"] == "Event bonus"
    assert by_id["tx3"]["status_label"] == "Pending" and by_id["tx3"]["redemption_id"] == "red-old"


def test_app_version(env):
    r = env["c"].get("/api/v1/app/version")
    assert r.status_code == 200 and r.json()["min_version"] == "3.0.0" and r.json()["latest_version"] == "3.1.0"


# ── Events ────────────────────────────────────────────────────────────────
def test_events_rsvp_cycle(env):
    c, h = env["c"], env["member"]
    assert {e["id"] for e in c.get("/api/v1/events/").json()} == {"e-up", "e-past"}
    assert c.post("/api/v1/events/e-past/rsvp", headers=h).status_code == 400, "past event accepted an RSVP"
    r = c.post("/api/v1/events/e-up/rsvp", headers=h)
    assert r.status_code == 200, r.text
    assert c.post("/api/v1/events/e-up/rsvp", headers=h).status_code == 400  # no double RSVP
    assert [x["event_id"] for x in c.get("/api/v1/events/my-rsvps", headers=h).json()] == ["e-up"]
    assert c.delete("/api/v1/events/e-up/rsvp", headers=h).status_code == 200
    assert c.get("/api/v1/events/my-rsvps", headers=h).json() == []
    assert c.post("/api/v1/events/e-up/rsvp", headers=h).status_code == 200  # re-RSVP after cancelling
    assert len(c.get("/api/v1/events/my-rsvps", headers=h).json()) == 1


def test_invite_guest_to_event(env):
    r = env["c"].post("/api/v1/events/e-up/invite-guests", headers=env["member"],
                      json=[{"guest_name": "Asha", "guest_email": "asha@example.com"}])
    assert r.status_code == 200, r.text


def test_check_in_only_on_event_day(env):
    assert env["c"].post("/api/v1/events/e-up/scan-attendance", headers=env["member"]).status_code == 400


def test_admin_create_event_with_category(env):
    r = env["c"].post("/api/v1/admin/events", headers=env["admin"], json={
        "title": "Property Investment Workshop", "category": "Real Estate", "description": "Webinar",
        "location": "Online", "event_date": "2030-11-04T08:30:00Z", "points_for_attending": 50,
        "points_for_referring": 20})
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "Real Estate"


# ── Rewards ───────────────────────────────────────────────────────────────
def test_rewards_list_and_detail(env):
    c = env["c"]
    ids = [r["id"] for r in c.get("/api/v1/rewards/").json()]
    assert ids[0] == "r-toy"  # sorted by points
    d = c.get("/api/v1/rewards/r-sky").json()
    assert d["what_you_get"] == "One tandem jump" and d["dollar_value"] == 350
    assert d["delivery_info"] == "Emailed within 5 business days"  # falls back to the default setting


def test_wishlist(env):
    c, h = env["c"], env["member"]
    assert c.post("/api/v1/rewards/r-vip/wishlist", headers=h).status_code == 200
    assert c.post("/api/v1/rewards/r-vip/wishlist", headers=h).status_code == 200  # idempotent
    assert c.get("/api/v1/rewards/wishlist", headers=h).json() == ["r-vip"]
    assert c.delete("/api/v1/rewards/r-vip/wishlist", headers=h).status_code == 200
    assert c.get("/api/v1/rewards/wishlist", headers=h).json() == []


def test_redeem_and_insufficient(env):
    c, h, db = env["c"], env["member"], env["db"]
    before = user(db, MEMBER_ID)["total_points"]
    r = c.post("/api/v1/rewards/r-sky/redeem", headers=h)
    assert r.status_code == 200, r.text
    red_id = r.json()["id"]
    assert user(db, MEMBER_ID)["total_points"] == before - 300
    assert next(x for x in db.tables["rewards"] if x["id"] == "r-sky")["stock"] == 14
    linked = [t for t in tx(db, MEMBER_ID) if t.get("reference_id") == red_id]
    assert linked and linked[0]["points"] == -300
    assert c.post("/api/v1/rewards/r-vip/redeem", headers=h).status_code == 400  # not enough points
    acts = {a["id"]: a for a in c.get("/api/v1/transactions/", headers=h).json()}
    assert acts[linked[0]["id"]]["status_label"] == "Pending"
    env["new_red"] = red_id


# ── Admin: redemptions approve → sent ─────────────────────────────────────
def test_admin_approve_then_sent(env):
    c, a, db = env["c"], env["admin"], env["db"]
    red = env["new_red"]
    assert c.put(f"/api/v1/admin/redemptions/{red}/approve", headers=a).status_code == 200
    r = c.put(f"/api/v1/admin/redemptions/{red}/sent", headers=a, json={"admin_note": "Code ABC-123"})
    assert r.status_code == 200, r.text
    row = next(x for x in db.tables["redemptions"] if x["id"] == red)
    assert row["status"] == "sent" and row["sent_at"] and row["admin_note"] == "Code ABC-123"
    acts = c.get("/api/v1/transactions/", headers=env["member"]).json()
    assert any(x.get("redemption_id") == red and x["status_label"] == "Sent" for x in acts)
    notes = c.get("/api/v1/notifications", headers=env["member"]).json()
    assert any("has been sent" in n["title"] for n in notes)


def test_admin_reject_refunds(env):
    c, db = env["c"], env["db"]
    before = user(db, MEMBER_ID)["total_points"]
    r = c.put("/api/v1/admin/redemptions/red-old/reject", headers=env["admin"], json={"admin_note": "Out of stock"})
    assert r.status_code == 200, r.text
    assert user(db, MEMBER_ID)["total_points"] == before + 50


# ── Referrals ─────────────────────────────────────────────────────────────
def test_referral_new_app_requires_consent(env):
    c, h = env["c"], env["member"]
    body = {"referred_name": "Amy", "referred_mobile": "0400 111 222", "channel": "share"}
    assert c.post("/api/v1/referrals/", headers=h, json={**body, "consent_given": False}).status_code == 400
    r = c.post("/api/v1/referrals/", headers=h, json={**body, "consent_given": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "invited" and r.json()["channel"] == "share"


def test_referral_from_live_app_3_0(env):
    # Exactly what app 3.0.0 sends: no channel, no consent field
    r = env["c"].post("/api/v1/referrals/", headers=env["member"],
                      json={"referred_name": "Ravi", "referred_mobile": "+91 98765 43210", "referred_email": "ravi@example.com"})
    assert r.status_code == 200, r.text


def test_referral_validation(env):
    c, h = env["c"], env["member"]
    assert c.post("/api/v1/referrals/", headers=h, json={"referred_name": "Bo", "referred_mobile": "12345",
                                                         "channel": "share", "consent_given": True}).status_code == 400
    assert c.post("/api/v1/referrals/", headers=h, json={"referred_name": "Old", "referred_email": "old@example.com",
                                                         "channel": "email", "consent_given": True}).status_code == 400


def test_admin_referral_stages_and_points(env):
    c, a, db = env["c"], env["admin"], env["db"]
    listing = c.get("/api/v1/admin/referrals", headers=a).json()
    assert any(r["referrer"] and r["referrer"]["full_name"] == "Manoj Kumar" for r in listing)
    before = user(db, MEMBER_ID)["total_points"]
    for stage in ["contacted", "loan_in_progress", "settled"]:
        assert c.put("/api/v1/admin/referrals/ref-old/stage", headers=a, json={"status": stage}).status_code == 200
    r = c.put("/api/v1/admin/referrals/ref-old/stage", headers=a, json={"status": "rewarded"})
    assert r.status_code == 200, r.text
    assert user(db, MEMBER_ID)["total_points"] == before + 500  # referral_points setting
    c.put("/api/v1/admin/referrals/ref-old/stage", headers=a, json={"status": "rewarded"})
    assert user(db, MEMBER_ID)["total_points"] == before + 500, "points awarded twice"
    s = c.get("/api/v1/referrals/summary", headers=env["member"]).json()
    assert s["points_earned"] == 500 and s["points_per_referral"] == 500 and s["referral_code"] == "MANOJ123"
    mine = {r["id"]: r for r in c.get("/api/v1/referrals/", headers=env["member"]).json()}
    assert mine["ref-old"]["status"] == "rewarded"


# ── Admin: points, profile, delete ────────────────────────────────────────
def test_admin_points_adjustment_shows_in_activity(env):
    c, db = env["c"], env["db"]
    cur = user(db, FRIEND_ID)["total_points"]
    r = c.put(f"/api/v1/admin/users/{FRIEND_ID}/points", headers=env["admin"],
              json={"new_points": cur + 250, "reason": "Goodwill"})
    assert r.status_code == 200, r.text
    acts = c.get("/api/v1/transactions/", headers=env["old"]).json()
    assert acts[0]["title"] == "Points added by Reliance team" and acts[0]["points"] == 250
    assert acts[0]["reason"] == "Goodwill"


def test_profile_update_with_new_options(env):
    r = env["c"].put("/api/v1/auth/profile", headers=env["member"], json={
        "dob": "1986-03-14", "gender": "Male", "state": "NSW", "industry": "Accounting & Finance",
        "home_ownership": "Own with a mortgage", "annual_income": "$50,000 – $100,000"})
    assert r.status_code == 200, r.text
    assert user(env["db"], MEMBER_ID)["home_ownership"] == "Own with a mortgage"


def test_admin_delete_blocks_member(env):
    c = env["c"]
    assert c.get("/api/v1/auth/me", headers=env["old"]).status_code == 200
    assert c.delete(f"/api/v1/admin/users/{FRIEND_ID}", headers=env["admin"]).status_code == 200
    assert c.get("/api/v1/auth/me", headers=env["old"]).status_code == 401
    assert c.post(f"/api/v1/admin/users/{FRIEND_ID}/restore", headers=env["admin"]).status_code == 200
    assert c.get("/api/v1/auth/me", headers=env["old"]).status_code == 200


def test_errors_are_readable_by_the_admin_site(env):
    # A crash must come back as JSON with CORS headers, not as a browser "Network Error"
    db = env["db"]
    saved = db.columns["events"]
    db.columns["events"] = [c for c in saved if c != "category"]
    try:
        r = env["c"].post("/api/v1/admin/events", headers={**env["admin"], "Origin": "https://rrc-admin.vercel.app"},
                          json={"title": "X", "category": "Y", "event_date": "2030-01-01T00:00:00Z"})
    finally:
        db.columns["events"] = saved
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == "https://rrc-admin.vercel.app"
    assert "category" in r.json()["detail"]
