import traceback
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from app.core.activity_middleware import ActivityLogMiddleware
from app.api.routes import auth, events, rewards, referrals, transactions, admin, content, tiers, notifications, app_config, feedback, broker, jobs, staff

app = FastAPI(title="RRC Backend API", docs_url=None, redoc_url=None, openapi_url=None)
app.state.limiter = auth.limiter

# Turn unexpected errors into a JSON 500 *inside* the CORS middleware, so browsers (the admin
# site) can read the error instead of reporting a generic "Network Error". The details stay in
# the server log under a reference; the caller only gets the reference.
@app.middleware("http")
async def json_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:  # noqa: BLE001
        ref = uuid.uuid4().hex[:8].upper()
        print(f"Server error ref {ref} on {request.method} {request.url.path}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "detail": f"Something went wrong on our side. Please try again; if it keeps happening, quote reference {ref}."})


@app.exception_handler(RateLimitExceeded)
async def too_many_requests(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Too many attempts. Please wait a minute and try again."})


# Only the admin websites may call the API from a browser (the app isn't a browser, so CORS
# doesn't apply to it). Sign-in uses bearer tokens, not cookies, so no credentials mode.
allowed_origins = [
    "https://admin.reliiancerewards.com.au",
    "https://reliiancerewards.com.au",
    "https://www.reliiancerewards.com.au",
    "https://rrc-admin.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    # Vercel previews of the admin site, and local development
    allow_origin_regex=r"https://rrc-admin(-[a-z0-9-]+)?\.vercel\.app|http://localhost(:\d+)?",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Job-Key"],
    max_age=600,
)


# Every change made on the admin site goes into the activity log (who, what, when, from where).
app.add_middleware(ActivityLogMiddleware)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(referrals.router, prefix="/api/v1/referrals", tags=["Referrals"])
app.include_router(events.router, prefix="/api/v1/events", tags=["Events"])
app.include_router(rewards.router, prefix="/api/v1/rewards", tags=["Rewards"])
app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["Transactions"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(staff.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(content.router, prefix="/api/v1/content", tags=["Content"])
app.include_router(tiers.router, prefix="/api/v1/tiers", tags=["tiers"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["notifications"])
app.include_router(app_config.router, prefix="/api/v1/app", tags=["app"])
app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["feedback"])
app.include_router(broker.router, prefix="/api/v1/broker", tags=["broker"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])

@app.get("/health")
def health_check():
    return {"status": "ok"}
