from sqlalchemy import Column, Integer, String, DateTime, func
from app.database import Base


class Driver(Base):
    __tablename__ = "drivers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String)
    phone = Column(String)
    department = Column(String)
    role = Column(String)  # employee, contractor, marketing, executive
    created_at = Column(DateTime, server_default=func.now())
