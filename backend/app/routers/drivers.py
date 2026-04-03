from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models.driver import Driver

router = APIRouter(prefix="/api/drivers", tags=["drivers"])


@router.get("")
def list_drivers(search: Optional[str] = None, limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    q = db.query(Driver)
    if search:
        s = f"%{search}%"
        q = q.filter((Driver.name.ilike(s)) | (Driver.email.ilike(s)) | (Driver.department.ilike(s)))
    rows = q.order_by(Driver.name).limit(limit).all()
    return [{"id": d.id, "name": d.name, "email": d.email, "phone": d.phone, "department": d.department, "role": d.role} for d in rows]


@router.post("")
def create_driver(data: dict, db: Session = Depends(get_db)):
    d = Driver(**{k: v for k, v in data.items() if hasattr(Driver, k)})
    db.add(d)
    db.commit()
    db.refresh(d)
    return {"id": d.id, "name": d.name, "email": d.email}


@router.put("/{driver_id}")
def update_driver(driver_id: int, data: dict, db: Session = Depends(get_db)):
    d = db.query(Driver).filter(Driver.id == driver_id).first()
    if not d:
        raise HTTPException(404, "Driver not found")
    for k, v in data.items():
        if hasattr(d, k) and k != "id":
            setattr(d, k, v)
    db.commit()
    db.refresh(d)
    return {"id": d.id, "name": d.name, "email": d.email}
