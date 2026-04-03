from passlib.context import CryptContext
from app.models.user import User
from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def seed_database(db):
    if db.query(User).count() == 0:
        admin = User(
            username="admin",
            password_hash=pwd_context.hash(settings.ADMIN_DEFAULT_PASSWORD),
            role="admin",
        )
        db.add(admin)
        db.commit()
        print("Seeded admin user")
