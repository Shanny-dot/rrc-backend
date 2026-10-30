"""Staff access, the activity log and account sign-outs (admin site, security phase 2).

Mounted under /api/v1/admin. Who may use each endpoint is set in app/core/permissions.py.
"""
import datetime
import secrets

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.core import permissions
from app.core.auth_middleware import get_current_admin
from app.core.supabase_client import supabase_admin
from app.services import audit_service
from app.services.email_service import EmailService, _site

router = APIRouter(dependencies=[Depends(get_current_admin)])

STAFF_COLUMNS = "id, full_name, email, is_admin, admin_role, deleted_at, created_at"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _two_step_factors(user_id: str):
    """The staff member's authenticator-app links, or None if Supabase can't be asked."""
    try:
        resp = supabase_admin.auth.admin.mfa.list_factors({"user_id": user_id})
        return [f for f in (getattr(resp, "factors", None) or []) if getattr(f, "status", "") == "verified"]
    except Exception as e:
        print(f"Two-step factor lookup failed: {e}")
        return None


def _staff_row(id: str) -> dict:
    rows = supabase_admin.table("users").select(STAFF_COLUMNS).eq("id", id).execute().data or []
    if not rows or not rows[0].get("is_admin"):
        raise HTTPException(status_code=404, detail="That person doesn't have admin access.")
    return rows[0]


def _owners() -> list:
    rows = supabase_admin.table("users").select(STAFF_COLUMNS).eq("is_admin", True).execute().data or []
    return [r for r in rows if not r.get("deleted_at") and permissions.role_of(r) == permissions.OWNER]


def _check_role(role: str) -> str:
    if role not in permissions.ROLES:
        raise HTTPException(status_code=400, detail="Choose Owner, Manager, Staff or Viewer.")
    return role


def _alert(action: str, admin: dict, person: dict, extra: list = ()):
    audit_service.alert(action, [
        ("Person", f"{person.get('full_name') or ''} ({person.get('email')})"),
        *extra, ("Done by", f"{admin.get('email')} ({admin.get('admin_role')})"),
    ], "If you didn't expect this change, check the Staff page and the Activity log.", key=str(person.get("id")))


@router.get("/me")
def who_am_i(admin: dict = Depends(get_current_admin)):
    """The signed-in staff member's access level, so the admin site shows only what they can use."""
    role = admin.get("admin_role")
    return {"id": admin.get("sub"), "email": admin.get("email"), "role": role,
            "role_label": permissions.ROLE_LABELS.get(role), "permissions": permissions.permissions_for(role)}


@router.get("/staff")
def list_staff():
    rows = supabase_admin.table("users").select(STAFF_COLUMNS).eq("is_admin", True).execute().data or []
    out = []
    for r in rows:
        if r.get("deleted_at"):
            continue
        factors = _two_step_factors(r["id"])
        out.append({**r, "admin_role": permissions.role_of(r),
                    "two_step": None if factors is None else bool(factors)})
    return {"staff": sorted(out, key=lambda r: (permissions.ROLES.index(r["admin_role"]), r.get("email") or "")),
            "roles": [{"value": k, "label": v} for k, v in permissions.ROLE_LABELS.items()]}


@router.post("/staff")
def add_staff(email: str = Body(..., embed=True), role: str = Body(..., embed=True),
              full_name: str = Body("", embed=True), admin: dict = Depends(get_current_admin)):
    """Gives someone access to the admin site. An existing account (e.g. a member) keeps its
    password; otherwise a staff account is created and they get an email to choose a password."""
    email = (email or "").strip().lower()
    _check_role(role)
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    rows = supabase_admin.table("users").select(STAFF_COLUMNS).eq("email", email).execute().data or []
    live = [r for r in rows if not r.get("deleted_at")]
    link = None
    if live:
        person = live[0]
        if person.get("is_admin"):
            raise HTTPException(status_code=400, detail="This person already has admin access. Change their level instead.")
        supabase_admin.table("users").update({"is_admin": True, "admin_role": role}).eq("id", person["id"]).execute()
    elif rows:
        raise HTTPException(status_code=400, detail="This email belongs to a closed account. Restore it on the Users page first.")
    else:
        try:
            login = supabase_admin.auth.admin.create_user({
                "email": email, "password": secrets.token_urlsafe(24), "email_confirm": True,
                "user_metadata": {"full_name": full_name.strip()},
            }).user
        except Exception as e:
            print(f"Staff account create failed: {e}")
            raise HTTPException(status_code=400, detail="An account with this email already exists but has no "
                                                        "profile. Please contact your developer.")
        from app.api.routes.auth import generate_referral_code
        person = {"id": login.id, "email": email, "full_name": full_name.strip() or email.split("@")[0]}
        supabase_admin.table("users").insert({**person, "referral_code": generate_referral_code(),
                                              "is_admin": True, "admin_role": role}).execute()
        try:
            link = supabase_admin.auth.admin.generate_link({
                "type": "recovery", "email": email, "options": {"redirect_to": _site("/reset-password")}
            }).properties.action_link
        except Exception as e:
            print(f"Staff set-password link failed: {e}")
    EmailService.send_staff_access(email, person.get("full_name"), permissions.ROLE_LABELS[role], link)
    _alert("Admin access given", admin, person, [("Access level", permissions.ROLE_LABELS[role])])
    return {"message": "Access given. They've been emailed how to sign in.", "id": person["id"]}


