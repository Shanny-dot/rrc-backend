from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from app.core.client_ip import client_ip
from slowapi.errors import RateLimitExceeded
from app.api.routes import auth, events, rewards, referrals, transactions, admin, content, tiers, notifications, app_config, feedback, broker, jobs

limiter = Limiter(key_func=client_ip)

app = FastAPI(title="RRC App API", description="API for Referral and Rewards Platform")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Turn unexpected errors into a JSON 500 *inside* the CORS middleware, so browsers (the admin
# site) can read the error instead of reporting a generic "Network Error".
@app.middleware("http")
async def json_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": f"Server error: {type(exc).__name__}: {exc}"[:500]})

# CORS setup (added after json_errors, so it wraps it and error responses keep CORS headers)
allowed_origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://localhost:5176",
    "https://rrc-admin.vercel.app",
    "https://admin.reliiancerewards.com.au",
    "http://admin.reliiancerewards.com.au",
    "https://reliiancerewards.com.au",
    "http://reliiancerewards.com.au",
    "https://www.reliiancerewards.com.au",
    "http://www.reliiancerewards.com.au",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https?://.*(reliiancerewards\.com\.au|vercel\.app|localhost)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check
@app.get("/health")
def health_check():
    return {"status": "ok"}

# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(events.router, prefix="/api/v1/events", tags=["events"])
app.include_router(rewards.router, prefix="/api/v1/rewards", tags=["rewards"])
app.include_router(referrals.router, prefix="/api/v1/referrals", tags=["referrals"])
app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["transactions"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(content.router, prefix="/api/v1/content", tags=["content"])
app.include_router(tiers.router, prefix="/api/v1/tiers", tags=["tiers"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["notifications"])
app.include_router(app_config.router, prefix="/api/v1/app", tags=["app"])
app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["feedback"])
app.include_router(broker.router, prefix="/api/v1/broker", tags=["broker"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
