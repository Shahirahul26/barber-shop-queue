from contextlib import asynccontextmanager
from contextlib import suppress
from datetime import date, datetime, timedelta, timezone, time as dt_time
from io import BytesIO
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
import re
import asyncio
import hashlib
import secrets
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

import qrcode
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from .config import settings, validate_production_settings
from .email_service import send_customer_otp_email, send_password_reset_email, smtp_is_configured
from .database import Base, SessionLocal, engine, get_db
from .models import Appointment, AuditEvent, Barber, CustomerUser, PlatformSetting, PushSubscription, QueueEntry, QueueStatus, Rating, Service, Shop, StaffUser
from .notifications import notify_queue_milestones
from .queue_service import active_queue, estimated_waits, queue_view
from .realtime import manager
from .schemas import (
    AdminShopCreate, AppointmentAction, AppointmentCreate, AppointmentOut, ApprovalUpdate, BannerUpdate, CustomerOtpRequest, CustomerOtpVerify, ForgotPasswordRequest, GoogleLoginRequest,
    BarberCreate, BarberOut, BarberUpdate, CustomerAction, LoginRequest, QueueEntryOut, QueueJoin,
    PasswordChange, PasswordResetConfirm, PushSubscriptionIn, RatingCreate, ServiceCreate, ServiceOut, ServiceUpdate, ShopOut,
    ShopStateUpdate, ShopUpdate, StaffAction, StaffCreate, StaffOut, StaffPasswordReset,
    StaffProfileUpdate, StaffStatusUpdate, TokenOut,
)
from .security import create_access_token, create_customer_token, current_staff, decode_access_token, hash_password, verify_password


STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DEFAULT_BANNER = {"software_name": "TrimTime", "eyebrow": "TRIMTIME FOR SHOPS", "title": "Less waiting. More great cuts.", "message": "Keep every chair productive while customers follow their queue from anywhere.", "login_image_url": None}


def banner_value(db: Session) -> dict:
    setting = db.get(PlatformSetting, "staff_banner")
    if setting is None:
        return DEFAULT_BANNER
    try:
        return {**DEFAULT_BANNER, **json.loads(setting.value)}
    except (TypeError, json.JSONDecodeError):
        return DEFAULT_BANNER


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    prefix = "+" if value.strip().startswith("+") else ""
    digits = re.sub(r"\D", "", value)
    return prefix + digits


def appointment_view(item: Appointment) -> dict:
    service_ids = item.service_ids or [item.service_id]
    return {"id": item.id, "public_token": item.public_token, "token": f"B{(item.daily_booking_number or item.id):02d}", "shop_id": item.shop_id, "service_id": item.service_id, "service_ids": service_ids, "barber_id": item.barber_id, "customer_name": item.customer_name, "phone": item.phone, "service_name": item.service_names or item.service.name, "total_duration_minutes": item.total_duration_minutes or item.service.duration_minutes, "total_price_rupees": item.total_price_rupees if item.total_price_rupees is not None else item.service.price_rupees, "barber_name": item.barber.name if item.barber else None, "scheduled_at": item.scheduled_at, "status": item.status}


def appointment_duration(item: Appointment) -> int:
    return item.total_duration_minutes or item.service.duration_minutes


def optional_customer(request: Request, db: Session) -> CustomerUser | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        payload = decode_access_token(header[7:])
    except HTTPException:
        return None
    if payload.get("type") != "customer":
        return None
    customer = db.get(CustomerUser, int(payload["sub"]))
    return customer if customer and customer.is_verified else None


def audit(db: Session, action: str, staff: StaffUser | None = None, shop_id: int | None = None, details: str | None = None) -> None:
    db.add(AuditEvent(shop_id=shop_id, actor_id=staff.id if staff else None, action=action, details=details))


def seed_demo_data() -> None:
    with SessionLocal() as db:
        shop = db.scalar(select(Shop).limit(1))
        if shop is None:
            shop = Shop(name="Blade & Bloom", slug="blade-and-bloom-1", address="MG Road, your city")
            shop.services = [
                Service(name="Classic haircut", duration_minutes=25, price_rupees=250),
                Service(name="Beard trim", duration_minutes=15, price_rupees=150),
                Service(name="Hair + beard", duration_minutes=40, price_rupees=350),
            ]
            shop.barbers = [Barber(name="Aman"), Barber(name="Vikram")]
            db.add(shop)
            db.flush()
        if db.scalar(select(StaffUser).where(StaffUser.email == settings.admin_email.lower())) is None:
            db.add(StaffUser(shop_id=shop.id, name="Demo Owner", email=settings.admin_email.lower(), password_hash=hash_password(settings.admin_password), role="owner", is_platform_admin=True))
        else:
            configured_admin = db.scalar(select(StaffUser).where(StaffUser.email == settings.admin_email.lower()))
            if configured_admin:
                configured_admin.is_platform_admin = True
        if settings.environment != "production" and db.scalar(select(Shop.id).where(Shop.name == "Urban Edge Salon")) is None:
            second = Shop(name="Urban Edge Salon", slug="urban-edge-salon-2", address="High Street, your city", phone="9876543210")
            second.services = [Service(name="Premium haircut", duration_minutes=30, price_rupees=350), Service(name="Beard styling", duration_minutes=20, price_rupees=200)]
            second.barbers = [Barber(name="Rohan"), Barber(name="Arjun")]
            db.add(second)
        db.commit()


def promote_due_appointments(db: Session, shop_id: int | None = None) -> set[int]:
    now = datetime.now(timezone.utc)
    # selectinload uses a separate SELECT for services. A joinedload would add a
    # LEFT OUTER JOIN, which PostgreSQL cannot combine with FOR UPDATE here.
    statement = select(Appointment).options(selectinload(Appointment.service)).where(Appointment.status.in_(("booked", "confirmed"))).order_by(Appointment.scheduled_at, Appointment.id).with_for_update(skip_locked=True)
    if shop_id is not None:
        statement = statement.where(Appointment.shop_id == shop_id)
    promoted_shops: set[int] = set()
    for appointment in db.scalars(statement).all():
        scheduled_at = appointment.scheduled_at if appointment.scheduled_at.tzinfo else appointment.scheduled_at.replace(tzinfo=timezone.utc)
        queue_entry_time = scheduled_at - timedelta(minutes=appointment_duration(appointment))
        if queue_entry_time > now:
            continue
        if db.scalar(select(QueueEntry.id).where(QueueEntry.appointment_id == appointment.id)):
            appointment.status = "queued"
            continue
        db.add(QueueEntry(appointment_id=appointment.id, shop_id=appointment.shop_id, customer_id=appointment.customer_id, service_id=appointment.service_id, service_ids=appointment.service_ids, service_names=appointment.service_names, total_duration_minutes=appointment.total_duration_minutes, total_price_rupees=appointment.total_price_rupees, barber_id=appointment.barber_id, customer_name=appointment.customer_name, phone=appointment.phone, source="appointment", joined_at=queue_entry_time))
        appointment.status = "queued"
        audit(db, "appointment.promoted_to_queue", shop_id=appointment.shop_id, details=f"appointment_id={appointment.id}")
        promoted_shops.add(appointment.shop_id)
    if promoted_shops:
        db.commit()
    return promoted_shops


def reset_expired_queue(db: Session, shop_id: int | None = None) -> set[int]:
    statement = select(QueueEntry).options(joinedload(QueueEntry.shop)).where(
        QueueEntry.status.in_((QueueStatus.WAITING, QueueStatus.SERVING, QueueStatus.SKIPPED))
    )
    if shop_id is not None:
        statement = statement.where(QueueEntry.shop_id == shop_id)
    reset_shops: set[int] = set()
    for entry in db.scalars(statement).all():
        try:
            shop_timezone = ZoneInfo(entry.shop.timezone)
        except ZoneInfoNotFoundError:
            shop_timezone = timezone.utc
        joined_at = entry.joined_at if entry.joined_at.tzinfo else entry.joined_at.replace(tzinfo=timezone.utc)
        if joined_at.astimezone(shop_timezone).date() >= datetime.now(shop_timezone).date():
            continue
        entry.status = QueueStatus.CANCELLED
        if entry.appointment_id:
            appointment = db.get(Appointment, entry.appointment_id)
            if appointment and appointment.status == "queued":
                appointment.status = "no_show"
        audit(db, "queue.daily_reset", shop_id=entry.shop_id, details=f"queue_entry_id={entry.id}")
        reset_shops.add(entry.shop_id)
    if reset_shops:
        db.commit()
    return reset_shops


async def appointment_promotion_loop() -> None:
    while True:
        try:
            with SessionLocal() as db:
                changed_shops = reset_expired_queue(db) | promote_due_appointments(db)
                for changed_shop_id in changed_shops:
                    notify_queue_milestones(db, changed_shop_id)
                    await manager.queue_changed(changed_shop_id)
        except Exception:
            # Keep the scheduler alive after a transient database or notification failure.
            pass
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_production_settings()
    if settings.environment != "production":
        Base.metadata.create_all(bind=engine)
        seed_demo_data()
    promotion_task = asyncio.create_task(appointment_promotion_loop())
    try:
        yield
    finally:
        promotion_task.cancel()
        with suppress(asyncio.CancelledError):
            await promotion_task


