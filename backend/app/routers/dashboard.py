from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.vehicle import Vehicle
from app.models.driver import Driver
from app.models.assignment import Assignment

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    total = db.query(Vehicle).count()
    active = db.query(Vehicle).filter(Vehicle.status == "active").count()
    returned = db.query(Vehicle).filter(Vehicle.status == "returned").count()

    by_category = dict(
        db.query(Vehicle.category, func.count(Vehicle.id))
        .group_by(Vehicle.category)
        .all()
    )
    by_status = dict(
        db.query(Vehicle.status, func.count(Vehicle.id))
        .group_by(Vehicle.status)
        .all()
    )
    total_drivers = db.query(Driver).count()
    active_assignments = db.query(Assignment).filter(Assignment.is_active == True).count()

    return {
        "total_vehicles": total,
        "active_vehicles": active,
        "returned_vehicles": returned,
        "total_drivers": total_drivers,
        "active_assignments": active_assignments,
        "by_category": by_category,
        "by_status": by_status,
    }