@router.put("/staff/{id}")
def change_staff_role(id: str, role: str = Body(..., embed=True), admin: dict = Depends(get_current_admin)):
    _check_role(role)
    person = _staff_row(id)
    if id == admin.get("sub"):
        raise HTTPException(status_code=400, detail="You can't change your own access level. Ask another owner.")
    if permissions.role_of(person) == permissions.OWNER and role != permissions.OWNER and len(_owners()) <= 1:
        raise HTTPException(status_code=400, detail="There must always be at least one owner.")
    supabase_admin.table("users").update({"admin_role": role}).eq("id", id).execute()
    _alert("Staff access level changed", admin, person,
           [("From", permissions.role_of(person)), ("To", role)])
    return {"message": "Access level changed.", "id": id, "role": role}


@router.delete("/staff/{id}")
def remove_staff(id: str, admin: dict = Depends(get_current_admin)):
    person = _staff_row(id)
    if id == admin.get("sub"):
        raise HTTPException(status_code=400, detail="You can't remove your own access. Ask another owner.")
    if permissions.role_of(person) == permissions.OWNER and len(_owners()) <= 1:
        raise HTTPException(status_code=400, detail="There must always be at least one owner.")
    # Access removed and every signed-in session ends now
    supabase_admin.table("users").update({"is_admin": False, "admin_role": None, "signed_out_at": _now_iso()}) \
        .eq("id", id).execute()
    _alert("Admin access removed", admin, person)
    return {"message": "Admin access removed.", "id": id}


@router.post("/staff/{id}/reset-two-step")
def reset_two_step(id: str, admin: dict = Depends(get_current_admin)):
    """For a lost or replaced phone: removes their authenticator link so they set it up again
    at their next sign-in, and signs them out everywhere."""
    person = _staff_row(id)
    factors = _two_step_factors(id)
    if factors is None:
        raise HTTPException(status_code=503, detail="Couldn't reach the sign-in service. Please try again.")
    for f in factors:
        supabase_admin.auth.admin.mfa.delete_factor({"id": f.id, "user_id": id})
    supabase_admin.table("users").update({"signed_out_at": _now_iso()}).eq("id", id).execute()
    _alert("Staff two-step sign-in reset", admin, person)
    return {"message": "Done. They'll set up their authenticator app again at their next sign-in.", "id": id}


@router.post("/users/{id}/sign-out-everywhere")
def sign_member_out(id: str):
    """Ends every signed-in session of a member (e.g. a lost phone or a suspected break-in)."""
    rows = supabase_admin.table("users").select("id").eq("id", id).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    supabase_admin.table("users").update({"signed_out_at": _now_iso()}).eq("id", id).execute()
    return {"message": "Signed out of all devices. They'll need to sign in again.", "id": id}


@router.get("/activity")
def activity_log(kind: str = None, actor: str = None, search: str = None, since: str = None,
                 until: str = None, limit: int = 200):
    """The activity log, newest first. kind: admin | security; actor: staff email (part of);
    search: words in the action or target; since/until: YYYY-MM-DD (inclusive)."""
    q = supabase_admin.table("audit_log").select("*")
    if kind in ("admin", "security"):
        q = q.eq("kind", kind)
    if actor:
        q = q.ilike("actor_email", f"%{actor.strip()}%")
    if since:
        q = q.gte("at", f"{since}T00:00:00+00:00")
    if until:
        q = q.lte("at", f"{until}T23:59:59+00:00")
    rows = q.order("at", desc=True).limit(max(1, min(limit, 1000))).execute().data or []
    if search:
        s = search.strip().lower()
        rows = [r for r in rows if s in (r.get("action") or "").lower() or s in (r.get("target") or "").lower()
                or s in str(r.get("details") or "").lower()]
    return rows
