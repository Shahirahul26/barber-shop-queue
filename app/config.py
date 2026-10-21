import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()

@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("ENVIRONMENT", "development")
    secret_key: str = os.getenv("SECRET_KEY", "development-only-change-me")
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "480"))
    admin_email: str = os.getenv("ADMIN_EMAIL", "owner@example.com")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")
    allowed_hosts: tuple[str, ...] = tuple(item.strip() for item in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if item.strip())
    vapid_public_key: str = os.getenv("VAPID_PUBLIC_KEY", "")
    vapid_private_key: str = os.getenv("VAPID_PRIVATE_KEY", "")
    vapid_subject: str = os.getenv("VAPID_SUBJECT", "mailto:owner@example.com")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from_email: str = os.getenv("SMTP_FROM_EMAIL", "")
    smtp_use_tls: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")


settings = Settings()


def validate_production_settings() -> None:
    if settings.environment != "production":
        return
    if settings.secret_key == "development-only-change-me" or len(settings.secret_key) < 32:
        raise RuntimeError("Production SECRET_KEY must be random and at least 32 characters")
    if settings.admin_password == "ChangeMe123!":
        raise RuntimeError("Set a unique ADMIN_PASSWORD before production startup")
