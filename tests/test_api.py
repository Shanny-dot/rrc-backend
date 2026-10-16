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
                         ("get", "/api/v1/admin/referrals"), ("put", "/api/v1/admin/redemptions/33333333-0000-4000-8000-000000000001/approve"),
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
    assert by_id["55555555-0000-4000-8000-000000000002"]["title"] == "Points added by Reliance team"
    assert by_id["55555555-0000-4000-8000-000000000002"]["status_label"] == "Points added" and by_id["55555555-0000-4000-8000-000000000002"]["reason"] == "Event bonus"
    assert by_id["55555555-0000-4000-8000-000000000003"]["status_label"] == "Pending" and by_id["55555555-0000-4000-8000-000000000003"]["redemption_id"] == "33333333-0000-4000-8000-000000000001"


def test_app_version(env):
    r = env["c"].get("/api/v1/app/version")
    assert r.status_code == 200 and r.json()["min_version"] == "3.0.0" and r.json()["latest_version"] == "3.1.0"


# ── Events ────────────────────────────────────────────────────────────────
def test_events_rsvp_cycle(env):
    c, h = env["c"], env["member"]
    assert {e["id"] for e in c.get("/api/v1/events/").json()} == {"11111111-0000-4000-8000-000000000001", "11111111-0000-4000-8000-000000000002"}
    assert c.post("/api/v1/events/11111111-0000-4000-8000-000000000002/rsvp", headers=h).status_code == 400, "past event accepted an RSVP"
    r = c.post("/api/v1/events/11111111-0000-4000-8000-000000000001/rsvp", headers=h)
    assert r.status_code == 200, r.text
    assert c.post("/api/v1/events/11111111-0000-4000-8000-000000000001/rsvp", headers=h).status_code == 400  # no double RSVP
    assert [x["event_id"] for x in c.get("/api/v1/events/my-rsvps", headers=h).json()] == ["11111111-0000-4000-8000-000000000001"]
    assert c.delete("/api/v1/events/11111111-0000-4000-8000-000000000001/rsvp", headers=h).status_code == 200
    assert c.get("/api/v1/events/my-rsvps", headers=h).json() == []
    assert c.post("/api/v1/events/11111111-0000-4000-8000-000000000001/rsvp", headers=h).status_code == 200  # re-RSVP after cancelling
    assert len(c.get("/api/v1/events/my-rsvps", headers=h).json()) == 1


def test_invite_guest_to_event(env):
    r = env["c"].post("/api/v1/events/11111111-0000-4000-8000-000000000001/invite-guests", headers=env["member"],
                      json=[{"guest_name": "Asha", "guest_email": "asha@example.com"}])
    assert r.status_code == 200, r.text


def test_check_in_only_on_event_day(env):
    assert env["c"].post("/api/v1/events/11111111-0000-4000-8000-000000000001/scan-attendance", headers=env["member"]).status_code == 400


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
    assert ids[0] == "22222222-0000-4000-8000-000000000003"  # sorted by points
    d = c.get("/api/v1/rewards/22222222-0000-4000-8000-000000000001").json()
    assert d["what_you_get"] == "One tandem jump" and d["dollar_value"] == 350
    assert d["delivery_info"] == "Emailed within 5 business days"  # falls back to the default setting


def test_wishlist(env):
    c, h = env["c"], env["member"]
    assert c.post("/api/v1/rewards/22222222-0000-4000-8000-000000000002/wishlist", headers=h).status_code == 200
    assert c.post("/api/v1/rewards/22222222-0000-4000-8000-000000000002/wishlist", headers=h).status_code == 200  # idempotent
    assert c.get("/api/v1/rewards/wishlist", headers=h).json() == ["22222222-0000-4000-8000-000000000002"]
    assert c.delete("/api/v1/rewards/22222222-0000-4000-8000-000000000002/wishlist", headers=h).status_code == 200
    assert c.get("/api/v1/rewards/wishlist", headers=h).json() == []


