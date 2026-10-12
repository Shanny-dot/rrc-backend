from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import HTTPException
from app.api.routes import auth, events, rewards, referrals, transactions, admin, content, tiers, notifications, app_config

app = FastAPI(title="RRC Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    if request.method == "OPTIONS":
        response = JSONResponse(content={"status": "ok"}, status_code=200)
    else:
        try:
            response = await call_next(request)
        except Exception as exc:
            response = JSONResponse(content={"detail": str(exc)}, status_code=500)

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Credentials": "true"
        }
    )

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(referrals.router, prefix="/api/v1/referrals", tags=["Referrals"])
app.include_router(events.router, prefix="/api/v1/events", tags=["Events"])
app.include_router(rewards.router, prefix="/api/v1/rewards", tags=["Rewards"])
app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["Transactions"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(content.router, prefix="/api/v1/content", tags=["Content"])
app.include_router(tiers.router, prefix="/api/v1/tiers", tags=["tiers"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["notifications"])
app.include_router(app_config.router, prefix="/api/v1/app", tags=["app"])

@app.get("/health")
def health_check():
    return {"status": "ok"}