app = FastAPI(title="TrimTime API", version="0.3.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def load_entry(db: Session, entry_id: int) -> QueueEntry:
    entry = db.scalar(select(QueueEntry).options(joinedload(QueueEntry.service), joinedload(QueueEntry.shop), joinedload(QueueEntry.barber)).where(QueueEntry.id == entry_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="Queue entry not found")
    return entry


def require_shop(staff: StaffUser, shop_id: int) -> None:
    if staff.shop_id != shop_id:
        raise HTTPException(status_code=403, detail="You cannot manage this shop")


def require_owner(staff: StaffUser) -> None:
    if staff.role not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Owner or manager access required")


def require_platform_admin(staff: StaffUser) -> None:
    if not staff.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrator access required")


def require_staff_manager(staff: StaffUser, target: StaffUser) -> None:
    if staff.is_platform_admin:
        return
    require_shop(staff, target.shop_id)
    require_owner(staff)


@app.get("/", include_in_schema=False)
def landing_page():
    return FileResponse(STATIC_DIR / "landing.html")


@app.get("/customer", include_in_schema=False)
def customer_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/staff", include_in_schema=False)
def staff_page():
    return FileResponse(STATIC_DIR / "staff.html")


@app.get("/terms", include_in_schema=False)
def terms_page():
    return FileResponse(STATIC_DIR / "terms.html")


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


@app.get("/api/platform/banner")
def get_platform_banner(db: Session = Depends(get_db)):
    return banner_value(db)


@app.put("/api/admin/banner")
def update_platform_banner(payload: BannerUpdate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_platform_admin(staff)
    setting = db.get(PlatformSetting, "staff_banner")
    serialized = json.dumps({**banner_value(db), **payload.model_dump()})
    if setting is None:
        setting = PlatformSetting(key="staff_banner", value=serialized)
        db.add(setting)
    else:
        setting.value = serialized
    audit(db, "platform.banner_updated", staff, staff.shop_id)
    db.commit()
    return payload.model_dump()


@app.post("/api/admin/login-image")
async def upload_login_image(image: UploadFile = File(...), staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_platform_admin(staff)
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    extension = extensions.get(image.content_type or "")
    if extension is None:
        raise HTTPException(status_code=415, detail="Upload a JPG, PNG or WebP image")
    content = await image.read(5 * 1024 * 1024 + 1)
    if not content or len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Login image must be between 1 byte and 5 MB")
    filename = f"login-{secrets.token_hex(8)}{extension}"
    (UPLOAD_DIR / filename).write_bytes(content)
    banner = banner_value(db)
    old_url = banner.get("login_image_url")
    banner["login_image_url"] = f"/static/uploads/{filename}"
    setting = db.get(PlatformSetting, "staff_banner")
    if setting is None:
        db.add(PlatformSetting(key="staff_banner", value=json.dumps(banner)))
    else:
        setting.value = json.dumps(banner)
    audit(db, "platform.login_image_updated", staff, staff.shop_id)
    db.commit()
    if old_url and old_url.startswith("/static/uploads/"):
        old_path = (UPLOAD_DIR / Path(old_url).name).resolve()
        if old_path.parent == UPLOAD_DIR.resolve():
            old_path.unlink(missing_ok=True)
    return {"login_image_url": banner["login_image_url"]}


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.3.0"}


@app.get("/api/push/public-key")
def push_public_key():
    return {"public_key": settings.vapid_public_key}


@app.post("/api/push/subscribe", status_code=201)
def subscribe_push(payload: PushSubscriptionIn, db: Session = Depends(get_db)):
    entry = db.scalar(select(QueueEntry).where(QueueEntry.public_token == payload.public_token))
    if entry is None:
        raise HTTPException(status_code=404, detail="Queue entry not found")
    existing = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint))
    if existing:
        existing.queue_entry_id, existing.p256dh, existing.auth = entry.id, payload.keys.p256dh, payload.keys.auth
    else:
        db.add(PushSubscription(queue_entry_id=entry.id, endpoint=payload.endpoint, p256dh=payload.keys.p256dh, auth=payload.keys.auth))
    db.commit()
    db.refresh(entry)
    notify_queue_milestones(db, entry.shop_id)
    return {"subscribed": True}


@app.post("/api/auth/login", response_model=TokenOut)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    identifier = (payload.identifier or payload.email or "").strip().lower()
    if not identifier:
        raise HTTPException(status_code=422, detail="Enter your email address or phone number")
    user = db.scalar(select(StaffUser).where(StaffUser.email == identifier)) if "@" in identifier else db.scalar(select(StaffUser).where(StaffUser.phone == normalize_phone(identifier)))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This staff account is inactive. Contact your shop owner or administrator.")
    return {"access_token": create_access_token(user), "shop_id": user.shop_id, "staff_name": user.name, "is_platform_admin": user.is_platform_admin, "must_change_password": user.must_change_password, "role": user.role, "barber_id": user.barber_id}


@app.get("/api/auth/google/config")
def google_login_config():
    return {"enabled": bool(settings.google_client_id), "client_id": settings.google_client_id}


@app.post("/api/auth/google", response_model=TokenOut)
def google_login(payload: GoogleLoginRequest, db: Session = Depends(get_db)):
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    try:
        identity = google_id_token.verify_oauth2_token(payload.credential, google_requests.Request(), settings.google_client_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified") from exc
    email = str(identity.get("email", "")).strip().lower()
    if not email or not identity.get("email_verified"):
        raise HTTPException(status_code=401, detail="Google account email is not verified")
    user = db.scalar(select(StaffUser).where(StaffUser.email == email))
    if user is None:
        raise HTTPException(status_code=403, detail="No staff account is registered with this Google email")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This staff account is inactive")
    return {"access_token": create_access_token(user), "shop_id": user.shop_id, "staff_name": user.name, "is_platform_admin": user.is_platform_admin, "must_change_password": user.must_change_password, "role": user.role, "barber_id": user.barber_id}


def customer_identifier(value: str) -> tuple[str, str]:
    cleaned = value.strip().lower()
    if "@" in cleaned:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", cleaned):
            raise HTTPException(status_code=422, detail="Enter a valid email address")
        return "email", cleaned
    phone = normalize_phone(cleaned)
    if not phone or not 10 <= len(re.sub(r"\D", "", phone)) <= 15:
        raise HTTPException(status_code=422, detail="Enter a valid mobile number")
    return "phone", phone


@app.post("/api/customer-auth/request-otp")
def request_customer_otp(payload: CustomerOtpRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    kind, identifier = customer_identifier(payload.identifier)
    if kind == "phone" and settings.environment == "production":
        raise HTTPException(status_code=503, detail="Mobile OTP delivery is not configured. Use email or contact support.")
    customer = db.scalar(select(CustomerUser).where(getattr(CustomerUser, kind) == identifier))
    if customer is None:
        customer = CustomerUser(**{kind: identifier})
        db.add(customer)
    now = datetime.now(timezone.utc)
    sent_at = customer.otp_sent_at if not customer.otp_sent_at or customer.otp_sent_at.tzinfo else customer.otp_sent_at.replace(tzinfo=timezone.utc)
    if sent_at and (now - sent_at).total_seconds() < 60:
        raise HTTPException(status_code=429, detail="Please wait 60 seconds before requesting another OTP")
    otp = f"{secrets.randbelow(1_000_000):06d}"
    customer.otp_hash = hashlib.sha256(otp.encode()).hexdigest()
    customer.otp_expires_at = now + timedelta(minutes=10)
    customer.otp_sent_at = now
    customer.otp_attempts = 0
    db.commit()
    if kind == "email":
        background_tasks.add_task(send_customer_otp_email, identifier, otp)
    response = {"message": f"OTP sent to your {kind}. It is valid for 10 minutes.", "expires_in_seconds": 600, "first_time": not bool(customer.terms_accepted_at)}
    if settings.environment != "production" and (kind == "phone" or not smtp_is_configured()):
        response["development_otp"] = otp
    return response


@app.post("/api/customer-auth/verify-otp")
def verify_customer_otp(payload: CustomerOtpVerify, db: Session = Depends(get_db)):
    kind, identifier = customer_identifier(payload.identifier)
    customer = db.scalar(select(CustomerUser).where(getattr(CustomerUser, kind) == identifier))
    now = datetime.now(timezone.utc)
    if customer is None or not customer.otp_hash or not customer.otp_expires_at:
        raise HTTPException(status_code=400, detail="Request a new OTP")
    expires = customer.otp_expires_at if customer.otp_expires_at.tzinfo else customer.otp_expires_at.replace(tzinfo=timezone.utc)
    if expires < now:
        raise HTTPException(status_code=400, detail="OTP expired. Request a new OTP")
    if customer.otp_attempts >= 5:
        raise HTTPException(status_code=429, detail="Too many incorrect attempts. Request a new OTP")
    if not secrets.compare_digest(customer.otp_hash, hashlib.sha256(payload.otp.encode()).hexdigest()):
        customer.otp_attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Incorrect OTP")
    if customer.terms_accepted_at is None:
        if not payload.terms_accepted:
            raise HTTPException(status_code=422, detail="Accept the Terms and Conditions to continue")
        if not payload.name or payload.age is None or not payload.gender:
            raise HTTPException(status_code=422, detail="Name, age and gender are required for first-time registration")
        customer.name = payload.name.strip()
        customer.age = payload.age
        customer.gender = payload.gender
    customer.is_verified = True
    customer.terms_accepted_at = customer.terms_accepted_at or now
    customer.otp_hash = None
    customer.otp_expires_at = None
    customer.otp_attempts = 0
    db.commit()
    return {"access_token": create_customer_token(customer.id), "customer": {"id": customer.id, "name": customer.name, "age": customer.age, "gender": customer.gender, "email": customer.email, "phone": customer.phone}}


@app.get("/api/customer-auth/me")
def customer_me(request: Request, db: Session = Depends(get_db)):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Customer login required")
    payload = decode_access_token(header[7:])
    if payload.get("type") != "customer":
        raise HTTPException(status_code=401, detail="Invalid customer session")
    customer = db.get(CustomerUser, int(payload["sub"]))
    if customer is None or not customer.is_verified:
        raise HTTPException(status_code=401, detail="Customer session is no longer valid")
    return {"id": customer.id, "name": customer.name, "age": customer.age, "gender": customer.gender, "email": customer.email, "phone": customer.phone}


@app.get("/api/customer-auth/active-queue", response_model=QueueEntryOut | None)
def customer_active_queue(request: Request, db: Session = Depends(get_db)):
    customer = optional_customer(request, db)
    if customer is None:
        raise HTTPException(status_code=401, detail="Customer login required")
    entry = db.scalar(
        select(QueueEntry)
        .options(joinedload(QueueEntry.service), joinedload(QueueEntry.barber))
        .where(
            QueueEntry.customer_id == customer.id,
            QueueEntry.source == "online",
            QueueEntry.status.in_((QueueStatus.WAITING, QueueStatus.SERVING, QueueStatus.SKIPPED)),
        )
        .order_by(QueueEntry.joined_at.desc(), QueueEntry.id.desc())
    )
    return queue_view(db, entry) if entry else None


@app.get("/api/customer-auth/history")
def customer_history(request: Request, db: Session = Depends(get_db)):
    customer = optional_customer(request, db)
    if customer is None:
        raise HTTPException(status_code=401, detail="Customer login required")
    entries = list(db.scalars(select(QueueEntry).options(joinedload(QueueEntry.shop), joinedload(QueueEntry.service), joinedload(QueueEntry.barber), joinedload(QueueEntry.appointment)).where(QueueEntry.customer_id == customer.id, QueueEntry.status == QueueStatus.COMPLETED)).all())
    linked_appointment_ids = {entry.appointment_id for entry in entries if entry.appointment_id}
    appointments = list(db.scalars(select(Appointment).options(joinedload(Appointment.shop), joinedload(Appointment.service), joinedload(Appointment.barber)).where(Appointment.customer_id == customer.id, Appointment.status == "completed")).all())
    rated_queue_ids = set(db.scalars(select(Rating.queue_entry_id).where(Rating.queue_entry_id.is_not(None))).all())
    rated_appointment_ids = set(db.scalars(select(Rating.appointment_id).where(Rating.appointment_id.is_not(None))).all())
    rows = [{"token": (f"B{(entry.appointment.daily_booking_number or entry.appointment.id):02d}" if entry.appointment_id else f"A{(entry.daily_token_number or entry.id):02d}"), "public_token": entry.public_token, "rating_type": "queue", "rated": entry.id in rated_queue_ids or entry.appointment_id in rated_appointment_ids, "shop_id": entry.shop_id, "service_id": entry.service_id, "service_ids": entry.service_ids or (entry.appointment.service_ids if entry.appointment else ([entry.service_id] if entry.service_id else [])), "barber_id": entry.barber_id, "shop": entry.shop.name, "service": entry.service_names or (entry.appointment.service_names if entry.appointment else entry.service.name if entry.service else "Service not assigned"), "barber": entry.barber.name if entry.barber else "Not assigned", "date": entry.completed_at or entry.joined_at, "price_rupees": entry.total_price_rupees if entry.total_price_rupees is not None else entry.appointment.total_price_rupees if entry.appointment else entry.service.price_rupees if entry.service else 0} for entry in entries]
    rows += [{"token": f"B{(item.daily_booking_number or item.id):02d}", "public_token": item.public_token, "rating_type": "appointment", "rated": item.id in rated_appointment_ids, "shop_id": item.shop_id, "service_id": item.service_id, "service_ids": item.service_ids or [item.service_id], "barber_id": item.barber_id, "shop": item.shop.name, "service": item.service_names or item.service.name, "barber": item.barber.name if item.barber else "Not assigned", "date": item.scheduled_at, "price_rupees": item.total_price_rupees if item.total_price_rupees is not None else item.service.price_rupees} for item in appointments if item.id not in linked_appointment_ids]
    return sorted(rows, key=lambda row: row["date"], reverse=True)[:50]


@app.post("/api/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    identifier = payload.identifier.strip().lower()
    user = db.scalar(select(StaffUser).where(StaffUser.email == identifier)) if "@" in identifier else db.scalar(select(StaffUser).where(StaffUser.phone == normalize_phone(identifier)))
    response = {"message": "If the account exists, a password reset link has been sent to its registered email."}
    if user and user.is_active:
        raw_token = secrets.token_urlsafe(32)
        user.password_reset_token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        db.commit()
        reset_url = f"{str(request.base_url).rstrip('/')}/staff?reset_token={raw_token}"
        background_tasks.add_task(send_password_reset_email, user.email, reset_url)
        if settings.environment != "production" and not smtp_is_configured():
            response["development_reset_url"] = reset_url
    return response


@app.post("/api/auth/reset-password")
def reset_password(payload: PasswordResetConfirm, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    user = db.scalar(select(StaffUser).where(StaffUser.password_reset_token_hash == token_hash))
    if user is None or user.password_reset_expires_at is None:
        raise HTTPException(status_code=400, detail="This password reset link is invalid or has already been used")
    expires_at = user.password_reset_expires_at if user.password_reset_expires_at.tzinfo else user.password_reset_expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This password reset link has expired. Request a new one.")
    user.password_hash = hash_password(payload.new_password)
    user.password_reset_token_hash = None
    user.password_reset_expires_at = None
    user.must_change_password = False
    audit(db, "staff.password_reset_by_email", user, user.shop_id)
    db.commit()
    return {"message": "Password reset successfully. You can now sign in."}


@app.post("/api/auth/register-shop", response_model=TokenOut, status_code=201)
def register_shop(payload: AdminShopCreate, db: Session = Depends(get_db)):
    if not payload.terms_accepted:
        raise HTTPException(status_code=422, detail="Accept the Terms and Conditions before registering your shop")
    email = payload.owner_email.lower()
    if db.scalar(select(StaffUser.id).where(StaffUser.email == email)):
        raise HTTPException(status_code=409, detail="This email is already registered. Sign in or ask an administrator to reset your password.")
    base_slug = slugify(payload.name) or "shop"
    slug, number = base_slug, 2
    while db.scalar(select(Shop.id).where(Shop.slug == slug)):
        slug, number = f"{base_slug}-{number}", number + 1
    shop = Shop(name=payload.name.strip(), slug=slug, address=payload.address.strip(), phone=payload.phone, gst_number=payload.gst_number, latitude=payload.latitude, longitude=payload.longitude, approval_status="approved")
    db.add(shop)
    db.flush()
    db.add(Service(shop_id=shop.id, name="Other", duration_minutes=20, price_rupees=0))
    phone = normalize_phone(payload.phone)
    if phone and db.scalar(select(StaffUser.id).where(StaffUser.phone == phone)):
        raise HTTPException(status_code=409, detail="This phone number is already registered")
    owner = StaffUser(shop_id=shop.id, name=payload.owner_name.strip(), email=email, phone=phone, password_hash=hash_password(payload.owner_password), role="owner")
    db.add(owner)
    audit(db, "shop.self_registered", owner, shop.id, f"Owner {email}")
    db.commit()
    db.refresh(owner)
    return {"access_token": create_access_token(owner), "shop_id": owner.shop_id, "staff_name": owner.name, "is_platform_admin": False, "must_change_password": False, "role": owner.role, "barber_id": None}


@app.post("/api/auth/change-password")
def change_password(payload: PasswordChange, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, staff.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current password")
    staff.password_hash = hash_password(payload.new_password)
    staff.must_change_password = False
    audit(db, "staff.password_changed", staff, staff.shop_id)
    db.commit()
    return {"message": "Password changed successfully"}


@app.get("/api/shops/{shop_id}", response_model=ShopOut)
def get_shop(shop_id: int, db: Session = Depends(get_db)):
    shop = db.scalar(select(Shop).options(selectinload(Shop.services), selectinload(Shop.barbers)).where(Shop.id == shop_id))
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    waiting = [item for item in active_queue(db, shop_id) if item.status == QueueStatus.WAITING]
    waits = estimated_waits(db, shop_id)
    ratings = [item.stars for item in shop.ratings]
    return {"id": shop.id, "name": shop.name, "address": shop.address, "phone": shop.phone, "gst_number": shop.gst_number, "slug": shop.slug, "latitude": shop.latitude, "longitude": shop.longitude, "approval_status": shop.approval_status, "average_rating": round(sum(ratings) / len(ratings), 1) if ratings else 0, "rating_count": len(ratings), "timezone": shop.timezone, "opens_at": shop.opens_at, "closes_at": shop.closes_at, "queue_paused": shop.queue_paused, "photo_url": shop.photo_url, "waiting_count": len(waiting), "estimated_wait_minutes": max(waits.values(), default=0), "services": [item for item in shop.services if item.is_active], "barbers": [item for item in shop.barbers if item.is_active]}


@app.get("/api/shops", response_model=list[ShopOut])
def list_shops(db: Session = Depends(get_db)):
    shop_ids = list(db.scalars(select(Shop.id).where(Shop.approval_status == "approved").order_by(Shop.name)).all())
    return [get_shop(shop_id, db) for shop_id in shop_ids]


@app.get("/api/feedback")
def public_feedback(db: Session = Depends(get_db)):
    items = db.scalars(select(Rating).options(joinedload(Rating.shop)).where(Rating.comment.is_not(None), Rating.comment != "").order_by(Rating.created_at.desc()).limit(10)).all()
    return [{"shop_name": item.shop.name, "stars": item.stars, "comment": item.comment, "created_at": item.created_at} for item in items]


@app.get("/api/shops/{shop_id}/qr")
def shop_qr(shop_id: int, request: Request, db: Session = Depends(get_db)):
    if db.get(Shop, shop_id) is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    customer_url = str(request.base_url).rstrip("/") + f"/customer?shop={shop_id}"
    image = qrcode.make(customer_url)
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return StreamingResponse(output, media_type="image/png", headers={"Content-Disposition": f'inline; filename="shop-{shop_id}-qr.png"'})


@app.patch("/api/shops/{shop_id}", response_model=ShopOut)
async def update_shop(shop_id: int, payload: ShopUpdate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_shop(staff, shop_id)
    require_owner(staff)
    shop = db.get(Shop, shop_id)
    for field, value in payload.model_dump().items():
        setattr(shop, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    await manager.queue_changed(shop_id)
    return get_shop(shop_id, db)


@app.post("/api/shops/{shop_id}/photo", response_model=ShopOut)
async def upload_shop_photo(shop_id: int, photo: UploadFile = File(...), staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_shop(staff, shop_id)
    require_owner(staff)
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    extension = extensions.get(photo.content_type or "")
    if extension is None:
        raise HTTPException(status_code=415, detail="Upload a JPG, PNG or WebP image")
    content = await photo.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Shop photo must be 5 MB or smaller")
    if not content:
        raise HTTPException(status_code=400, detail="The selected image is empty")
    shop = db.get(Shop, shop_id)
    filename = f"shop-{shop_id}-{secrets.token_hex(8)}{extension}"
    destination = UPLOAD_DIR / filename
    destination.write_bytes(content)
    old_url = shop.photo_url
    shop.photo_url = f"/static/uploads/{filename}"
    audit(db, "shop.photo_updated", staff, shop_id)
    db.commit()
    if old_url and old_url.startswith("/static/uploads/"):
        old_path = (UPLOAD_DIR / Path(old_url).name).resolve()
        if old_path.parent == UPLOAD_DIR.resolve() and old_path != destination.resolve():
            old_path.unlink(missing_ok=True)
    return get_shop(shop_id, db)


@app.post("/api/shops/{shop_id}/services", response_model=ServiceOut, status_code=201)
async def add_service(shop_id: int, payload: ServiceCreate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_shop(staff, shop_id)
    require_owner(staff)
    service = Service(shop_id=shop_id, **payload.model_dump())
    db.add(service)
    db.commit()
    db.refresh(service)
    await manager.queue_changed(shop_id)
    return service


@app.patch("/api/services/{service_id}", response_model=ServiceOut)
async def update_service(service_id: int, payload: ServiceUpdate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    service = db.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    require_shop(staff, service.shop_id)
    require_owner(staff)
    for field, value in payload.model_dump().items():
        setattr(service, field, value)
    db.commit()
    db.refresh(service)
    await manager.queue_changed(service.shop_id)
    return service


@app.delete("/api/services/{service_id}")
async def delete_service(service_id: int, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    service = db.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    require_shop(staff, service.shop_id)
    require_owner(staff)
    active_count = db.scalar(select(func.count(Service.id)).where(Service.shop_id == service.shop_id, Service.is_active.is_(True)))
    if active_count <= 1:
        raise HTTPException(status_code=409, detail="A shop must keep at least one active service")
    service.is_active = False
    audit(db, "service.deleted", staff, service.shop_id, f"service_id={service.id}")
    db.commit()
    await manager.queue_changed(service.shop_id)
    return {"message": "Service deleted"}


@app.get("/api/shops/{shop_id}/staff", response_model=list[StaffOut])
def list_staff(shop_id: int, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    if not staff.is_platform_admin:
        require_shop(staff, shop_id)
        require_owner(staff)
    return list(db.scalars(select(StaffUser).where(StaffUser.shop_id == shop_id).order_by(StaffUser.name)).all())


@app.post("/api/shops/{shop_id}/staff", response_model=StaffOut, status_code=201)
def add_staff(shop_id: int, payload: StaffCreate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_shop(staff, shop_id)
    require_owner(staff)
    email = payload.email.lower()
    if db.scalar(select(StaffUser.id).where(StaffUser.email == email)):
        raise HTTPException(status_code=409, detail="Email is already registered")
    phone = normalize_phone(payload.phone)
    if phone and db.scalar(select(StaffUser.id).where(StaffUser.phone == phone)):
        raise HTTPException(status_code=409, detail="Phone number is already registered")
    barber = db.get(Barber, payload.barber_id) if payload.barber_id else None
    if payload.role == "barber" and (barber is None or barber.shop_id != shop_id):
        raise HTTPException(status_code=400, detail="Choose the barber profile linked to this staff login")
    user = StaffUser(shop_id=shop_id, barber_id=barber.id if barber else None, name=payload.name.strip(), email=email, phone=phone, password_hash=hash_password(payload.password), role=payload.role, must_change_password=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.patch("/api/staff/{staff_id}/password", response_model=StaffOut)
def reset_staff_password(staff_id: int, payload: StaffPasswordReset, actor: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    target = db.get(StaffUser, staff_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Staff account not found")
    require_staff_manager(actor, target)
    target.password_hash = hash_password(payload.temporary_password)
    target.must_change_password = True
    audit(db, "staff.password_reset", actor, target.shop_id, f"staff_id={target.id}")
    db.commit()
    db.refresh(target)
    return target


@app.patch("/api/staff/{staff_id}/status", response_model=StaffOut)
def update_staff_status(staff_id: int, payload: StaffStatusUpdate, actor: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    target = db.get(StaffUser, staff_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Staff account not found")
    require_staff_manager(actor, target)
    if target.id == actor.id and not payload.is_active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    target.is_active = payload.is_active
    audit(db, "staff.status_changed", actor, target.shop_id, f"staff_id={target.id};active={payload.is_active}")
    db.commit()
    db.refresh(target)
    return target


@app.patch("/api/staff/{staff_id}/profile", response_model=StaffOut)
def update_staff_profile(staff_id: int, payload: StaffProfileUpdate, actor: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    target = db.get(StaffUser, staff_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Staff account not found")
    require_staff_manager(actor, target)
    barber = db.get(Barber, payload.barber_id) if payload.barber_id else None
    if payload.role == "barber" and (barber is None or barber.shop_id != target.shop_id):
        raise HTTPException(status_code=400, detail="Choose a barber profile from this shop")
    target.name = payload.name.strip()
    target.role = payload.role
    target.barber_id = barber.id if payload.role == "barber" else None
    audit(db, "staff.profile_changed", actor, target.shop_id, f"staff_id={target.id};role={target.role};barber_id={target.barber_id}")
    db.commit()
    db.refresh(target)
    return target


@app.delete("/api/staff/{staff_id}")
def delete_staff(staff_id: int, actor: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    target = db.get(StaffUser, staff_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Staff account not found")
    require_staff_manager(actor, target)
    if target.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if target.role == "owner" or target.is_platform_admin:
        raise HTTPException(status_code=400, detail="Owner and platform administrator accounts cannot be deleted")
    for event in db.scalars(select(AuditEvent).where(AuditEvent.actor_id == target.id)).all():
        event.actor_id = None
    target_name, target_shop_id = target.name, target.shop_id
    db.delete(target)
    audit(db, "staff.deleted", actor, target_shop_id, f"staff_id={staff_id};name={target_name}")
    db.commit()
    return {"message": "Staff account deleted"}


@app.get("/api/shops/{shop_id}/queue", response_model=list[QueueEntryOut])
def get_queue(shop_id: int, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_shop(staff, shop_id)
    changed_shops = reset_expired_queue(db, shop_id) | promote_due_appointments(db, shop_id)
    if shop_id in changed_shops:
        notify_queue_milestones(db, shop_id)
    entries = active_queue(db, shop_id)
    entries += list(db.scalars(select(QueueEntry).options(joinedload(QueueEntry.service), joinedload(QueueEntry.barber)).where(QueueEntry.shop_id == shop_id, QueueEntry.status == QueueStatus.SKIPPED).order_by(QueueEntry.joined_at, QueueEntry.id)).all())
    if staff.role == "barber":
        if staff.barber_id is None:
            raise HTTPException(status_code=403, detail="Your login is not linked to a barber profile. Ask the owner to create or relink your account.")
        entries = [entry for entry in entries if entry.status != QueueStatus.SKIPPED and entry.barber_id in (None, staff.barber_id)]
    return [queue_view(db, entry) for entry in entries]


@app.post("/api/shops/{shop_id}/queue", response_model=QueueEntryOut, status_code=201)
async def join_queue(shop_id: int, payload: QueueJoin, request: Request, db: Session = Depends(get_db)):
    # Serialize joins for this shop so two simultaneous requests cannot receive
    # the same shop-local daily token number.
    shop = db.scalar(select(Shop).where(Shop.id == shop_id).with_for_update())
    service = db.get(Service, payload.service_id) if payload.service_id else None
    if shop is None or (service is not None and (service.shop_id != shop_id or not service.is_active)):
        raise HTTPException(status_code=404, detail="Shop or service not found")
    if payload.source == "walk_in" and service is None:
        raise HTTPException(status_code=400, detail="Choose a service for the walk-in customer")
    if shop.queue_paused:
        raise HTTPException(status_code=409, detail="This shop has temporarily paused new queue entries")
    barber = db.get(Barber, payload.barber_id) if payload.barber_id else None
    if barber and (barber.shop_id != shop_id or not barber.is_active):
        raise HTTPException(status_code=400, detail="Selected barber is unavailable")
    customer = optional_customer(request, db)
    try:
        shop_timezone = ZoneInfo(shop.timezone)
    except ZoneInfoNotFoundError:
        shop_timezone = ZoneInfo("Asia/Kolkata")
    local_now = datetime.now(shop_timezone)
    queue_day = local_now.date()
    next_token_number = (db.scalar(select(func.max(QueueEntry.daily_token_number)).where(
        QueueEntry.shop_id == shop_id, QueueEntry.queue_day == queue_day
    )) or 0) + 1
    identity_filters = []
    if customer:
        # Lock the verified customer row so simultaneous requests cannot bypass the limit.
        db.execute(select(CustomerUser.id).where(CustomerUser.id == customer.id).with_for_update()).scalar_one()
        identity_filters.append(QueueEntry.customer_id == customer.id)
        if customer.phone:
            identity_filters.append(QueueEntry.phone == customer.phone)
        if customer.email:
            identity_filters.append(func.lower(QueueEntry.email) == customer.email.lower())
    else:
        if payload.phone:
            identity_filters.append(QueueEntry.phone == payload.phone)
        if payload.email:
            identity_filters.append(func.lower(QueueEntry.email) == str(payload.email).lower())
    if payload.source == "online" and identity_filters:
        local_day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start_utc = local_day_start.astimezone(timezone.utc)
        next_day_start_utc = (local_day_start + timedelta(days=1)).astimezone(timezone.utc)
        daily_join_count = db.scalar(
            select(func.count(QueueEntry.id)).where(
                QueueEntry.source == "online",
                QueueEntry.joined_at >= day_start_utc,
                QueueEntry.joined_at < next_day_start_utc,
                QueueEntry.status != QueueStatus.COMPLETED,
                or_(*identity_filters),
            )
        ) or 0
        if daily_join_count >= 3:
            raise HTTPException(status_code=409, detail="You already have three non-completed live-queue joins today. Complete an active service or try again tomorrow before joining another queue with the same customer account, phone number, or email address.")
    entry = QueueEntry(shop_id=shop_id, customer_id=customer.id if customer else None, service_id=service.id if service else None, service_ids=[service.id] if service else [], service_names=service.name if service else None, total_duration_minutes=service.duration_minutes if service else None, total_price_rupees=service.price_rupees if service else None, barber_id=barber.id if barber else None, customer_name=payload.customer_name.strip(), phone=payload.phone, email=str(payload.email).lower() if payload.email else None, source=payload.source, queue_day=queue_day, daily_token_number=next_token_number)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    entry.service, entry.barber = service, barber
    notify_queue_milestones(db, shop_id)
    await manager.queue_changed(shop_id)
    return queue_view(db, entry)


@app.get("/api/my-queue/{public_token}", response_model=QueueEntryOut)
def get_queue_entry(public_token: str, db: Session = Depends(get_db)):
    entry = db.scalar(select(QueueEntry).options(joinedload(QueueEntry.service), joinedload(QueueEntry.barber)).where(QueueEntry.public_token == public_token))
    if entry is None:
        raise HTTPException(status_code=404, detail="Queue entry not found")
    return queue_view(db, entry)


@app.post("/api/my-queue/cancel", response_model=QueueEntryOut)
async def cancel_own_entry(payload: CustomerAction, db: Session = Depends(get_db)):
    entry = db.scalar(select(QueueEntry).options(joinedload(QueueEntry.service), joinedload(QueueEntry.barber)).where(QueueEntry.public_token == payload.public_token))
    if entry is None:
        raise HTTPException(status_code=404, detail="Queue entry not found")
    if entry.status not in (QueueStatus.WAITING, QueueStatus.SKIPPED):
        raise HTTPException(status_code=409, detail="This queue entry can no longer be cancelled")
    entry.status = QueueStatus.CANCELLED
    db.commit()
    notify_queue_milestones(db, entry.shop_id)
    await manager.queue_changed(entry.shop_id)
    return queue_view(db, entry)


@app.post("/api/queue/{entry_id}/action", response_model=QueueEntryOut)
async def update_queue_entry(entry_id: int, payload: StaffAction, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    entry = load_entry(db, entry_id)
    require_shop(staff, entry.shop_id)
    if staff.role == "barber":
        if staff.barber_id is None:
            raise HTTPException(status_code=403, detail="Your login is not linked to a barber profile")
        if payload.action not in ("start", "complete"):
            raise HTTPException(status_code=403, detail="Barbers can only start and complete their own customers")
        if entry.barber_id not in (None, staff.barber_id):
            raise HTTPException(status_code=403, detail="This customer is assigned to another barber")
        payload.barber_id = staff.barber_id
    allowed = {
        QueueStatus.WAITING: {"start", "skip", "cancel"},
        QueueStatus.SERVING: {"complete", "cancel"},
        QueueStatus.SKIPPED: {"restore", "cancel"},
    }
    if payload.action not in allowed.get(entry.status, set()):
        raise HTTPException(status_code=409, detail=f"Cannot {payload.action} an entry that is {entry.status.value}")
    if payload.barber_id:
        barber = db.scalar(select(Barber).where(Barber.id == payload.barber_id).with_for_update())
        if barber is None or barber.shop_id != entry.shop_id or not barber.is_active:
            raise HTTPException(status_code=400, detail="Selected barber is unavailable")
        entry.barber_id = barber.id
        entry.barber = barber
    if payload.service_ids and entry.source != "appointment":
        service_ids = list(dict.fromkeys(payload.service_ids))
        services = list(db.scalars(select(Service).where(Service.id.in_(service_ids))).all()) if service_ids else []
        services_by_id = {service.id: service for service in services}
        services = [services_by_id[service_id] for service_id in service_ids if service_id in services_by_id]
        if not services or len(services) != len(service_ids) or any(service.shop_id != entry.shop_id or not service.is_active for service in services):
            raise HTTPException(status_code=400, detail="Choose at least one available service")
        entry.service_id = services[0].id
        entry.service_ids = service_ids
        entry.service_names = ", ".join(service.name for service in services)
        entry.total_duration_minutes = sum(service.duration_minutes for service in services)
        entry.total_price_rupees = sum(service.price_rupees for service in services)
        entry.service = services[0]
    elif payload.service_id and entry.source != "appointment":
        service = db.get(Service, payload.service_id)
        if service is None or service.shop_id != entry.shop_id or not service.is_active:
            raise HTTPException(status_code=400, detail="Selected service is unavailable")
        entry.service_id, entry.service_ids, entry.service_names = service.id, [service.id], service.name
        entry.total_duration_minutes, entry.total_price_rupees, entry.service = service.duration_minutes, service.price_rupees, service
    transitions = {"start": QueueStatus.SERVING, "complete": QueueStatus.COMPLETED, "skip": QueueStatus.WAITING, "cancel": QueueStatus.CANCELLED, "restore": QueueStatus.WAITING}
    entry.status = transitions[payload.action]
    now = datetime.now(timezone.utc)
    if payload.action == "start":
        service_missing = not entry.service_ids
        barber_missing = not entry.barber_id
        if service_missing and barber_missing:
            raise HTTPException(status_code=400, detail="Please choose a service and assign a barber before starting")
        if service_missing:
            raise HTTPException(status_code=400, detail="Please choose at least one service before starting")
        if barber_missing:
            raise HTTPException(status_code=400, detail="Please assign a barber before starting")
        if not payload.barber_id:
            db.scalar(select(Barber).where(Barber.id == entry.barber_id).with_for_update())
        busy = db.scalar(select(QueueEntry.id).where(QueueEntry.barber_id == entry.barber_id, QueueEntry.status == QueueStatus.SERVING, QueueEntry.id != entry.id))
        if busy:
            raise HTTPException(status_code=409, detail="This barber is already serving another customer. Please choose a different barber or wait until this barber is free.")
        entry.started_at = now
    if payload.action == "complete":
        entry.completed_at = now
    if payload.action in ("skip", "restore"):
        entry.joined_at = now
        if payload.action == "skip":
            entry.priority_active = False
        entry.two_ahead_notified_at = None
        entry.next_notified_at = None
    if entry.appointment_id and payload.action in ("complete", "cancel"):
        appointment = db.get(Appointment, entry.appointment_id)
        if appointment:
            appointment.status = "completed" if payload.action == "complete" else "cancelled"
    db.commit()
    db.refresh(entry)
    notify_queue_milestones(db, entry.shop_id)
    await manager.queue_changed(entry.shop_id)
    return queue_view(db, entry)


@app.post("/api/shops/{shop_id}/barbers", response_model=BarberOut, status_code=201)
async def add_barber(shop_id: int, payload: BarberCreate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_shop(staff, shop_id)
    require_owner(staff)
    barber = Barber(shop_id=shop_id, name=payload.name.strip())
    db.add(barber)
    db.commit()
    db.refresh(barber)
    await manager.queue_changed(shop_id)
    return barber


@app.patch("/api/barbers/{barber_id}", response_model=BarberOut)
async def update_barber(barber_id: int, payload: BarberUpdate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    barber = db.get(Barber, barber_id)
    if barber is None:
        raise HTTPException(status_code=404, detail="Barber not found")
    require_shop(staff, barber.shop_id)
    require_owner(staff)
    barber.name = payload.name.strip()
    barber.is_active = payload.is_active
    db.commit()
    db.refresh(barber)
    await manager.queue_changed(barber.shop_id)
    return barber


@app.delete("/api/barbers/{barber_id}", status_code=204)
async def delete_barber(barber_id: int, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    barber = db.get(Barber, barber_id)
    if barber is None:
        raise HTTPException(status_code=404, detail="Barber not found")
    require_shop(staff, barber.shop_id)
    require_owner(staff)
    serving = db.scalar(select(QueueEntry.id).where(QueueEntry.barber_id == barber.id, QueueEntry.status == QueueStatus.SERVING))
    if serving:
        raise HTTPException(status_code=409, detail="Complete or reassign this barber's active service before deleting them")
    for entry in db.scalars(select(QueueEntry).where(QueueEntry.barber_id == barber.id, QueueEntry.status == QueueStatus.WAITING)).all():
        entry.barber_id = None
    for appointment in db.scalars(select(Appointment).where(Appointment.barber_id == barber.id, Appointment.status.in_(("booked", "confirmed")))).all():
        appointment.barber_id = None
    barber.is_active = False
    audit(db, "barber.deleted", staff, barber.shop_id, f"{barber.id}:{barber.name}")
    db.commit()
    await manager.queue_changed(barber.shop_id)


@app.patch("/api/shops/{shop_id}/state", response_model=ShopOut)
async def update_shop_state(shop_id: int, payload: ShopStateUpdate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_shop(staff, shop_id)
    shop = db.get(Shop, shop_id)
    shop.queue_paused = payload.queue_paused
    db.commit()
    await manager.queue_changed(shop_id)
    return get_shop(shop_id, db)


@app.get("/api/admin/shops", response_model=list[ShopOut])
def admin_shops(staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_platform_admin(staff)
    return [get_shop(shop_id, db) for shop_id in db.scalars(select(Shop.id).order_by(Shop.id)).all()]


@app.post("/api/admin/shops", response_model=ShopOut, status_code=201)
def admin_create_shop(payload: AdminShopCreate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_platform_admin(staff)
    email = payload.owner_email.lower()
    if db.scalar(select(StaffUser.id).where(StaffUser.email == email)):
        raise HTTPException(status_code=409, detail="Owner email is already registered")
    base_slug = slugify(payload.name) or "shop"
    slug = base_slug
    number = 2
    while db.scalar(select(Shop.id).where(Shop.slug == slug)):
        slug, number = f"{base_slug}-{number}", number + 1
    shop = Shop(name=payload.name.strip(), slug=slug, address=payload.address.strip(), phone=payload.phone, gst_number=payload.gst_number, latitude=payload.latitude, longitude=payload.longitude, approval_status="approved")
    db.add(shop)
    db.flush()
    db.add(Service(shop_id=shop.id, name="Other", duration_minutes=20, price_rupees=0))
    phone = normalize_phone(payload.phone)
    if phone and db.scalar(select(StaffUser.id).where(StaffUser.phone == phone)):
        raise HTTPException(status_code=409, detail="Owner phone number is already registered")
    db.add(StaffUser(shop_id=shop.id, name=payload.owner_name.strip(), email=email, phone=phone, password_hash=hash_password(payload.owner_password), role="owner", must_change_password=True))
    audit(db, "shop.created", staff, shop.id, f"Created {shop.name} with owner {email}")
    db.commit()
    return get_shop(shop.id, db)


@app.patch("/api/admin/shops/{shop_id}/approval", response_model=ShopOut)
def admin_approve_shop(shop_id: int, payload: ApprovalUpdate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_platform_admin(staff)
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    shop.approval_status = payload.approval_status
    audit(db, "shop.approval_changed", staff, shop.id, payload.approval_status)
    db.commit()
    return get_shop(shop.id, db)


@app.get("/api/marketplace/nearby", response_model=list[ShopOut])
def nearby_shops(latitude: float, longitude: float, radius_km: float = 10, db: Session = Depends(get_db)):
    candidates = list(db.scalars(select(Shop).where(Shop.approval_status == "approved", Shop.latitude.is_not(None), Shop.longitude.is_not(None))).all())
    def distance(shop: Shop) -> float:
        lat1, lon1, lat2, lon2 = map(radians, [latitude, longitude, shop.latitude, shop.longitude])
        return 6371 * 2 * asin(sqrt(sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin((lon2-lon1)/2)**2))
    matches = sorted(((distance(shop), shop.id) for shop in candidates), key=lambda item: item[0])
    return [get_shop(shop_id, db) for km, shop_id in matches if km <= radius_km]


def appointment_interval(item: Appointment) -> tuple[datetime, datetime]:
    start = item.scheduled_at if item.scheduled_at.tzinfo else item.scheduled_at.replace(tzinfo=timezone.utc)
    return start, start + timedelta(minutes=appointment_duration(item))


def available_barbers_for_slot(db: Session, shop_id: int, start: datetime, duration_minutes: int) -> list[Barber]:
    end = start + timedelta(minutes=duration_minutes)
    barbers = list(db.scalars(select(Barber).where(Barber.shop_id == shop_id, Barber.is_active.is_(True)).order_by(Barber.id)).all())
    appointments = list(db.scalars(select(Appointment).options(joinedload(Appointment.service)).where(Appointment.shop_id == shop_id, Appointment.status.in_(("booked", "confirmed", "queued", "serving")))).all())
    busy_ids = set()
    for item in appointments:
        existing_start, existing_end = appointment_interval(item)
        if item.barber_id and existing_start < end and start < existing_end:
            busy_ids.add(item.barber_id)
    return [barber for barber in barbers if barber.id not in busy_ids]


@app.get("/api/shops/{shop_id}/appointment-slots")
def appointment_slots(shop_id: int, appointment_date: date, service_ids: list[int] = Query(default=[]), service_id: int | None = None, barber_id: int | None = None, db: Session = Depends(get_db)):
    shop = db.get(Shop, shop_id)
    unique_service_ids = list(dict.fromkeys(service_ids or ([service_id] if service_id else [])))
    services = list(db.scalars(select(Service).where(Service.id.in_(unique_service_ids))).all()) if unique_service_ids else []
    barber = db.get(Barber, barber_id) if barber_id else None
    if shop is None or len(services) != len(unique_service_ids) or any(service.shop_id != shop_id or not service.is_active for service in services):
        raise HTTPException(status_code=404, detail="Shop or service is unavailable")
    duration_minutes = sum(service.duration_minutes for service in services)
    if barber and (barber.shop_id != shop_id or not barber.is_active):
        raise HTTPException(status_code=400, detail="Selected barber is unavailable")
    try:
        shop_timezone = ZoneInfo(shop.timezone)
    except ZoneInfoNotFoundError:
        shop_timezone = timezone.utc
    opening = datetime.combine(appointment_date, dt_time.fromisoformat(shop.opens_at), tzinfo=shop_timezone)
    closing = datetime.combine(appointment_date, dt_time.fromisoformat(shop.closes_at), tzinfo=shop_timezone)
    if closing <= opening:
        closing += timedelta(days=1)
    now = datetime.now(timezone.utc)
    slots = []
    cursor = opening
    step = timedelta(minutes=duration_minutes)
    while cursor + step <= closing:
        cursor_utc = cursor.astimezone(timezone.utc)
        available = available_barbers_for_slot(db, shop_id, cursor_utc, duration_minutes)
        if cursor_utc > now and (barber in available if barber else bool(available)):
            slots.append({"value": cursor.isoformat(), "label": cursor.strftime("%I:%M %p"), "available_barbers": len(available)})
        cursor += step
    return {"date": appointment_date.isoformat(), "service_duration_minutes": duration_minutes, "slots": slots}


@app.post("/api/shops/{shop_id}/appointments", response_model=AppointmentOut, status_code=201)
async def create_appointment(shop_id: int, payload: AppointmentCreate, request: Request, db: Session = Depends(get_db)):
    # Serialize appointment creation per shop so each service date receives a
    # collision-free B01, B02... sequence.
    shop = db.scalar(select(Shop).where(Shop.id == shop_id).with_for_update())
    service_ids = list(dict.fromkeys(payload.service_ids or ([payload.service_id] if payload.service_id else [])))
    services = list(db.scalars(select(Service).where(Service.id.in_(service_ids))).all()) if service_ids else []
    services_by_id = {service.id: service for service in services}
    services = [services_by_id[service_id] for service_id in service_ids if service_id in services_by_id]
    service = services[0] if services else None
    barber = db.get(Barber, payload.barber_id) if payload.barber_id else None
    if shop is None or shop.approval_status != "approved" or len(services) != len(service_ids) or not services or any(item.shop_id != shop_id or not item.is_active for item in services):
        raise HTTPException(status_code=404, detail="Shop or service is unavailable")
    total_duration = sum(item.duration_minutes for item in services)
    total_price = sum(item.price_rupees for item in services)
    service_names = ", ".join(item.name for item in services)
    if payload.scheduled_at.tzinfo is None or payload.scheduled_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Appointment must be in the future")
    try:
        shop_timezone = ZoneInfo(shop.timezone)
    except ZoneInfoNotFoundError:
        shop_timezone = timezone.utc
    local_appointment = payload.scheduled_at.astimezone(shop_timezone)
    booking_day = local_appointment.date()
    next_booking_number = (db.scalar(select(func.max(Appointment.daily_booking_number)).where(
        Appointment.shop_id == shop_id, Appointment.booking_day == booking_day
    )) or 0) + 1
    opening_time = dt_time.fromisoformat(shop.opens_at)
    closing_time = dt_time.fromisoformat(shop.closes_at)
    opening_at = datetime.combine(local_appointment.date(), opening_time, tzinfo=shop_timezone)
    closing_at = datetime.combine(local_appointment.date(), closing_time, tzinfo=shop_timezone)
    if closing_at <= opening_at:
        closing_at += timedelta(days=1)
        if local_appointment < opening_at:
            opening_at -= timedelta(days=1)
            closing_at -= timedelta(days=1)
    service_finishes_at = local_appointment + timedelta(minutes=total_duration)
    within_hours = opening_at <= local_appointment and service_finishes_at <= closing_at
    if not within_hours:
        raise HTTPException(status_code=409, detail=f"Please select an appointment during shop opening hours: {shop.opens_at} to {shop.closes_at} ({shop.timezone}).")
    if barber and (barber.shop_id != shop_id or not barber.is_active):
        raise HTTPException(status_code=400, detail="Selected barber is unavailable")
    available = available_barbers_for_slot(db, shop_id, payload.scheduled_at.astimezone(timezone.utc), total_duration)
    if barber and barber not in available:
        raise HTTPException(status_code=409, detail=f"{barber.name} is unavailable for the full {total_duration}-minute booking. Choose another barber or slot.")
    if barber is None:
        if not available:
            raise HTTPException(status_code=409, detail="All barbers are busy during this service slot. Choose another time.")
        barber = available[0]
    customer = optional_customer(request, db)
    item = Appointment(shop_id=shop_id, customer_id=customer.id if customer else None, service_id=service.id, service_ids=service_ids, service_names=service_names, total_duration_minutes=total_duration, total_price_rupees=total_price, barber_id=barber.id if barber else None, customer_name=payload.customer_name.strip(), phone=payload.phone, scheduled_at=payload.scheduled_at.astimezone(timezone.utc), booking_day=booking_day, daily_booking_number=next_booking_number)
    db.add(item)
    db.commit()
    db.refresh(item)
    item.service, item.barber = service, barber
    await manager.queue_changed(shop_id)
    return appointment_view(item)


@app.get("/api/my-appointment/{public_token}", response_model=AppointmentOut)
def get_customer_appointment(public_token: str, db: Session = Depends(get_db)):
    item = db.scalar(select(Appointment).options(joinedload(Appointment.service), joinedload(Appointment.barber)).where(Appointment.public_token == public_token))
    if item is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appointment_view(item)


@app.post("/api/my-appointment/cancel", response_model=AppointmentOut)
async def cancel_customer_appointment(payload: CustomerAction, db: Session = Depends(get_db)):
    item = db.scalar(select(Appointment).options(joinedload(Appointment.service), joinedload(Appointment.barber)).where(Appointment.public_token == payload.public_token))
    if item is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if item.status not in ("booked", "confirmed", "queued"):
        raise HTTPException(status_code=409, detail=f"This appointment cannot be cancelled because it is {item.status}")
    linked_entry = db.scalar(select(QueueEntry).where(QueueEntry.appointment_id == item.id))
    if linked_entry and linked_entry.status == QueueStatus.SERVING:
        raise HTTPException(status_code=409, detail="This appointment is already being served and can no longer be cancelled")
    if linked_entry and linked_entry.status in (QueueStatus.WAITING, QueueStatus.SKIPPED):
        linked_entry.status = QueueStatus.CANCELLED
    item.status = "cancelled"
    db.commit()
    await manager.queue_changed(item.shop_id)
    return appointment_view(item)


@app.get("/api/shops/{shop_id}/appointments", response_model=list[AppointmentOut])
def staff_appointments(shop_id: int, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_shop(staff, shop_id)
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    try:
        shop_timezone = ZoneInfo(shop.timezone)
    except ZoneInfoNotFoundError:
        shop_timezone = ZoneInfo("Asia/Kolkata")
    local_now = datetime.now(shop_timezone)
    today_start_utc = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    statement = select(Appointment).options(joinedload(Appointment.service), joinedload(Appointment.barber)).where(
        Appointment.shop_id == shop_id,
        Appointment.status.not_in(("cancelled", "completed")),
        Appointment.scheduled_at >= today_start_utc,
    )
    if staff.role == "barber":
        if staff.barber_id is None:
            raise HTTPException(status_code=403, detail="Your login is not linked to a barber profile")
        statement = statement.where(Appointment.barber_id == staff.barber_id)
    items = db.scalars(statement.order_by(Appointment.scheduled_at)).all()
    return [appointment_view(item) for item in items]


@app.patch("/api/appointments/{appointment_id}", response_model=AppointmentOut)
async def update_appointment(appointment_id: int, payload: AppointmentAction, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    item = db.scalar(select(Appointment).options(joinedload(Appointment.service), joinedload(Appointment.barber)).where(Appointment.id == appointment_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    require_shop(staff, item.shop_id)
    if staff.role == "barber" and item.barber_id != staff.barber_id:
        raise HTTPException(status_code=403, detail="You can only update your own appointments")
    if staff.role == "barber" and payload.status not in ("serving", "completed"):
        raise HTTPException(status_code=403, detail="Barbers can only start or complete their own appointments")
    item.status = payload.status
    if payload.status in ("cancelled", "completed"):
        linked_entry = db.scalar(select(QueueEntry).where(QueueEntry.appointment_id == item.id, QueueEntry.status.in_((QueueStatus.WAITING, QueueStatus.SERVING))))
        if linked_entry:
            linked_entry.status = QueueStatus.CANCELLED if payload.status == "cancelled" else QueueStatus.COMPLETED
            if payload.status == "completed":
                linked_entry.completed_at = datetime.now(timezone.utc)
    audit(db, "appointment.updated", staff, item.shop_id, f"{item.id}:{payload.status}")
    db.commit()
    await manager.queue_changed(item.shop_id)
    return appointment_view(item)


@app.post("/api/ratings", status_code=201)
def create_rating(payload: RatingCreate, db: Session = Depends(get_db)):
    entry = db.scalar(select(QueueEntry).where(QueueEntry.public_token == payload.queue_public_token)) if payload.queue_public_token else None
    appointment = db.scalar(select(Appointment).where(Appointment.public_token == payload.appointment_public_token)) if payload.appointment_public_token else None
    if (entry is None) == (appointment is None):
        raise HTTPException(status_code=400, detail="Provide one completed queue visit or appointment")
    visit = entry or appointment
    if visit.status != (QueueStatus.COMPLETED if entry else "completed"):
        raise HTTPException(status_code=400, detail="Only completed services can be rated")
    duplicate_filters = [Rating.queue_entry_id == entry.id] if entry else [Rating.appointment_id == appointment.id]
    if entry and entry.appointment_id:
        duplicate_filters.append(Rating.appointment_id == entry.appointment_id)
    if appointment:
        linked_entry_id = db.scalar(select(QueueEntry.id).where(QueueEntry.appointment_id == appointment.id))
        if linked_entry_id:
            duplicate_filters.append(Rating.queue_entry_id == linked_entry_id)
    if db.scalar(select(Rating.id).where(or_(*duplicate_filters))):
        raise HTTPException(status_code=409, detail="This service has already been rated")
    # A single customer score updates the shop and the assigned barber.
    barber_stars = (payload.barber_stars or payload.stars) if visit.barber_id else None
    barber_comment = payload.barber_comment if visit.barber_id else None
    db.add(Rating(shop_id=visit.shop_id, queue_entry_id=entry.id if entry else None, appointment_id=appointment.id if appointment else None, barber_id=visit.barber_id, stars=payload.stars, comment=payload.comment, barber_stars=barber_stars, barber_comment=barber_comment))
    db.commit()
    return {"rated": True}


@app.get("/api/shops/{shop_id}/analytics")
def shop_analytics(shop_id: int, start_date: date | None = None, end_date: date | None = None, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_shop(staff, shop_id)
    shop = db.get(Shop, shop_id)
    entries = list(db.scalars(select(QueueEntry).where(QueueEntry.shop_id == shop_id)).all())
    appointments = list(db.scalars(select(Appointment).where(Appointment.shop_id == shop_id)).all())
    try:
        shop_timezone = ZoneInfo(shop.timezone)
    except ZoneInfoNotFoundError:
        shop_timezone = timezone.utc
    today = datetime.now(shop_timezone).date()
    range_start, range_end = start_date or today, end_date or today
    if range_end < range_start:
        raise HTTPException(status_code=422, detail="End date must be on or after start date")
    def local_date(value: datetime | None) -> date | None:
        if value is None:
            return None
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(shop_timezone).date()
    def in_range(value: datetime | None) -> bool:
        value_date = local_date(value)
        return value_date is not None and range_start <= value_date <= range_end
    range_entries = [item for item in entries if in_range(item.completed_at or item.joined_at)]
    range_appointments = [item for item in appointments if in_range(item.scheduled_at)]
    cancelled_appointments = [item for item in range_appointments if item.status == "cancelled"]
    completed = [item for item in entries if item.status == QueueStatus.COMPLETED and in_range(item.completed_at)]
    linked_appointment_ids = {item.appointment_id for item in completed if item.appointment_id}
    completed_appointments = [item for item in range_appointments if item.status == "completed" and item.id not in linked_appointment_ids]
    def queue_entry_price(item: QueueEntry) -> int:
        if item.total_price_rupees is not None:
            return item.total_price_rupees
        if item.appointment and item.appointment.total_price_rupees is not None:
            return item.appointment.total_price_rupees
        service = db.get(Service, item.service_id) if item.service_id else None
        return service.price_rupees if service else 0
    def appointment_price(item: Appointment) -> int:
        return item.total_price_rupees if item.total_price_rupees is not None else db.get(Service, item.service_id).price_rupees
    revenue = sum(queue_entry_price(item) for item in completed) + sum(appointment_price(item) for item in completed_appointments)
    barber_rows = []
    barbers = list(db.scalars(select(Barber).where(Barber.shop_id == shop_id).order_by(Barber.name)).all())
    for barber in barbers:
        barber_entries = [item for item in entries if item.barber_id == barber.id]
        barber_completed = [item for item in barber_entries if item.status == QueueStatus.COMPLETED]
        barber_completed = [item for item in barber_completed if in_range(item.completed_at)]
        barber_completed_appointments = [item for item in completed_appointments if item.barber_id == barber.id]
        barber_ratings = [item for item in db.scalars(select(Rating).where(Rating.barber_id == barber.id, Rating.barber_stars.is_not(None))).all() if in_range(item.created_at)]
        barber_rows.append({
            "barber_id": barber.id,
            "barber_name": barber.name,
            "waiting": sum(item.status == QueueStatus.WAITING for item in barber_entries),
            "serving": sum(item.status == QueueStatus.SERVING for item in barber_entries),
            "completed_services": len(barber_completed) + len(barber_completed_appointments),
            "appointments": sum(item.barber_id == barber.id for item in range_appointments),
            "cancelled_appointments": sum(item.barber_id == barber.id and item.status == "cancelled" for item in range_appointments),
            "average_rating": round(sum(item.barber_stars for item in barber_ratings) / len(barber_ratings), 1) if barber_ratings else 0,
            "review_count": len(barber_ratings),
            "estimated_revenue_rupees": sum(queue_entry_price(item) for item in barber_completed) + sum(appointment_price(item) for item in barber_completed_appointments),
        })
    if staff.role == "barber":
        barber_rows = [row for row in barber_rows if row["barber_id"] == staff.barber_id]
    barber_names = {barber.id: barber.name for barber in barbers}
    revenue_records = [(item.barber_id, queue_entry_price(item), item.completed_at) for item in completed if item.completed_at]
    revenue_records += [(item.barber_id, appointment_price(item), item.scheduled_at) for item in completed_appointments]
    if staff.role == "barber":
        revenue_records = [record for record in revenue_records if record[0] == staff.barber_id]
    daily: dict[str, dict] = {}
    for barber_id, amount, occurred_at in revenue_records:
        occurred_date = local_date(occurred_at)
        if occurred_date is None or not range_start <= occurred_date <= range_end:
            continue
        date_key = occurred_date.isoformat()
        row = daily.setdefault(date_key, {"date": date_key, "total_revenue_rupees": 0, "barbers": {}})
        row["total_revenue_rupees"] += amount
        if barber_id:
            barber_row = row["barbers"].setdefault(barber_id, {"barber_id": barber_id, "barber_name": barber_names.get(barber_id, "Unknown barber"), "revenue_rupees": 0})
            barber_row["revenue_rupees"] += amount
    daily_rows = []
    for row in sorted(daily.values(), key=lambda item: item["date"], reverse=True):
        row["barbers"] = sorted(row["barbers"].values(), key=lambda item: item["barber_name"])
        daily_rows.append(row)
    today_revenue = daily.get(today.isoformat(), {}).get("total_revenue_rupees", 0)
    month_revenue = sum(row["total_revenue_rupees"] for row in daily.values())
    return {"range_start": range_start, "range_end": range_end, "total_queue_entries": len(range_entries), "completed_services": len(completed) + len(completed_appointments), "appointments": len(range_appointments), "cancelled_appointments": len(cancelled_appointments), "estimated_revenue_rupees": revenue, "today_revenue_rupees": today_revenue, "month_revenue_rupees": month_revenue, "daily_revenue": daily_rows, "barbers": barber_rows}


@app.websocket("/ws/shops/{shop_id}")
async def shop_socket(websocket: WebSocket, shop_id: int):
    await manager.connect(shop_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(shop_id, websocket)


@app.websocket("/ws/staff/{shop_id}")
async def staff_socket(websocket: WebSocket, shop_id: int, token: str):
    try:
        payload = decode_access_token(token)
        if int(payload["shop_id"]) != shop_id:
            await websocket.close(code=1008)
            return
    except HTTPException:
        await websocket.close(code=1008)
        return
    await manager.connect(shop_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(shop_id, websocket)
