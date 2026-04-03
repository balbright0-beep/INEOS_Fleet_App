from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models.assignment import Assignment

router = APIRouter(prefix="/api/assignments", tags=["assignments"])


@router.get("")
def list_assignments(vehicle_id: int = None, driver_id: int = None, active_only: bool = True, db: Session = Depends(get_db)):
    q = db.query(Assignment)
    if vehicle_id:
        q = q.filter(Assignment.vehicle_id == vehicle_id)
    if driver_id:
        q = q.filter(Assignment.driver_id == driver_id)
    if active_only:
        q = q.filter(Assignment.is_active == True)
    rows = q.order_by(Assignment.assigned_date.desc()).all()
    return [{"id": a.id, "vehicle_id": a.vehicle_id, "driver_id": a.driver_id, "assignment_type": a.assignment_type, "assigned_date": str(a.assigned_date) if a.assigned_date else None, "return_date": str(a.return_date) if a.return_date else None, "is_active": a.is_active} for a in rows]


@router.post("")
def create_assignment(data: dict, db: Session = Depends(get_db)):
    a = Assignment(
        vehicle_id=data["vehicle_id"],
        driver_id=data["driver_id"],
        assignment_type=data.get("assignment_type", "primary"),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "vehicle_id": a.vehicle_id, "driver_id": a.driver_id}


@router.put("/{assignment_id}/return")
def return_assignment(assignment_id: int, db: Session = Depends(get_db)):
    a = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not a:
        raise HTTPException(404, "Assignment not found")
    a.is_active = False
    a.return_date = datetime.utcnow()
    db.commit()
    return {"ok": True}
