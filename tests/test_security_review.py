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
