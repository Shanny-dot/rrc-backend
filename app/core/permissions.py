"""Staff access levels for the admin site.

Every admin endpoint is listed in ROUTES with the permission it needs and a plain description
for the activity log. An admin endpoint that isn't listed is refused (403) for everyone, so a
new endpoint can't be left open by mistake - add it here.
"""
OWNER, MANAGER, STAFF, VIEWER = "owner", "manager", "staff", "viewer"
ROLES = (OWNER, MANAGER, STAFF, VIEWER)

ROLE_LABELS = {
    OWNER: "Owner - everything, including staff access",
    MANAGER: "Manager - everything except staff access",
    STAFF: "Staff - day-to-day work, no points changes, settings or deletions",
    VIEWER: "Viewer - can look, can't change anything",
}

# What each role may do. "view" covers every read-only page except the activity log.
_STAFF = {"view", "members.edit", "events.manage", "redemptions.manage", "referrals.manage", "requests.manage"}
_MANAGER = _STAFF | {"members.delete", "members.security", "points.adjust", "rewards.manage",
                     "settings.manage", "audit.view"}
ROLE_PERMISSIONS = {
    OWNER: _MANAGER | {"staff.manage"},
    MANAGER: _MANAGER,
    STAFF: _STAFF,
    VIEWER: {"view"},
}

A = "/api/v1/admin"
# (method, route path) -> (permission, what the activity log says)
ROUTES = {
    ("GET", f"{A}/users"): ("view", None),
    ("GET", f"{A}/deleted-users"): ("view", None),
    ("GET", f"{A}/users/{{id}}"): ("view", None),
    ("PUT", f"{A}/users/{{id}}"): ("members.edit", "Edited member details"),
    ("PUT", f"{A}/users/{{id}}/points"): ("points.adjust", "Changed member points"),
    ("DELETE", f"{A}/users/{{id}}"): ("members.delete", "Closed member account"),
    ("POST", f"{A}/users/{{id}}/restore"): ("members.delete", "Restored member account"),
    ("POST", f"{A}/users/{{id}}/sign-out-everywhere"): ("members.security", "Signed member out of all devices"),
    ("POST", f"{A}/upload-image"): ("events.manage", "Uploaded an image"),
    ("GET", f"{A}/events"): ("view", None),
    ("POST", f"{A}/events"): ("events.manage", "Created event"),
    ("PUT", f"{A}/events/{{id}}"): ("events.manage", "Edited event"),
    ("DELETE", f"{A}/events/{{id}}"): ("events.manage", "Deleted event"),
    ("POST", f"{A}/events/scan-qr"): ("events.manage", "Checked in an attendee"),
    ("POST", f"{A}/events/{{id}}/thank-you"): ("events.manage", "Sent event thank-you"),
    ("POST", f"{A}/rewards"): ("rewards.manage", "Created reward"),
    ("PUT", f"{A}/rewards/{{id}}"): ("rewards.manage", "Edited reward"),
    ("DELETE", f"{A}/rewards/{{id}}"): ("rewards.manage", "Deleted reward"),
    ("GET", f"{A}/redemptions"): ("view", None),
    ("PUT", f"{A}/redemptions/{{id}}/status"): ("redemptions.manage", "Changed redemption status"),
    ("PUT", f"{A}/redemptions/{{id}}/approve"): ("redemptions.manage", "Approved redemption"),
    ("PUT", f"{A}/redemptions/{{id}}/reject"): ("redemptions.manage", "Rejected redemption (points returned)"),
    ("PUT", f"{A}/redemptions/{{id}}/sent"): ("redemptions.manage", "Marked redemption sent"),
    ("GET", f"{A}/transactions"): ("view", None),
    ("GET", f"{A}/redemption-statuses"): ("view", None),
    ("PUT", f"{A}/redemption-statuses"): ("settings.manage", "Changed redemption status messages"),
    ("GET", f"{A}/tiers"): ("view", None),
    ("PUT", f"{A}/tiers"): ("settings.manage", "Changed tiers"),
    ("GET", f"{A}/referrals"): ("view", None),
    ("PUT", f"{A}/referrals/{{id}}/stage"): ("referrals.manage", "Changed referral stage"),
    ("GET", f"{A}/feedback"): ("view", None),
    ("PUT", f"{A}/feedback/{{id}}"): ("requests.manage", "Updated feedback"),
    ("GET", f"{A}/broker-requests"): ("view", None),
    ("PUT", f"{A}/broker-requests/{{id}}"): ("requests.manage", "Updated a request"),
    ("GET", f"{A}/me"): ("view", None),
    ("GET", f"{A}/staff"): ("staff.manage", None),
    ("POST", f"{A}/staff"): ("staff.manage", "Gave admin access"),
    ("PUT", f"{A}/staff/{{id}}"): ("staff.manage", "Changed staff access level"),
    ("DELETE", f"{A}/staff/{{id}}"): ("staff.manage", "Removed admin access"),
    ("POST", f"{A}/staff/{{id}}/reset-two-step"): ("staff.manage", "Reset staff two-step sign-in"),
    ("GET", f"{A}/activity"): ("audit.view", None),
    ("GET", "/api/v1/content/all"): ("view", None),
    ("PUT", "/api/v1/content/{key}"): ("settings.manage", "Changed program settings / content"),
}


def role_of(user_row: dict) -> str:
    role = (user_row or {}).get("admin_role")
    # Admins from before roles existed keep full access until an owner changes it.
    return role if role in ROLES else OWNER


def can(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def permissions_for(role: str) -> list:
    return sorted(ROLE_PERMISSIONS.get(role, set()))
