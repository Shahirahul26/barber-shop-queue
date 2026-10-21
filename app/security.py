from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session
from .config import settings
from .database import get_db
from .models import StaffUser


password_hash = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_access_token(user: StaffUser) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user.id), "shop_id": user.shop_id, "role": user.role, "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes)}, settings.secret_key, algorithm="HS256")


def create_customer_token(customer_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(customer_id), "type": "customer", "iat": now, "exp": now + timedelta(days=90)}, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc


def current_staff(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> StaffUser:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Staff login required")
    payload = decode_access_token(credentials.credentials)
    user = db.get(StaffUser, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Staff account is inactive")
    if user.must_change_password and request.url.path != "/api/auth/change-password":
        raise HTTPException(status_code=403, detail="Change your temporary password before using the dashboard")
    return user
