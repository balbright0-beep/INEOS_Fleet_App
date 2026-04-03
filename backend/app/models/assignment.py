from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, func
from app.database import Base


class Assignment(Base):
    __tablename__ = "assignments"
    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)
    driver_id = Column(Integer, ForeignKey("drivers.id"), nullable=False)
    assignment_type = Column(String, default="primary")  # primary, secondary
    assigned_date = Column(DateTime, server_default=func.now())
    return_date = Column(DateTime)
    is_active = Column(Boolean, default=True)
