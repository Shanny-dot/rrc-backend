from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import auth, events, rewards, referrals, transactions, admin

app = FastAPI(title="RRC Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to FRONTEND_URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(referrals.router, prefix="/api/v1/referrals", tags=["Referrals"])
app.include_router(events.router, prefix="/api/v1/events", tags=["Events"])
app.include_router(rewards.router, prefix="/api/v1/rewards", tags=["Rewards"])
app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["Transactions"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])

@app.get("/health")
def health_check():
    return {"status": "ok"}