def test_redeem_and_insufficient(env):
    c, h, db = env["c"], env["member"], env["db"]
    before = user(db, MEMBER_ID)["total_points"]
    r = c.post("/api/v1/rewards/22222222-0000-4000-8000-000000000001/redeem", headers=h)
    assert r.status_code == 200, r.text
    red_id = r.json()["id"]
    assert user(db, MEMBER_ID)["total_points"] == before - 300
    assert next(x for x in db.tables["rewards"] if x["id"] == "22222222-0000-4000-8000-000000000001")["stock"] == 14
    linked = [t for t in tx(db, MEMBER_ID) if t.get("reference_id") == red_id]
    assert linked and linked[0]["points"] == -300
    assert c.post("/api/v1/rewards/22222222-0000-4000-8000-000000000002/redeem", headers=h).status_code == 400  # not enough points
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
    r = c.put("/api/v1/admin/redemptions/33333333-0000-4000-8000-000000000001/reject", headers=env["admin"], json={"admin_note": "Out of stock"})
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
        assert c.put("/api/v1/admin/referrals/44444444-0000-4000-8000-000000000001/stage", headers=a, json={"status": stage}).status_code == 200
    r = c.put("/api/v1/admin/referrals/44444444-0000-4000-8000-000000000001/stage", headers=a, json={"status": "rewarded"})
    assert r.status_code == 200, r.text
    assert user(db, MEMBER_ID)["total_points"] == before + 500  # referral_points setting
    c.put("/api/v1/admin/referrals/44444444-0000-4000-8000-000000000001/stage", headers=a, json={"status": "rewarded"})
    assert user(db, MEMBER_ID)["total_points"] == before + 500, "points awarded twice"
    s = c.get("/api/v1/referrals/summary", headers=env["member"]).json()
    assert s["points_earned"] == 500 and s["points_per_referral"] == 500 and s["referral_code"] == "MANOJ123"
    mine = {r["id"]: r for r in c.get("/api/v1/referrals/", headers=env["member"]).json()}
    assert mine["44444444-0000-4000-8000-000000000001"]["status"] == "rewarded"


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


