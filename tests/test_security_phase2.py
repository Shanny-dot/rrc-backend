"""Security phase 2: staff access levels, the activity log, alerts, new sign-in emails and
signing out of every device."""
import time

import jwt
import pytest

from tests.conftest import ADMIN_ID, MEMBER_ID


def staff_session(db, uid, email, role, aal="aal2"):
    """A signed-in admin-site session for a staff member with the given access level."""
    if not any(u["id"] == uid for u in db.tables["users"]):
        db.tables["users"].append({"id": uid, "full_name": email.split("@")[0].title(), "email": email,
                                   "is_admin": True, "admin_role": role, "total_points": 0,
                                   "referral_code": uid[-8:].upper(), "deleted_at": None})
    token = jwt.encode({"sub": uid, "aal": aal, "iat": int(time.time()), "n": uid + role}, "test-only", algorithm="HS256")
    db.auth.accounts.setdefault(email, ("Staff#Pass-2026", uid, email))
    db.auth.sessions[token] = uid
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def mail(monkeypatch):
    import app.services.email_service as es
    from app.services import audit_service
    sent = []
    monkeypatch.setattr(es, "_EMAIL_ENABLED", True)
    monkeypatch.setattr(es, "_send", lambda params: sent.append(params))
    audit_service.reset_alerts()
    return sent


VIEWER = "00000000-0000-4000-8000-0000000000d1"
STAFF = "00000000-0000-4000-8000-0000000000d2"
MANAGER = "00000000-0000-4000-8000-0000000000d3"


def test_access_levels(env):
    db, c = env["db"], env["c"]
    viewer = staff_session(db, VIEWER, "viewer@rrc.com", "viewer")
    staff = staff_session(db, STAFF, "staff@rrc.com", "staff")
    manager = staff_session(db, MANAGER, "manager@rrc.com", "manager")
    points = f"/api/v1/admin/users/{MEMBER_ID}/points"

    # Viewer: can look, can't change anything
    assert c.get("/api/v1/admin/users", headers=viewer).status_code == 200
    assert c.put(f"/api/v1/admin/users/{MEMBER_ID}", headers=viewer, json={"city": "X"}).status_code == 403
    # Staff: day-to-day work, but no points changes, settings, deletions or activity log
    assert c.put(f"/api/v1/admin/users/{MEMBER_ID}", headers=staff, json={"city": "Perth"}).status_code == 200
    r = c.put(points, headers=staff, json={"new_points": 99999, "reason": "x"})
    assert r.status_code == 403 and "access level" in r.json()["detail"]
    assert c.put("/api/v1/content/welcome_points", headers=staff, json={"value": "5000"}).status_code == 403
    assert c.delete(f"/api/v1/admin/users/{MEMBER_ID}", headers=staff).status_code == 403
    assert c.get("/api/v1/admin/activity", headers=staff).status_code == 403
    # Manager: everything except staff access
    assert c.get("/api/v1/admin/activity", headers=manager).status_code == 200
    assert c.get("/api/v1/admin/staff", headers=manager).status_code == 403
    # What the admin site is told about the signed-in person
    me = c.get("/api/v1/admin/me", headers=staff).json()
    assert me["role"] == "staff" and "points.adjust" not in me["permissions"] and "events.manage" in me["permissions"]
    assert c.get("/api/v1/admin/me", headers=env["admin"]).json()["role"] == "owner"  # admins from before roles


def test_every_admin_endpoint_has_an_access_rule(env):
    from app.api.routes import admin, content, staff
    from app.core import permissions
    from app.core.auth_middleware import get_current_admin
    found = set()
    for router, prefix in ((admin.router, "/api/v1/admin"), (staff.router, "/api/v1/admin"),
                           (content.router, "/api/v1/content")):
        for r in router.routes:
            if router is content.router and not any(d.call is get_current_admin for d in r.dependant.dependencies):
                continue  # public content
            found.update((m, prefix + r.path) for m in r.methods)
    # Admin endpoints without a rule are refused for everyone, so this keeps the table complete
    assert len(found) > 40
    assert found == set(permissions.ROUTES), (sorted(found - set(permissions.ROUTES)), sorted(set(permissions.ROUTES) - found))


