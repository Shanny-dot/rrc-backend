"""Security review (phase 4, internal): regression tests for the weaknesses found."""
from tests.conftest import MEMBER_ID


def _member(db, uid=MEMBER_ID):
    return next(u for u in db.tables["users"] if u["id"] == uid)


def test_sign_up_check_cannot_sign_in_to_a_verified_account(env):
    """verify-signup used to sign in as ANY fully verified member from just their email."""
    db, c = env["db"], env["c"]
    member = _member(db)
    saved = (member.get("mobile_verified_at"), member.get("email_verified_at"))
    member["mobile_verified_at"] = member["email_verified_at"] = "2026-10-01T00:00:00+00:00"
    try:
        for body in ({"email": member["email"]},
                     {"email": member["email"], "mobile_code": "123456", "email_code": "654321"}):
            r = c.post("/api/v1/auth/verify-signup", json=body)
            assert r.status_code == 400 and "access_token" not in r.json()
            assert "already verified" in r.json()["detail"]
    finally:
        member["mobile_verified_at"], member["email_verified_at"] = saved


def test_invitation_emails_are_capped_per_member(env):
    from app.core import send_limits
    send_limits.reset_all()
    c = env["c"]
    event = "11111111-0000-4000-8000-000000000001"
    guests = lambda n, tag: [{"guest_name": f"G{tag}{i}", "guest_email": f"g{tag}{i}@example.com"} for i in range(n)]  # noqa: E731
    assert c.post(f"/api/v1/events/{event}/invite-guests", headers=env["member"], json=guests(11, "x")).status_code == 400
    for batch in range(3):
        assert c.post(f"/api/v1/events/{event}/invite-guests", headers=env["member"], json=guests(10, batch)).status_code == 200
    r = c.post(f"/api/v1/events/{event}/invite-guests", headers=env["member"], json=guests(1, "y"))
    assert r.status_code == 429 and "tomorrow" in r.json()["detail"]
    # Referral invitations: past the cap the referral is still saved, just not emailed by us
    send_limits.LIMITS["referral_invites"], saved = 1, send_limits.LIMITS["referral_invites"]
    try:
        body = lambda n: {"referred_name": f"Friend {n}", "referred_email": f"friend{n}@example.com",  # noqa: E731
                          "channel": "email", "consent_given": True}
        assert c.post("/api/v1/referrals/", headers=env["old"], json=body(1)).status_code == 200
        r = c.post("/api/v1/referrals/", headers=env["old"], json=body(2))
        assert r.status_code == 200 and r.json()["invite_emailed"] is False
    finally:
        send_limits.LIMITS["referral_invites"] = saved
        send_limits.reset_all()


def test_staff_only_event_check_in(env):
    import datetime
    db, c = env["db"], env["c"]
    start = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
    event = {"title": "Staff check-in", "event_date": start, "is_active": True, "points_for_attending": 40}
    made = c.post("/api/v1/admin/events", headers=env["admin"], json=event)
    assert made.status_code == 200
    event_id = made.json()["id"]
    assert c.post(f"/api/v1/events/{event_id}/rsvp", headers=env["member"], json={}).status_code == 200
    db.tables["app_content"].append({"key": "event_self_checkin", "value": "0"})
    try:
        before = _member(db).get("total_points") or 0
        r = c.post(f"/api/v1/events/{event_id}/scan-attendance", headers=env["member"])
        assert r.status_code == 403 and "staff" in r.json()["detail"]
        assert (_member(db).get("total_points") or 0) == before
        # Members can't see the list or check themselves in the staff way
        assert c.get(f"/api/v1/admin/events/{event_id}/attendees", headers=env["member"]).status_code == 403
        people = c.get(f"/api/v1/admin/events/{event_id}/attendees", headers=env["admin"]).json()
        mine = next(p for p in people if p["email"] == _member(db)["email"])
        assert mine["attended"] is False
        assert c.post("/api/v1/admin/events/scan-qr", headers=env["admin"], json={"qr_token": mine["qr_token"]}).status_code == 200
        assert (_member(db).get("total_points") or 0) == before + 40
        assert c.post("/api/v1/admin/events/scan-qr", headers=env["admin"], json={"qr_token": mine["qr_token"]}).status_code == 400
    finally:
        db.tables["app_content"][:] = [r for r in db.tables["app_content"] if r["key"] != "event_self_checkin"]


def test_job_key_is_checked(env):
    c = env["c"]
    assert c.post("/api/v1/jobs/daily", headers={"X-Job-Key": "wrong"}).status_code == 403
    assert c.post("/api/v1/jobs/daily").status_code == 403


def test_verification_codes_cannot_be_guessed(env):
    from app.api.routes.auth import limiter
    from app.services import sms_service
    sms_service.reset_code_attempts(); limiter.reset()
    c, mobile = env["c"], "+61491570157"
    right = sms_service.issue_code(mobile)
    wrong = "000000" if right != "000000" else "111111"
    for _ in range(sms_service.MAX_CODE_FAILS):
        assert not sms_service.code_matches(mobile, wrong)
    # Locked: even the right code is refused for this number now...
    assert not sms_service.code_matches(mobile, right)
    # ...including through the sign-in-by-SMS endpoint
    r = c.post("/api/v1/auth/verify-mobile", json={"mobile": "0491 570 157", "code": right})
    assert r.status_code == 400
    # Other numbers are unaffected
    other = "+61491570158"
    assert sms_service.code_matches(other, sms_service.issue_code(other))
    sms_service.reset_code_attempts(); limiter.reset()
    assert sms_service.code_matches(mobile, right)
    sms_service.reset_code_attempts()
