from sqlalchemy import Column, Integer, String, DateTime, func
from app.database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(Integer, primary_key=True, index=True)
    vin = Column(String, unique=True, index=True)
    year = Column(String)
    model = Column(String, default="Grenadier")
    body_style = Column(String)
    trim = Column(String)
    color = Column(String)
    ext_color = Column(String)
    category = Column(String, index=True)  # marketing_pr, demo, iecp, pto, internal, navs, de_fleet
    status = Column(String, default="active", index=True)  # active, returned, in_transit, maintenance
    location_city = Column(String)
    location_state = Column(String)
    dealer_name = Column(String)
    plate_number = Column(String)
    mileage = Column(Integer)
    notes = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
