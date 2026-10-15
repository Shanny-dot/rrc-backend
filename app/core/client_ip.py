from fastapi import Request


def client_ip(request: Request) -> str:
    """The caller's real address on Render.

    Render's proxy only appends to X-Forwarded-For, so its first entry (which uvicorn
    reports as request.client.host) can be set by the caller. Render's Cloudflare edge
    sets CF-Connecting-IP / True-Client-IP itself, so those are used first. Used for rate
    limits and invite-link matching."""
    for header in ("cf-connecting-ip", "true-client-ip"):
        value = request.headers.get(header, "").strip()
        if value:
            return value
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if forwarded:
        return forwarded[-1]
    return request.client.host if request.client else ""
