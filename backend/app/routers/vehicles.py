from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models.vehicle import Vehicle

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


@router.get("")
def list_vehicles(
    search: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Vehicle)
    if search:
        s = f"%{search}%"
        q = q.filter(
            (Vehicle.vin.ilike(s)) | (Vehicle.dealer_name.ilike(s))
            | (Vehicle.location_city.ilike(s)) | (Vehicle.trim.ilike(s))
            | (Vehicle.plate_number.ilike(s)) | (Vehicle.notes.ilike(s))
        )
    if category:
        q = q.filter(Vehicle.category == category)
    if status:
        q = q.filter(Vehicle.status == status)
    if state:
        q = q.filter(Vehicle.location_state == state)
    total = q.count()
    rows = q.order_by(Vehicle.updated_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [_to_dict(v) for v in rows],
    }


@router.get("/{vehicle_id}")
def get_vehicle(vehicle_id: int, db: Session = Depends(get_db)):
    v = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not v:
        raise HTTPException(404, "Vehicle not found")
    return _to_dict(v)


@router.post("")
def create_vehicle(data: dict, db: Session = Depends(get_db)):
    v = Vehicle(**{k: v for k, v in data.items() if hasattr(Vehicle, k)})
    db.add(v)
    db.commit()
    db.refresh(v)
    return _to_dict(v)


@router.put("/{vehicle_id}")
def update_vehicle(vehicle_id: int, data: dict, db: Session = Depends(get_db)):
    v = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not v:
        raise HTTPException(404, "Vehicle not found")
    for k, val in data.items():
        if hasattr(v, k) and k != "id":
            setattr(v, k, val)
    db.commit()
    db.refresh(v)
    return _to_dict(v)


@router.delete("/{vehicle_id}")
def delete_vehicle(vehicle_id: int, db: Session = Depends(get_db)):
    v = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not v:
        raise HTTPException(404, "Vehicle not found")
    v.status = "returned"
    db.commit()
    return {"ok": True}


def _to_dict(v):
    return {
        "id": v.id, "vin": v.vin, "year": v.year, "model": v.model,
        "body_style": v.body_style, "trim": v.trim, "color": v.color,
        "ext_color": v.ext_color, "category": v.category, "status": v.status,
        "location_city": v.location_city, "location_state": v.location_state,
        "dealer_name": v.dealer_name, "plate_number": v.plate_number,
        "mileage": v.mileage, "notes": v.notes,
        "created_at": str(v.created_at) if v.created_at else None,
        "updated_at": str(v.updated_at) if v.updated_at else None,
    }
