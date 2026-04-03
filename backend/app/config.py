from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "INEOS Fleet Management"
    DATABASE_URL: str = "sqlite:///fleet.db"
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 8
    ALLOWED_ORIGINS: str = "http://localhost:8000"
    ADMIN_DEFAULT_PASSWORD: str = "admin123"

    class Config:
        env_file = ".env"


settings = Settings()
