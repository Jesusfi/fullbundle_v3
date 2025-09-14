
import os, logging, logging.handlers, time, datetime as dt
from typing import Optional, List, Literal

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from pydantic import BaseModel, Field
from dotenv import load_dotenv
import jwt

from database import Base, engine, SessionLocal
from models import User, Holding, Assumptions, PriceCache, Projection, ProjectionPoint
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.pricing import fetch_price_for, ProviderError
from services.projection import run_projection_for_user

# ---------- Config & Logging ----------
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
DB_PATH = os.getenv("DB_PATH", "./data.db")
LOG_PATH = os.getenv("LOG_PATH", "./logs/app.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
CORS_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:9000,http://127.0.0.1:9000").split(",") if x.strip()]

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logger = logging.getLogger("app")
logger.setLevel(LOG_LEVEL)
fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
handler = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=5_000_000, backupCount=5)
handler.setFormatter(fmt)
logger.addHandler(handler)

# ---------- FastAPI ----------
app = FastAPI(title="Millionaire Tracker Full Bundle v3", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

# Serve front-end at /app/
app.mount("/app", StaticFiles(directory="frontend", html=True), name="frontend")

@app.get("/")
def root():
    # Redirect to app, keep /docs available
    return RedirectResponse(url="/app/")

bearer = HTTPBearer(auto_error=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- Auth (username only) ----------
class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)

class TokenOut(BaseModel):
    token: str

def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60*60*24*30
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def get_current_user(db: Session = Depends(get_db), cred: HTTPAuthorizationCredentials = Depends(bearer)) -> User:
    if cred is None:
        raise HTTPException(status_code=401, detail="Missing auth")
    try:
        payload = jwt.decode(cred.credentials, SECRET_KEY, algorithms=["HS256"])
        username = payload.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.scalar(select(User).where(User.username == username))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@app.post("/auth/login", response_model=TokenOut)
def login(inb: LoginIn, db: Session = Depends(get_db)):
    username = inb.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username required")
    user = db.scalar(select(User).where(User.username == username))
    if not user:
        user = User(username=username)
        db.add(user); db.commit(); db.refresh(user)
        db.add(Assumptions(user_id=user.id)); db.commit()
    token = create_token(username)
    logger.info(f"login user={username}")
    return TokenOut(token=token)

# ---------- Schemas ----------
class AssumptionsIn(BaseModel):
    target: float = 1_000_000
    basis: int = 365
    default_cagr: float = 7.0
    monthly_contrib: float = 0.0
    cash_apy: float = 4.5
    price_provider: Literal["none","yahoo","stooq","alphavantage"] = "none"
    alpha_key: Optional[str] = ""

class AssumptionsOut(AssumptionsIn):
    updated_at: dt.datetime

class HoldingIn(BaseModel):
    type: Literal["cash","ticker","cagr"]
    name: str
    units: float = 0.0
    price: float = 0.0
    cagr: float = 7.0
    monthly_contrib: float = 0.0

class HoldingOut(HoldingIn):
    id: int
    updated_at: dt.datetime

class PriceRefreshOut(BaseModel):
    updated: int
    failed: int

class ProjectionOut(BaseModel):
    run_at: dt.datetime
    start_total: float
    target: float
    basis: int
    millionaire_date: Optional[dt.datetime]
    days_to_target: Optional[int]
    checkpoints: list[tuple[int, float]]
    table: list[tuple[str, float]]   # <- add this line

# ---------- Assumptions ----------
from fastapi import Depends
@app.get("/assumptions", response_model=AssumptionsOut)
def get_assumptions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asm = db.scalar(select(Assumptions).where(Assumptions.user_id == user.id))
    return AssumptionsOut(
        target=asm.target, basis=asm.basis, default_cagr=asm.default_cagr,
        monthly_contrib=asm.monthly_contrib, cash_apy=asm.cash_apy,
        price_provider=asm.price_provider, alpha_key=asm.alpha_key or "",
        updated_at=asm.updated_at
    )

@app.put("/assumptions", response_model=AssumptionsOut)
def update_assumptions(inb: AssumptionsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asm = db.scalar(select(Assumptions).where(Assumptions.user_id == user.id))
    for k,v in inb.model_dump().items():
        setattr(asm, k if k != "default_cagr" else "default_cagr", v)
    asm.updated_at = dt.datetime.utcnow()
    db.add(asm); db.commit(); db.refresh(asm)
    logger.info(f"assumptions.update user={user.username}")
    return get_assumptions(user, db)

# ---------- Holdings ----------
@app.get("/holdings", response_model=List[HoldingOut])
def list_holdings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Holding).where(Holding.user_id == user.id).order_by(Holding.id)).all()
    return [HoldingOut(id=r.id, type=r.type, name=r.name, units=r.units, price=r.price, cagr=r.cagr, monthly_contrib=r.monthly_contrib, updated_at=r.updated_at) for r in rows]