def test_admin_changes_are_in_the_activity_log(env, mail):
    db, c = env["db"], env["c"]
    before = len(db.tables["audit_log"])
    r = c.put(f"/api/v1/admin/users/{MEMBER_ID}/points", headers={**env["admin"], "User-Agent": "TestBrowser"},
              json={"new_points": 2300, "reason": "Event bonus"})
    assert r.status_code == 200
    row = db.tables["audit_log"][-1]
    assert len(db.tables["audit_log"]) == before + 1
    assert row["kind"] == "admin" and row["action"] == "Changed member points" and row["actor_id"] == ADMIN_ID
    assert row["actor_email"] == "admin@rrc.com" and row["actor_role"] == "owner" and row["status"] == 200
    assert row["target"] == MEMBER_ID and row["user_agent"] == "TestBrowser"
    assert row["details"]["request"] == {"new_points": 2300, "reason": "Event bonus"}
    assert row["details"]["points_before"] != 2300 and row["details"]["points_after"] == 2300
    # Refused attempts are recorded too; looking at pages isn't
    c.get("/api/v1/admin/users", headers=env["admin"])
    assert len(db.tables["audit_log"]) == before + 1
    # Image data and passwords are never kept
    from app.services.audit_service import clean
    assert clean({"data_base64": "AAAA", "password": "x", "note": "y" * 400}) == \
        {"data_base64": "[image]", "password": "[hidden]", "note": "y" * 300 + "..."}
    # The log can be read and filtered by owners and managers
    rows = c.get("/api/v1/admin/activity", headers=env["admin"], params={"search": "points"}).json()
    assert rows and rows[0]["action"] == "Changed member points"


def test_large_points_change_alerts_the_business(env, mail):
    c = env["c"]
    c.put(f"/api/v1/admin/users/{MEMBER_ID}/points", headers=env["admin"], json={"new_points": 2400, "reason": "small"})
    assert not [m for m in mail if m["subject"].startswith("Security alert")]
    c.put(f"/api/v1/admin/users/{MEMBER_ID}/points", headers=env["admin"], json={"new_points": 9400, "reason": "big one"})
    alert = [m for m in mail if m["subject"] == "Security alert: Large points change"]
    assert alert and alert[0]["to"] == "admin@rrc.com" and "+7,000" in alert[0]["html"] and "big one" in alert[0]["html"]


def test_staff_management(env, mail):
    db, c = env["db"], env["c"]
    owner = env["admin"]
    # Give a member access as Staff
    r = c.post("/api/v1/admin/staff", headers=owner, json={"email": "old@example.com", "role": "staff"})
    assert r.status_code == 200, r.text
    old = next(u for u in db.tables["users"] if u["email"] == "old@example.com")
    assert old["is_admin"] and old["admin_role"] == "staff"
    assert any(m["subject"] == "Your admin website access" and m["to"] == "old@example.com" for m in mail)
    assert any(m["subject"] == "Security alert: Admin access given" for m in mail)
    # A brand-new staff account gets a set-password email
    r = c.post("/api/v1/admin/staff", headers=owner, json={"email": "new.staff@rrc.com", "role": "viewer",
                                                            "full_name": "Nina Staff"})
    assert r.status_code == 200
    assert next(u for u in db.tables["users"] if u["email"] == "new.staff@rrc.com")["admin_role"] == "viewer"
    listed = c.get("/api/v1/admin/staff", headers=owner).json()["staff"]
    assert {"admin@rrc.com", "old@example.com", "new.staff@rrc.com"} <= {s["email"] for s in listed}
    # Rules: not your own level, always one owner
    assert c.put(f"/api/v1/admin/staff/{ADMIN_ID}", headers=owner, json={"role": "viewer"}).status_code == 400
    assert c.delete(f"/api/v1/admin/staff/{ADMIN_ID}", headers=owner).status_code == 400
    assert c.put(f"/api/v1/admin/staff/{old['id']}", headers=owner, json={"role": "boss"}).status_code == 400
    assert c.put(f"/api/v1/admin/staff/{old['id']}", headers=owner, json={"role": "manager"}).status_code == 200
    assert old["admin_role"] == "manager"
    # Lost phone: two-step reset removes the authenticator link and signs them out
    db.auth.admin.mfa.factors[old["id"]] = ["factor-1"]
    assert c.post(f"/api/v1/admin/staff/{old['id']}/reset-two-step", headers=owner).status_code == 200
    assert db.auth.admin.mfa.factors[old["id"]] == [] and old["signed_out_at"]
    # Removing access
    assert c.delete(f"/api/v1/admin/staff/{old['id']}", headers=owner).status_code == 200
    assert not old["is_admin"] and old["admin_role"] is None
    actions = [r["action"] for r in db.tables["audit_log"]]
    assert {"Gave admin access", "Changed staff access level", "Reset staff two-step sign-in",
            "Removed admin access"} <= set(actions)


