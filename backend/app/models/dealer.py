from sqlalchemy import Column, Integer, String
from app.database import Base


class Dealer(Base):
    __tablename__ = "dealers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    region = Column(String)
    market_area = Column(String)
    address = Column(String)
    city = Column(String)
    state = Column(String)
    zip_code = Column(String)
    contact_name = Column(String)
    contact_phone = Column(String)
    contact_email = Column(String)
