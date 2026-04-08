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
MVRCHECK_API_KEY = os.environ.get("MVRCHECK_API_KEY", "")
MVRCHECK_API_URL = os.environ.get("MVRCHECK_API_URL", "https://api.mvrcheck.com/v1/mvr")
# Shared auth — login is delegated to the INEOS Americas Platform so all
# Hub-connected apps share the same accounts. The Platform is the ONLY source
# of truth for users; the Fleet App holds no local user table.
PLATFORM_AUTH_URL = os.environ.get(
    "PLATFORM_AUTH_URL",
    "https://ineos-americas-platform.onrender.com/api/auth/login",
)
PLATFORM_ME_URL = os.environ.get(
    "PLATFORM_ME_URL",
    "https://ineos-americas-platform.onrender.com/api/auth/me",
)
PLATFORM_BASE_URL = os.environ.get(
    "PLATFORM_BASE_URL",
    "https://ineos-americas-platform.onrender.com",
)
# Local fallback is OFF by default. Set ALLOW_LOCAL_FALLBACK=true on Render
# only as an emergency break-glass when the Platform is hard-down — and even
# then you must set EMERGENCY_ADMIN_PASSWORD as a separate env var to seed a
# temporary admin row, since no user is seeded by default.
ALLOW_LOCAL_FALLBACK = os.environ.get("ALLOW_LOCAL_FALLBACK", "false").lower() == "true"
EMERGENCY_ADMIN_PASSWORD = os.environ.get("EMERGENCY_ADMIN_PASSWORD", "")

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
    # Wipe any historical local users — Fleet App no longer holds its own
    # user table. The Platform is the only source of truth.
    if not (ALLOW_LOCAL_FALLBACK and EMERGENCY_ADMIN_PASSWORD):
        db.query(User).delete()
        db.commit()
    elif db.query(User).count() == 0:
        # Emergency-only seed: explicit env vars must both be set
        pw = EMERGENCY_ADMIN_PASSWORD.encode("utf-8")[:72]
        hashed = bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")
        db.add(User(username="emergency-admin", password_hash=hashed))
        db.commit()
        print("[auth] WARNING: emergency-admin user seeded — disable ALLOW_LOCAL_FALLBACK as soon as the Platform is reachable")
    if db.query(FleetData).count() == 0:
        db.add(FleetData(id=1, data="{}", updated_at=datetime.utcnow().isoformat()))
        db.commit()
    db.close()
    yield


app = FastAPI(title="INEOS Fleet Manager", lifespan=lifespan)


def _local_login(data: dict, db: Session):
    """Fallback: authenticate against the local users table (admin seed only)."""
    user = db.query(User).filter(User.username == data.get("username")).first()
    if not user:
        return None
    if not bcrypt.checkpw(data.get("password", "").encode("utf-8")[:72], user.password_hash.encode("utf-8")):
        return None
    token = jwt.encode(
        {"sub": user.username, "exp": datetime.utcnow() + timedelta(hours=12), "src": "local"},
        JWT_SECRET, algorithm="HS256",
    )
    return {"token": token, "username": user.username, "role": "admin", "source": "local"}


