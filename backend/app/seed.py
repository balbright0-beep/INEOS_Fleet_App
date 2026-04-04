import bcrypt
from app.models.user import User
from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def seed_database(db):
    if db.query(User).count() == 0:
        password = settings.ADMIN_DEFAULT_PASSWORD or "admin123"
        admin = User(
            username="admin",
            password_hash=hash_password(password),
            role="admin",
        )
        db.add(admin)
        db.commit()
        print("Seeded admin user")
