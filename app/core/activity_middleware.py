"""Records every change made on the admin site in the activity log.

A plain ASGI middleware: it keeps a copy of the request body as the endpoint reads it and the
response status as it is sent, then writes one audit_log row for each admin request that
changes something (any method but GET/HEAD/OPTIONS). Who made it comes from get_current_admin,
which leaves the signed-in admin and a description of the action on request.state.
"""
import json

from starlette.concurrency import run_in_threadpool

from app.services import audit_service

_MAX_BODY = 64 * 1024
_READ_ONLY = {"GET", "HEAD", "OPTIONS"}


def _client_ip(scope) -> str:
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
    return (headers.get("cf-connecting-ip") or headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (scope.get("client") or ("",))[0])


class ActivityLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") in _READ_ONLY:
            return await self.app(scope, receive, send)

        body = bytearray()
        status = {"code": None}

        async def receive_and_keep():
            message = await receive()
            if message["type"] == "http.request" and len(body) < _MAX_BODY:
                body.extend(message.get("body", b"")[: _MAX_BODY - len(body)])
            return message

        async def send_and_note(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive_and_keep, send_and_note)
        finally:
            state = scope.get("state") or {}
            actor = state.get("audit_actor")
            if actor and state.get("audit_action"):
                await run_in_threadpool(self._write, scope, state, actor, bytes(body), status["code"])

    @staticmethod
    def _write(scope, state, actor, body: bytes, code):
        try:
            sent = json.loads(body) if body else None
        except ValueError:
            sent = None
        path_params = scope.get("path_params") or {}
        details = {"request": sent} if sent is not None else {}
        details.update(state.get("audit_extra") or {})
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
        audit_service.record(
            "admin", state["audit_action"], actor=actor,
            target=path_params.get("id") or path_params.get("key"),
            details=details or None, status=code or 500,
            ip=_client_ip(scope), user_agent=headers.get("user-agent"),
        )
