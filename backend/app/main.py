import json
import os
import bcrypt
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


# Serve static files (Fleet Manager HTML) — must be last
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
