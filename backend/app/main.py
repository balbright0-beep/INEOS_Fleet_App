import json
import os
import bcrypt
import urllib.request
import urllib.error
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from jose import jwt
from datetime import datetime, timedelta

# Config
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///fleet.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me")
ADMIN_PASSWORD = os.environ.get("ADMIN_DEFAULT_PASSWORD", "admin123")
MVRCHECK_API_KEY = os.environ.get("MVRCHECK_API_KEY", "")
MVRCHECK_API_URL = os.environ.get("MVRCHECK_API_URL", "https://api.mvrcheck.com/v1/mvr")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)


class FleetData(Base):
    __tablename__ = "fleet_data"
    id = Column(Integer, primary_key=True)
    data = Column(Text, default="{}")
    updated_at = Column(String)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if db.query(User).count() == 0:
        pw = (ADMIN_PASSWORD or "admin123").encode("utf-8")[:72]
        hashed = bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")
        db.add(User(username="admin", password_hash=hashed))
        db.commit()
    if db.query(FleetData).count() == 0:
        db.add(FleetData(id=1, data="{}", updated_at=datetime.utcnow().isoformat()))
        db.commit()
    db.close()
    yield


app = FastAPI(title="INEOS Fleet Manager", lifespan=lifespan)


@app.post("/api/login")
def login(data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.get("username")).first()
    if not user:
        raise HTTPException(401, "Invalid credentials")
    if not bcrypt.checkpw(data.get("password", "").encode("utf-8")[:72], user.password_hash.encode("utf-8")):
        raise HTTPException(401, "Invalid credentials")
    token = jwt.encode(
        {"sub": user.username, "exp": datetime.utcnow() + timedelta(hours=12)},
        JWT_SECRET, algorithm="HS256",
    )
    return {"token": token, "username": user.username}


def get_current_user(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(auth[7:], JWT_SECRET, algorithms=["HS256"])
        return payload["sub"]
    except Exception:
        raise HTTPException(401, "Invalid token")


@app.get("/api/db")
def load_data(user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(FleetData).filter(FleetData.id == 1).first()
    if not record:
        return {}
    return JSONResponse(content=json.loads(record.data or "{}"))


@app.put("/api/db")
async def save_data(request: Request, user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    body = await request.json()
    record = db.query(FleetData).filter(FleetData.id == 1).first()
    if not record:
        record = FleetData(id=1)
        db.add(record)
    record.data = json.dumps(body)
    record.updated_at = datetime.utcnow().isoformat()
    db.commit()
    return {"ok": True, "updated_at": record.updated_at}


# ===== MVRcheck integration =====
@app.post("/api/mvr/pull")
async def pull_mvr(request: Request, user: str = Depends(get_current_user)):
    """
    Pull a Motor Vehicle Report from MVRcheck.com for a given driver.
    Body: { driverName, licenseNumber, licenseState, dateOfBirth (YYYY-MM-DD) }
    Returns a normalized response: { status, fetchedAt, violations[], suspended, expirationDate, raw }
    """
    body = await request.json()
    license_number = (body.get("licenseNumber") or "").strip()
    license_state = (body.get("licenseState") or "").strip().upper()
    dob = (body.get("dateOfBirth") or "").strip()
    driver_name = (body.get("driverName") or "").strip()

    if not license_number or not license_state or not dob:
        raise HTTPException(400, "licenseNumber, licenseState, and dateOfBirth are required")

    if not MVRCHECK_API_KEY:
        # Mock mode for development — returns a synthetic clean record
        return {
            "status": "MOCK",
            "fetchedAt": datetime.utcnow().isoformat() + "Z",
            "driverName": driver_name,
            "licenseNumber": license_number,
            "licenseState": license_state,
            "licenseStatus": "VALID",
            "expirationDate": "2028-01-15",
            "violations": [],
            "suspensions": [],
            "totalPoints": 0,
            "mock": True,
            "note": "MVRCHECK_API_KEY not set — returning synthetic clean record. Set the env var on Render to enable real pulls."
        }

    # Real MVRcheck API call
    payload = {
        "license_number": license_number,
        "license_state": license_state,
        "date_of_birth": dob,
        "first_name": driver_name.split(" ")[0] if driver_name else "",
        "last_name": " ".join(driver_name.split(" ")[1:]) if driver_name and " " in driver_name else "",
    }
    req = urllib.request.Request(
        MVRCHECK_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {MVRCHECK_API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise HTTPException(e.code, f"MVRcheck error: {detail}")
    except Exception as e:
        raise HTTPException(502, f"MVRcheck request failed: {e}")

    # Normalize MVRcheck response (field names may vary by provider tier)
    violations = raw.get("violations") or raw.get("convictions") or []
    suspensions = raw.get("suspensions") or []
    return {
        "status": raw.get("status", "OK"),
        "fetchedAt": datetime.utcnow().isoformat() + "Z",
        "driverName": driver_name,
        "licenseNumber": license_number,
        "licenseState": license_state,
        "licenseStatus": raw.get("license_status", "UNKNOWN"),
        "expirationDate": raw.get("expiration_date"),
        "violations": violations,
        "suspensions": suspensions,
        "totalPoints": raw.get("total_points", 0),
        "raw": raw,
    }


# Serve static files (Fleet Manager HTML) — must be last
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