@app.post("/holdings", response_model=HoldingOut)
def create_holding(inb: HoldingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    h = Holding(user_id=user.id, **inb.model_dump())
    db.add(h); db.commit(); db.refresh(h)
    logger.info(f"holding.create user={user.username} name={h.name} type={h.type}")
    return HoldingOut(id=h.id, type=h.type, name=h.name, units=h.units, price=h.price, cagr=h.cagr, monthly_contrib=h.monthly_contrib, updated_at=h.updated_at)

@app.put("/holdings/{hid}", response_model=HoldingOut)
def update_holding(hid: int, inb: HoldingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    h = db.get(Holding, hid)
    if not h or h.user_id != user.id: raise HTTPException(404)
    for k,v in inb.model_dump().items(): setattr(h, k, v)
    h.updated_at = dt.datetime.utcnow()
    db.add(h); db.commit(); db.refresh(h)
    logger.info(f"holding.update user={user.username} id={h.id}")
    return HoldingOut(id=h.id, type=h.type, name=h.name, units=h.units, price=h.price, cagr=h.cagr, monthly_contrib=h.monthly_contrib, updated_at=h.updated_at)

@app.delete("/holdings/{hid}")
def delete_holding(hid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    h = db.get(Holding, hid)
    if not h or h.user_id != user.id: raise HTTPException(404)
    db.delete(h); db.commit()
    logger.info(f"holding.delete user={user.username} id={hid}")
    return {"ok": True}

# ---------- Prices ----------
@app.post("/prices/refresh", response_model=PriceRefreshOut)
def refresh_prices(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asm = db.scalar(select(Assumptions).where(Assumptions.user_id == user.id))
    if asm.price_provider == "none":
        raise HTTPException(400, "No price provider configured")
    tickers = [h.name.upper() for h in db.scalars(select(Holding).where(Holding.user_id == user.id, Holding.type == "ticker")).all()]
    tickers = sorted(set(tickers))
    ok = 0; fail = 0
    for t in tickers:
        try:
            px, src = fetch_price_for(t, asm.price_provider, asm.alpha_key or os.getenv("ALPHA_VANTAGE_KEY",""))
            existing = db.scalar(select(PriceCache).where(PriceCache.user_id == user.id, PriceCache.ticker == t))
            ts = dt.datetime.utcnow()
            if existing:
                existing.price = px; existing.ts = ts; existing.source = src
                db.add(existing)
            else:
                db.add(PriceCache(user_id=user.id, ticker=t, price=px, ts=ts, source=src))
            db.commit()
            ok += 1
        except ProviderError as e:
            logger.warning(f"price.fail user={user.username} t={t} err={e}")
            fail += 1
    logger.info(f"price.refresh user={user.username} ok={ok} fail={fail}")
    return PriceRefreshOut(updated=ok, failed=fail)

# ---------- Projections ----------
@app.post("/projections/run", response_model=ProjectionOut)
def run_projection(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = run_projection_for_user(user, db)
    logger.info(f"projection.run user={user.username} days={out['days_to_target']} start={out['start_total']:.2f}")
    return ProjectionOut(**out)

@app.get("/projections/latest", response_model=ProjectionOut)
def latest_projection(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.scalar(select(Projection).where(Projection.user_id == user.id).order_by(Projection.id.desc()))
    if not p: raise HTTPException(404, "No projections yet")
    pts = db.scalars(select(ProjectionPoint).where(ProjectionPoint.projection_id == p.id).order_by(ProjectionPoint.day)).all()
    return ProjectionOut(
        run_at=p.run_at, start_total=p.start_total, target=p.target, basis=p.basis,
        millionaire_date=p.millionaire_date, days_to_target=p.days_to_target,
        checkpoints=[(pt.day, pt.total) for pt in pts if pt.day in (0,30,90,180,365,730,1095)]
    )