def test_login_repairs_missing_profile(env):
    """An account that exists in Supabase Auth but has no member profile can log in,
    gets a profile with the welcome bonus, and every screen works."""
    db, c = env["db"], env["c"]
    orphan_id = "00000000-0000-4000-8000-0000000000d4"
    db.auth.accounts["varun@example.com"] = ("Secret123!", orphan_id, "Varun")
    r = c.post("/api/v1/auth/login", json={"email": "Varun@Example.com ", "password": "Secret123!"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = c.get("/api/v1/auth/me", headers=h)
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "varun@example.com" and me.json()["total_points"] == 100
    # Logging in again doesn't create a second profile or a second bonus.
    c.post("/api/v1/auth/login", json={"email": "varun@example.com", "password": "Secret123!"})
    assert len([u for u in db.tables["users"] if u["email"] == "varun@example.com"]) == 1
    assert c.post("/api/v1/auth/login", json={"email": "varun@example.com", "password": "wrong"}).status_code == 400


def test_forgot_password_link_opens_reset_page(env):
    r = env["c"].post("/api/v1/auth/forgot-password", json={"email": "Manoj@Example.com"})
    assert r.status_code == 200 and r.json()["success"]
    email, opts = env["db"].auth.reset_requests[-1]
    assert email == "manoj@example.com"
    assert opts["redirect_to"] == "https://rrc-admin.vercel.app/reset-password"


# ── Mobile OTP (Guni SMS) ─────────────────────────────────────────────────
def _capture_guni(monkeypatch):
    """Stub the Guni gateway; return the list of JSON payloads it was sent."""
    import httpx
    import app.services.sms_service as sms
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == sms.GUNI_GATEWAY_URL and headers["Authorization"] == "Bearer test-guni-key"
        sent.append(json)
        return httpx.Response(200, json={"status": True, "message": "Quick SMS Sent Successfully"})

    monkeypatch.setattr(sms, "_SMS_ENABLED", True)
    monkeypatch.setattr(sms.settings, "GUNI_SMS_API_KEY", "test-guni-key")
    monkeypatch.setattr(sms.httpx, "post", fake_post)
    return sent


def test_mobile_otp_send_and_verify(env, monkeypatch):
    c, db = env["c"], env["db"]
    user(db, FRIEND_ID)["mobile"] = "+61412000111"
    sent = _capture_guni(monkeypatch)

    # The app may send the local format; it must reach Guni (and match on verify) as +61.
    r = c.post("/api/v1/auth/resend-otp", json={"mobile": "0412 000 111"})
    assert r.status_code == 200, r.text
    assert sent[-1]["contacts"] == ["61412000111"] and sent[-1]["sender"] == "Reliiance"
    code = sent[-1]["message"].split("code is ")[1][:6]
    assert code.isdigit()

    wrong = str((int(code) + 1) % 1000000).zfill(6)
    assert c.post("/api/v1/auth/verify-mobile", json={"mobile": "+61412000111", "code": wrong}).status_code == 400

    r = c.post("/api/v1/auth/verify-mobile", json={"mobile": "0412000111", "code": code})
    assert r.status_code == 200, r.text
    me = c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "old@example.com"


def test_mobile_otp_unknown_number_and_sms_off(env, monkeypatch):
    c = env["c"]
    sent = _capture_guni(monkeypatch)
    c.post("/api/v1/auth/resend-otp", json={"mobile": "+61499999999"})
    code = sent[-1]["message"].split("code is ")[1][:6]
    r = c.post("/api/v1/auth/verify-mobile", json={"mobile": "+61499999999", "code": code})
    assert r.status_code == 404

    import app.services.sms_service as sms
    monkeypatch.setattr(sms, "_SMS_ENABLED", False)
    assert c.post("/api/v1/auth/resend-otp", json={"mobile": "+61412000111"}).status_code == 400


# ── Help & contact settings ───────────────────────────────────────────────
def test_help_and_contact_content(env):
    import json
    c = env["c"]
    content = c.get("/api/v1/content").json()
    faq = json.loads(content["help_faq"])
    assert faq and all(i["q"] and i["a"] for i in faq)
    assert content["terms_url"].startswith("https://") and "contact_phone" in content

    # Staff edit the contact details and the questions; members see them straight away.
    assert c.put("/api/v1/content/contact_phone", json={"value": "02 9000 0000"}).status_code in (401, 403)
    assert c.put("/api/v1/content/contact_phone", headers=env["admin"], json={"value": "02 9000 0000"}).status_code == 200
    new_faq = json.dumps([{"q": "Who do I call?", "a": "Your broker."}])
    assert c.put("/api/v1/content/help_faq", headers=env["admin"], json={"value": new_faq}).status_code == 200
    content = c.get("/api/v1/content").json()
    assert content["contact_phone"] == "02 9000 0000" and json.loads(content["help_faq"])[0]["q"] == "Who do I call?"

    # A broken list is refused rather than blanking the Help page.
    bad = c.put("/api/v1/content/help_faq", headers=env["admin"], json={"value": json.dumps([{"q": "No answer"}])})
    assert bad.status_code == 400
    # Editing a migration-created setting keeps its label.
    c.put("/api/v1/content/referral_points", headers=env["admin"], json={"value": "500"})
    row = next(r for r in env["db"].tables["app_content"] if r["key"] == "referral_points")
    assert row.get("label") != "referral_points"


# ── Personal invite links ─────────────────────────────────────────────────
def test_invite_link_fills_in_code_after_install(env):
    c = env["c"]
    friend_phone = {"CF-Connecting-IP": "203.0.113.5"}
    assert c.get("/api/v1/referrals/summary", headers=env["member"]).json()["invite_link"] == \
        "https://rrc-admin.vercel.app/join/MANOJ123"

    # Friend opens the link: the page greets them with the inviter's first name.
    r = c.post("/api/v1/referrals/invite/manoj123", headers=friend_phone)
    assert r.json() == {"valid": True, "code": "MANOJ123", "inviter_first_name": "Manoj"}
    assert c.post("/api/v1/referrals/invite/NOPE0000", headers=friend_phone).json() == {"valid": False}

    # After installing, the app on the same network gets the code; other networks don't.
    assert c.get("/api/v1/referrals/pending-invite", headers=friend_phone).json() == {"code": "MANOJ123"}
    assert c.get("/api/v1/referrals/pending-invite", headers={"CF-Connecting-IP": "198.51.100.9"}).json() == {"code": None}
    # A faked X-Forwarded-For doesn't override the address Cloudflare reports.
    spoof = {"CF-Connecting-IP": "198.51.100.9", "X-Forwarded-For": "203.0.113.5"}
    assert c.get("/api/v1/referrals/pending-invite", headers=spoof).json() == {"code": None}


def test_signup_with_invite_code_links_referral(env):
    c, db = env["c"], env["db"]
    # Manoj already added this friend by mobile; she signs up with his code.
    c.post("/api/v1/referrals/", headers=env["member"], json={
        "referred_name": "Priya", "referred_mobile": "0411 222 333", "channel": "sms", "consent_given": True})
    r = c.post("/api/v1/auth/register", json={
        "full_name": "Priya Shah", "email": "priya@example.com", "password": "Secret123!",
        "mobile": "+61411222333", "referral_code": "manoj123"})
    assert r.status_code == 200, r.text
    priya = next(u for u in db.tables["users"] if u["email"] == "priya@example.com")
    assert priya["referred_by"] == MEMBER_ID
    refs = [f for f in db.tables["referrals"] if f["referrer_id"] == MEMBER_ID and f.get("referred_user_id") == priya["id"]]
    assert len(refs) == 1 and refs[0]["status"] == "registered" and refs[0]["referred_name"] == "Priya"

    # A code-only signup (no earlier referral) creates the referral row instead.
    c.post("/api/v1/auth/register", json={"full_name": "Sam Lee", "email": "sam@example.com", "password": "Secret123!",
                                          "mobile": "0400 999 888", "referral_code": "MANOJ123"})
    sam = next(u for u in db.tables["users"] if u["email"] == "sam@example.com")
    row = next(f for f in db.tables["referrals"] if f.get("referred_user_id") == sam["id"])
    assert row["channel"] == "code" and row["status"] == "registered"


# ── Feedback ──────────────────────────────────────────────────────────────
def test_feedback_reaches_admin(env):
    c = env["c"]
    assert c.post("/api/v1/feedback", json={"message": "Hi"}).status_code in (401, 403)
    assert c.post("/api/v1/feedback", headers=env["member"], json={"message": "  "}).status_code == 400
    r = c.post("/api/v1/feedback", headers=env["member"], json={
        "message": "Love the app! Could events show parking info?", "category": "idea", "app_version": "3.2.0", "platform": "ios"})
    assert r.status_code == 200, r.text

    assert c.get("/api/v1/admin/feedback", headers=env["member"]).status_code == 403
    items = c.get("/api/v1/admin/feedback", headers=env["admin"]).json()
    assert items[0]["category"] == "idea" and items[0]["status"] == "new"
    assert items[0]["users"]["email"] == "manoj@example.com"
    r = c.put(f"/api/v1/admin/feedback/{items[0]['id']}", headers=env["admin"], json={"status": "resolved"})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    assert c.put(f"/api/v1/admin/feedback/{items[0]['id']}", headers=env["admin"], json={"status": "done"}).status_code == 400


# ── Broker requests (Book a time / loan review) ───────────────────────────
def test_book_a_time_reaches_staff(env):
    import datetime
    c = env["c"]
    day = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
    r = c.post("/api/v1/broker/requests", headers=env["member"],
               json={"kind": "call", "preferred_date": day, "preferred_time": "morning", "note": "Best on my mobile"})
    assert r.status_code == 200, r.text
    assert c.post("/api/v1/broker/requests", headers=env["member"], json={"kind": "call", "preferred_date": "2020-01-01"}).status_code == 400
    assert c.post("/api/v1/broker/requests", headers=env["member"], json={"kind": "lunch"}).status_code == 400

    assert c.get("/api/v1/admin/broker-requests", headers=env["member"]).status_code == 403
    items = c.get("/api/v1/admin/broker-requests", headers=env["admin"]).json()
    pretty = datetime.date.fromisoformat(day).strftime("%a %d %b %Y")
    assert items[0]["note"] == f"Call booking: {pretty}, morning. Best on my mobile"
    assert items[0]["status"] == "new" and items[0]["users"]["email"] == "manoj@example.com"
    r = c.put(f"/api/v1/admin/broker-requests/{items[0]['id']}", headers=env["admin"], json={"status": "contacted", "staff_note": "Called Tue"})
    assert r.status_code == 200 and r.json()["status"] == "contacted" and r.json()["staff_note"] == "Called Tue"


# ── Phase 3: alerts, bonuses, loan check-ins, thank-yous ───────────────────
def _setting(db, key, value):
    rows = db.tables["app_content"]
    row = next((r for r in rows if r["key"] == key), None)
    if row:
        row["value"] = value
    else:
        rows.append({"key": key, "value": value})


def _capture_push(monkeypatch):
    import app.services.notify_service as ns
    sent = []

    def fake_send(token, title, body, data=None):
        sent.append((token, title, body, data))
        return "sent"

    monkeypatch.setattr(ns.PushService, "send_push_notification", staticmethod(fake_send))
    return sent


def test_notification_settings_mute_alerts(env, monkeypatch):
    c, db = env["c"], env["db"]
    sent = _capture_push(monkeypatch)
    user(db, MEMBER_ID)["fcm_token"] = "tok-manoj"
    assert c.get("/api/v1/auth/notification-prefs", headers=env["member"]).json() == \
        {"points": True, "referrals": True, "rewards": True, "events": True, "expiry": True, "loan": True}
    r = c.put("/api/v1/auth/notification-prefs", headers=env["member"], json={"points": False, "bogus": True})
    assert r.json()["points"] is False and "bogus" not in r.json()

    c.put(f"/api/v1/admin/users/{MEMBER_ID}/points", headers=env["admin"], json={"new_points": user(db, MEMBER_ID)["total_points"] + 10})
    assert sent == []  # points alerts muted
    c.put("/api/v1/auth/notification-prefs", headers=env["member"], json={"points": True})
    c.put(f"/api/v1/admin/users/{MEMBER_ID}/points", headers=env["admin"],
          json={"new_points": user(db, MEMBER_ID)["total_points"] + 25, "reason": "Thanks!"})
    assert sent[-1][:3] == ("tok-manoj", "+25 points added", "Thanks!")


def test_referral_progress_alert_and_first_referral_bonus(env, monkeypatch):
    c, db = env["c"], env["db"]
    sent = _capture_push(monkeypatch)
    user(db, FRIEND_ID)["fcm_token"] = "tok-old"
    _setting(db, "bonus_first_referral_points", "250")
    refs = []
    for i, name in enumerate(("Ann", "Ben")):
        rid = f"44444444-0000-4000-8000-00000000010{i}"
        db.tables["referrals"].append({"id": rid, "referrer_id": FRIEND_ID, "referred_name": name, "status": "invited", "points_earned": 0})
        refs.append(rid)
    before = user(db, FRIEND_ID)["total_points"]
    c.put(f"/api/v1/admin/referrals/{refs[0]}/stage", headers=env["admin"], json={"status": "contacted"})
    assert sent[-1][1:3] == ("Referral update", "Reliance has contacted Ann.")
    c.put(f"/api/v1/admin/referrals/{refs[0]}/stage", headers=env["admin"], json={"status": "settled"})
    c.put(f"/api/v1/admin/referrals/{refs[1]}/stage", headers=env["admin"], json={"status": "settled"})
    bonuses = [t for t in tx(db, FRIEND_ID) if t["type"] == "bonus"]
    assert len(bonuses) == 1 and bonuses[0]["points"] == 250
    assert user(db, FRIEND_ID)["total_points"] == before + 250


def test_daily_job_reminders_birthdays_and_loan_checkin(env, monkeypatch):
    import datetime
    from app.api.routes import jobs
    c, db = env["c"], env["db"]
    sent = _capture_push(monkeypatch)
    assert c.post("/api/v1/jobs/daily").status_code == 403
    assert c.post("/api/v1/jobs/daily", headers={"X-Job-Key": "wrong"}).status_code == 403

    today = jobs._today()
    leap_day = today.month == 2 and today.day == 29
    _setting(db, "bonus_birthday_points", "50")
    member = user(db, MEMBER_ID)
    member.update({
        "fcm_token": "tok-manoj",
        "dob": "1985-02-28" if leap_day else today.replace(year=1985).isoformat(),
        "loan_settled_on": None if leap_day else today.replace(year=today.year - 2).isoformat(),
    })
    start = datetime.datetime.combine(today + datetime.timedelta(days=1), datetime.time(18, 30), tzinfo=jobs.PROGRAM_TZ)
    ev = "11111111-0000-4000-8000-0000000000aa"
    db.tables["events"].append({"id": ev, "title": "Investor Night", "location": "Parramatta",
                                "event_date": start.isoformat(), "is_active": True})
    db.tables["event_rsvps"].append({"id": "77777777-0000-4000-8000-0000000000aa", "event_id": ev,
                                     "user_id": MEMBER_ID, "cancelled": False, "attended": False})
    points_before = member["total_points"]

    r = c.post("/api/v1/jobs/daily", headers={"X-Job-Key": "test-job-key"})
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["event_reminders"] == 1 and summary["birthday_bonuses"] == 1, summary
    titles = [s[1] for s in sent]
    assert "See you tomorrow: Investor Night" in titles and "Happy birthday! +50 points" in titles
    assert member["total_points"] == points_before + 50
    if member.get("loan_settled_on"):
        assert summary["loan_checkins"] == 1 and "Is your loan still competitive?" in titles
        assert c.get("/api/v1/broker/checkin", headers=env["member"]).json()["due"] is True
        updates = c.get("/api/v1/notifications", headers=env["member"]).json()
        assert any(u.get("type") == "loan_checkin" for u in updates)
        c.post("/api/v1/broker/requests", headers=env["member"], json={"kind": "loan_review"})
        assert c.get("/api/v1/broker/checkin", headers=env["member"]).json()["due"] is False

    # A second run the same day sends and pays nothing again.
    n = len(sent)
    again = c.post("/api/v1/jobs/daily", headers={"X-Job-Key": "test-job-key"}).json()
    assert again["event_reminders"] == 0 and again["birthday_bonuses"] == 0 and len(sent) == n
    assert member["total_points"] == points_before + 50


def test_points_expiry_uses_oldest_points_first():
    import datetime
    from app.api.routes import jobs

    def ts(d):
        return f"{d}T02:00:00+00:00"

    history = [
        {"type": "signup_bonus", "points": 100, "created_at": ts("2024-09-01")},   # older than 24 months
        {"type": "referral", "points": 500, "created_at": ts("2024-11-01")},       # turns 24 months within 30 days
        {"type": "event_attend", "points": 200, "created_at": ts("2026-01-01")},
        {"type": "redemption", "points": -150, "created_at": ts("2025-02-01")},   # uses the oldest points first
        {"type": "redemption_refund", "points": 50, "created_at": ts("2025-02-03")},
    ]
    # The 100 oldest points were spent, so nothing expires today; the 500 from Nov 2024 expire within 30 days.
    assert jobs.expiry_amounts(history, balance=700, months=24, today=datetime.date(2026, 10, 15)) == (0, 500)
    assert jobs.expiry_amounts(history, balance=700, months=24, today=datetime.date(2026, 11, 5)) == (500, 0)
    assert jobs._add_months(datetime.date(2026, 3, 31), -1) == datetime.date(2026, 2, 28)


def test_event_thank_you_reaches_attendees(env, monkeypatch):
    c, db = env["c"], env["db"]
    sent = _capture_push(monkeypatch)
    user(db, MEMBER_ID)["fcm_token"] = "tok-manoj"
    ev = "11111111-0000-4000-8000-000000000002"
    db.tables["event_rsvps"].append({"id": "77777777-0000-4000-8000-0000000000bb", "event_id": ev, "user_id": MEMBER_ID,
                                     "attended": True, "cancelled": False})
    bad = c.post(f"/api/v1/admin/events/{ev}/thank-you", headers=env["admin"], json={"message": "Thanks all!", "slides_url": "ftp://x"})
    assert bad.status_code == 400
    r = c.post(f"/api/v1/admin/events/{ev}/thank-you", headers=env["admin"],
               json={"message": "Great night. Key point: rates are moving.", "slides_url": "https://example.com/slides"})
    assert r.status_code == 200, r.text
    assert r.json()["notified"] == 1 and r.json()["email_enabled"] is False
    assert sent[-1][1] == "Thanks for coming to Market Update"
    update = next(u for u in c.get("/api/v1/notifications", headers=env["member"]).json() if u.get("type") == "event_thanks")
    assert "Slides: https://example.com/slides" in update["body"]
    # Sending again doesn't message the same people twice.
    again = c.post(f"/api/v1/admin/events/{ev}/thank-you", headers=env["admin"], json={"message": "Thanks again all"})
    assert again.json()["notified"] == 0


# ── Email via ZeptoMail ───────────────────────────────────────────────────
def test_emails_go_through_zeptomail(monkeypatch):
    import httpx
    import app.services.email_service as es
    calls = []

    def fake_post(url, json=None, timeout=None, headers=None):
        calls.append((url, json, headers))
        return httpx.Response(201, json={"data": [{"code": "EM_104", "message": "Email request received"}]})

    monkeypatch.setattr(es.settings, "ZEPTOMAIL_API_KEY", "abc123token")
    monkeypatch.setattr(es.settings, "FROM_NAME", "Reliance Rewards")
    monkeypatch.setattr(es, "_EMAIL_ENABLED", True)
    monkeypatch.setattr(es, "FROM_EMAIL", "noreply@reliiancerewards.com.au")
    monkeypatch.setattr(es.httpx, "post", fake_post)

    es.EmailService.send_staff_feedback("staff@example.com", {"full_name": "Manoj", "email": "manoj@example.com"},
                                        {"category": "idea", "message": "More events please"})
    url, body, headers = calls[-1]
    assert url == "https://api.zeptomail.com.au/v1.1/email"
    assert headers["Authorization"] == "Zoho-enczapikey abc123token"
    assert body["from"] == {"address": "noreply@reliiancerewards.com.au", "name": "Reliance Rewards"}
    assert body["to"] == [{"email_address": {"address": "staff@example.com"}}]
    assert body["reply_to"] == [{"address": "manoj@example.com"}]
    assert "More events please" in body["htmlbody"] and body["subject"] == "App feedback from Manoj"

    # A refused send (e.g. no credits) is reported as not sent rather than crashing the request.
    monkeypatch.setattr(es.httpx, "post", lambda *a, **k: httpx.Response(429, json={"error": {"message": "Credit exhausted"}}))
    assert es.EmailService.send_event_thank_you("a@example.com", "Al", "Gala", "Thanks!", []) is False