def _platform_login(data: dict):
    """Authenticate against the INEOS Americas Platform (the Hub's auth source)."""
    payload = json.dumps({
        "username": data.get("username", ""),
        "password": data.get("password", ""),
    }).encode("utf-8")
    req = urllib.request.Request(
        PLATFORM_AUTH_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        # Platform returns { token, username, role, dealer_name }
        body["source"] = "platform"
        return body
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return None
        raise HTTPException(502, f"Platform auth error ({e.code})")
    except Exception as e:
        # Network failure / DNS / timeout — caller decides whether to fall back
        raise HTTPException(503, f"Platform auth unreachable: {e}")


@app.post("/api/login")
def login(data: dict, db: Session = Depends(get_db)):
    """
    Authentication is delegated to the INEOS Americas Platform — the same
    user database that powers every Hub-connected app. The Fleet App holds
    no users of its own. If the Platform is unreachable, login fails with a
    503 unless ALLOW_LOCAL_FALLBACK + EMERGENCY_ADMIN_PASSWORD are both set
    on Render (break-glass only).
    """
    if not data.get("username") or not data.get("password"):
        raise HTTPException(400, "Username and password required")

    try:
        result = _platform_login(data)
        if result:
            return result
        # Platform answered 401 — credentials are wrong. Do NOT fall back.
        raise HTTPException(401, "Invalid credentials")
    except HTTPException as he:
        # Platform unreachable (503) and break-glass enabled
        if he.status_code == 503 and ALLOW_LOCAL_FALLBACK:
            local = _local_login(data, db)
            if local:
                return local
            raise HTTPException(503, "Platform unreachable and emergency credentials don't match")
        if he.status_code == 503:
            raise HTTPException(503, "Sign-in service is temporarily unavailable. Please try again in a moment.")
        raise


# Tiny in-memory cache for Platform token validations to avoid hammering it
_token_cache: dict = {}  # token -> (username, expires_at_epoch)
_TOKEN_CACHE_TTL = 300   # seconds


def _validate_via_platform(token: str):
    """Ask the Platform whether a token is valid. Cached for 5 minutes."""
    now = datetime.utcnow().timestamp()
    cached = _token_cache.get(token)
    if cached and cached[1] > now:
        return cached[0]
    req = urllib.request.Request(
        PLATFORM_ME_URL,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        username = body.get("username") or body.get("sub") or "unknown"
        _token_cache[token] = (username, now + _TOKEN_CACHE_TTL)
        return username
    except Exception:
        return None


def get_current_user(request: Request):
    """
    Validate the JWT. The Platform is the source of truth — we ask
    /api/auth/me (cached 5 min) for every token. The only exception is a
    locally-issued emergency token (src=local), which we accept by decoding
    with our own secret, but only when ALLOW_LOCAL_FALLBACK is enabled.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = auth[7:]
    # 1. Try local decode — only honored for emergency-mode tokens
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if payload.get("src") == "local":
            if not ALLOW_LOCAL_FALLBACK:
                raise HTTPException(401, "Local token rejected (fallback disabled)")
            return payload.get("sub") or "unknown"
        # Fleet-signed but not flagged local (e.g. JWT_SECRET shared with Platform)
        return payload.get("sub") or payload.get("username") or "unknown"
    except HTTPException:
        raise
    except Exception:
        pass
    # 2. Fall back to Platform validation
    user = _validate_via_platform(token)
    if user:
        return user
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


# ===== User Management (proxied to Platform admin API) =====
def _proxy_platform_request(method: str, path: str, request: Request, body: dict | None = None):
    """
    Forward a request to the Platform backend, carrying the caller's Authorization
    header. Used so the Fleet App can surface Platform admin endpoints without
    storing platform credentials locally.
    """
    auth = request.headers.get("Authorization", "")
    if not auth:
        raise HTTPException(401, "Not authenticated")
    url = PLATFORM_BASE_URL.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": auth, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        try:
            j = json.loads(detail)
            raise HTTPException(e.code, j.get("detail", detail))
        except json.JSONDecodeError:
            raise HTTPException(e.code, detail)
    except Exception as e:
        raise HTTPException(502, f"Platform request failed: {e}")


@app.get("/api/users")
def list_platform_users(request: Request, user: str = Depends(get_current_user)):
    return _proxy_platform_request("GET", "/api/admin/users", request)


@app.post("/api/users")
async def create_platform_user(request: Request, user: str = Depends(get_current_user)):
    body = await request.json()
    return _proxy_platform_request("POST", "/api/admin/users", request, body)


@app.delete("/api/users/{user_id}")
def delete_platform_user(user_id: int, request: Request, user: str = Depends(get_current_user)):
    return _proxy_platform_request("DELETE", f"/api/admin/users/{user_id}", request)


@app.put("/api/users/{user_id}/reset-password")
async def reset_platform_user_password(user_id: int, request: Request, user: str = Depends(get_current_user)):
    body = await request.json()
    return _proxy_platform_request("PUT", f"/api/admin/users/{user_id}/reset-password", request, body)


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