def test_sign_out_everywhere(env, monkeypatch):
    from app.core import auth_middleware
    c = env["c"]
    real = time.time
    monkeypatch.setattr(auth_middleware.time, "time", lambda: real() - 30)
    from app.core.auth_middleware import issue_app_token
    old_phone = {"Authorization": f"Bearer {issue_app_token(MEMBER_ID, 'manoj@example.com')}"}
    monkeypatch.setattr(auth_middleware.time, "time", real)
    assert c.get("/api/v1/auth/me", headers=old_phone).status_code == 200
    # The member signs out everywhere from this phone: this phone gets a fresh token
    fresh = c.post("/api/v1/auth/sign-out-everywhere", headers=old_phone)
    assert fresh.status_code == 200
    r = c.get("/api/v1/auth/me", headers=old_phone)
    assert r.status_code == 401 and "signed out" in r.json()["detail"]
    assert c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {fresh.json()['access_token']}"}).status_code == 200
    # Staff can do it for a member too (e.g. a lost phone)
    assert c.post(f"/api/v1/admin/users/{MEMBER_ID}/sign-out-everywhere", headers=env["admin"]).status_code == 200


def test_new_sign_in_email_and_lockout_alert(env, mail):
    from app.core import login_guard
    from app.api.routes.auth import limiter
    db, c = env["db"], env["c"]
    login_guard.reset_all(); limiter.reset()
    db.auth.accounts["manoj@example.com"] = ("Manoj-Pass-88", MEMBER_ID, "Manoj Kumar")
    assert c.post("/api/v1/auth/login", json={"email": "manoj@example.com", "password": "Manoj-Pass-88"}).status_code == 200
    mine = [m for m in mail if m["subject"] == "New sign-in to your account"]
    assert mine and mine[-1]["to"] == "manoj@example.com" and "Email and password" in mine[-1]["html"]
    # The app's automatic renewal doesn't send it
    n = len(mail)
    c.post("/api/v1/auth/refresh", headers=env["member"])
    assert len(mail) == n
    # Five wrong passwords: locked, logged and the business alerted
    for _ in range(5):
        c.post("/api/v1/auth/login", json={"email": "manoj@example.com", "password": "wrong-guess"})
    assert any(r["action"] == "Sign-in locked after repeated wrong passwords" and r["target"] == "manoj@example.com"
               for r in db.tables["audit_log"])
    assert any(m["subject"] == "Security alert: Repeated wrong passwords" for m in mail)
    login_guard.reset_all(); limiter.reset()


def test_security_settings_are_not_public(env):
    db, c = env["db"], env["c"]
    db.tables["app_content"].append({"key": "security_alert_email", "value": "owner@rrc.com"})
    assert "security_alert_email" not in c.get("/api/v1/content").json()
    db.tables["app_content"].pop()
