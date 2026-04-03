from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.dealer import Dealer

router = APIRouter(prefix="/api/dealers", tags=["dealers"])


@router.get("")
def list_dealers(db: Session = Depends(get_db)):
    rows = db.query(Dealer).order_by(Dealer.region, Dealer.name).all()
    return [{"id": d.id, "name": d.name, "region": d.region, "market_area": d.market_area, "city": d.city, "state": d.state, "contact_name": d.contact_name, "contact_phone": d.contact_phone, "contact_email": d.contact_email} for d in rows]


@router.post("")
def create_dealer(data: dict, db: Session = Depends(get_db)):
    d = Dealer(**{k: v for k, v in data.items() if hasattr(Dealer, k)})
    db.add(d)
    db.commit()
    db.refresh(d)
    return {"id": d.id, "name": d.name}
