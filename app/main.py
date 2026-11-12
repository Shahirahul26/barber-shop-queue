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
from .models import Appointment, AuditEvent, Barber, BarberAvailabilityException, BarberMembershipRequest, BarberPortfolioImage, BarberProfile, BarberServiceAssignment, BarberWeeklyAvailability, CustomerUser, PlatformSetting, PushSubscription, QueueEntry, QueueStatus, Rating, Service, Shop, ShopBarberMembership, StaffUser, TrustedDeviceSession
from .notifications import notify_queue_milestones
from .queue_service import active_queue, estimated_waits, queue_view
from .realtime import manager
from .schemas import (
    AdminShopCreate, AppointmentAction, AppointmentCreate, AppointmentOut, ApprovalUpdate, BannerUpdate, CustomerOtpRequest, CustomerOtpVerify, CustomerMpinComplete, CustomerProfileUpdate, DeviceCheckRequest, ForgotPasswordRequest, GoogleLoginRequest, MpinLoginRequest, MpinSetRequest,
    AvailabilityExceptionCreate, BarberCreate, BarberInvitationCreate, BarberOut, BarberProfileUpdate, BarberServicesUpdate, BarberUpdate, CustomerAction, LoginRequest, MembershipRequestAction, QueueEntryOut, QueueJoin, ShopAppointmentsFeatureUpdate, WeeklyAvailabilityUpdate,
    PasswordChange, PasswordResetConfirm, PushSubscriptionIn, RatingCreate, ServiceCreate, ServiceOut, ServiceUpdate, ShopOut,
    ShopStateUpdate, ShopUpdate, StaffAction, StaffCreate, StaffOut, StaffPasswordReset,
    StaffProfileUpdate, StaffStatusUpdate, TokenOut,
)
from .security import create_access_token, create_customer_token, create_mpin_verification_token, current_staff, decode_access_token, hash_password, verify_password
from .scheduling import barber_provides_services, eligible_barbers, next_reservation, scheduled_windows, shop_window, shop_zone


STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DEFAULT_BANNER = {"software_name": "TrimTime", "eyebrow": "TRIMTIME FOR SHOPS", "title": "Less waiting. More great cuts.", "message": "Keep every chair productive while customers follow their queue from anywhere.", "login_image_url": None}
TRUSTED_DEVICE_DAYS = 90
MPIN_MAX_ATTEMPTS = 5
MPIN_LOCK_MINUTES = 15


def aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


def weak_mpin(mpin: str) -> bool:
    common = {"000000", "111111", "123456", "654321", "121212", "112233", "123123", "101010", "999999"}
    return mpin in common or len(set(mpin)) == 1


def trusted_device(db: Session, *, device_id: str, customer_id: int | None = None, staff_user_id: int | None = None) -> TrustedDeviceSession | None:
    conditions = [TrustedDeviceSession.device_id == device_id, TrustedDeviceSession.revoked_at.is_(None)]
    conditions.append(TrustedDeviceSession.customer_id == customer_id if customer_id is not None else TrustedDeviceSession.staff_user_id == staff_user_id)
    item = db.scalar(select(TrustedDeviceSession).where(*conditions))
    if item and aware(item.expires_at) > datetime.now(timezone.utc):
        return item
    return None


def remember_device(db: Session, *, device_id: str, device_name: str | None, customer_id: int | None = None, staff_user_id: int | None = None) -> TrustedDeviceSession:
    condition = TrustedDeviceSession.customer_id == customer_id if customer_id is not None else TrustedDeviceSession.staff_user_id == staff_user_id
    item = db.scalar(select(TrustedDeviceSession).where(TrustedDeviceSession.device_id == device_id, condition))
    now = datetime.now(timezone.utc)
    if item is None:
        item = TrustedDeviceSession(device_id=device_id, customer_id=customer_id, staff_user_id=staff_user_id, expires_at=now + timedelta(days=TRUSTED_DEVICE_DAYS))
        db.add(item)
    item.device_name = (device_name or "Browser")[:160]
    item.last_used_at = now
    item.expires_at = now + timedelta(days=TRUSTED_DEVICE_DAYS)
    item.revoked_at = None
    return item


def verify_mpin(account: CustomerUser | StaffUser, mpin: str, db: Session) -> None:
    now = datetime.now(timezone.utc)
    if aware(account.mpin_locked_until) and aware(account.mpin_locked_until) > now:
        raise HTTPException(status_code=429, detail="MPIN is temporarily locked. Try again after 15 minutes or reset your MPIN.")
    if not account.mpin_hash or not verify_password(mpin, account.mpin_hash):
        account.mpin_failed_attempts = (account.mpin_failed_attempts or 0) + 1
        if account.mpin_failed_attempts >= MPIN_MAX_ATTEMPTS:
            account.mpin_locked_until = now + timedelta(minutes=MPIN_LOCK_MINUTES)
            db.commit()
            raise HTTPException(status_code=429, detail="Too many incorrect MPIN attempts. Try again after 15 minutes or reset your MPIN.")
        remaining = MPIN_MAX_ATTEMPTS - account.mpin_failed_attempts
        db.commit()
        raise HTTPException(status_code=401, detail=f"Incorrect MPIN. {remaining} attempt{'s' if remaining != 1 else ''} remaining.")
    account.mpin_failed_attempts = 0
    account.mpin_locked_until = None


def staff_session(user: StaffUser) -> dict:
    return {"access_token": create_access_token(user), "shop_id": user.shop_id, "staff_name": user.name, "is_platform_admin": user.is_platform_admin, "must_change_password": user.must_change_password, "role": user.role, "barber_id": user.barber_id, "requires_mpin_setup": not user.is_platform_admin and not bool(user.mpin_hash)}


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


def new_barber_number(db: Session) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        value = "BRB-" + "".join(secrets.choice(alphabet) for _ in range(6))
        if not db.scalar(select(BarberProfile.id).where(BarberProfile.barber_number == value)):
            return value


def barber_view(db: Session, barber: Barber) -> dict:
    profile = db.get(BarberProfile, barber.barber_profile_id) if barber.barber_profile_id else None
    career_filter = Rating.barber_profile_id == profile.id if profile else Rating.barber_id == barber.id
    career_values = list(db.scalars(select(Rating.barber_stars).where(career_filter, Rating.barber_stars.is_not(None))).all())
    shop_values = list(db.scalars(select(Rating.barber_stars).where(career_filter, Rating.shop_id == barber.shop_id, Rating.barber_stars.is_not(None))).all())
    years = 0
    if profile and profile.career_started_on:
        today = date.today()
        years = max(0, today.year - profile.career_started_on.year - ((today.month, today.day) < (profile.career_started_on.month, profile.career_started_on.day)))
    return {"id": barber.id, "name": barber.name, "is_active": barber.is_active,
        "barber_number": profile.barber_number if profile else None, "barber_profile_id": profile.id if profile else None,
        "photo_url": profile.photo_url if profile else None, "experience_years": years,
        "specialities": (profile.specialities or []) if profile else [],
        "career_rating": round(sum(career_values) / len(career_values), 1) if career_values else 0,
        "career_rating_count": len(career_values), "shop_rating": round(sum(shop_values) / len(shop_values), 1) if shop_values else 0,
        "shop_rating_count": len(shop_values)}


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
    statement = select(Appointment).options(selectinload(Appointment.service)).where(Appointment.status.in_(("booked", "confirmed", "queued"))).order_by(Appointment.scheduled_at, Appointment.id).with_for_update(skip_locked=True)
    if shop_id is not None:
        statement = statement.where(Appointment.shop_id == shop_id)
    promoted_shops: set[int] = set()
    for appointment in db.scalars(statement).all():
        scheduled_at = appointment.scheduled_at if appointment.scheduled_at.tzinfo else appointment.scheduled_at.replace(tzinfo=timezone.utc)
        shop = db.get(Shop, appointment.shop_id)
        grace = shop.appointment_grace_minutes if shop else 10
        queue_entry_time = scheduled_at - timedelta(minutes=grace)
        if queue_entry_time > now:
            continue
        existing = db.scalar(select(QueueEntry).where(QueueEntry.appointment_id == appointment.id))
        if existing:
            new_priority = now >= scheduled_at
            if existing.priority_active != new_priority:
                existing.priority_active = new_priority
                promoted_shops.add(appointment.shop_id)
            if appointment.status != "queued":
                appointment.status = "queued"
                promoted_shops.add(appointment.shop_id)
            continue
        db.add(QueueEntry(appointment_id=appointment.id, shop_id=appointment.shop_id, customer_id=appointment.customer_id, service_id=appointment.service_id, service_ids=appointment.service_ids, service_names=appointment.service_names, total_duration_minutes=appointment.total_duration_minutes, total_price_rupees=appointment.total_price_rupees, barber_id=appointment.barber_id, barber_profile_id=appointment.barber_profile_id, customer_name=appointment.customer_name, phone=appointment.phone, source="appointment", priority_active=now >= scheduled_at, joined_at=scheduled_at))
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
        try:
            with engine.begin() as conn:
                cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(shops)").fetchall()]
                if "appointments_enabled" not in cols:
                    conn.exec_driver_sql("ALTER TABLE shops ADD COLUMN appointments_enabled BOOLEAN DEFAULT 1")
        except Exception:
            pass
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
    return {"status": "ok", "version": "0.4.0"}


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
    if payload.device_id and user.mpin_hash and not user.is_platform_admin:
        remember_device(db, device_id=payload.device_id, device_name=payload.device_name, staff_user_id=user.id)
        db.commit()
    return staff_session(user)


@app.post("/api/auth/check-device")
def check_staff_device(payload: DeviceCheckRequest, db: Session = Depends(get_db)):
    identifier = payload.identifier.strip().lower()
    user = db.scalar(select(StaffUser).where(StaffUser.email == identifier)) if "@" in identifier else db.scalar(select(StaffUser).where(StaffUser.phone == normalize_phone(identifier)))
    enabled = bool(user and user.is_active and not user.is_platform_admin and user.mpin_hash and trusted_device(db, device_id=payload.device_id, staff_user_id=user.id))
    return {"mpin_login": enabled}


@app.post("/api/auth/login-mpin", response_model=TokenOut)
def staff_mpin_login(payload: MpinLoginRequest, db: Session = Depends(get_db)):
    identifier = payload.identifier.strip().lower()
    user = db.scalar(select(StaffUser).where(StaffUser.email == identifier)) if "@" in identifier else db.scalar(select(StaffUser).where(StaffUser.phone == normalize_phone(identifier)))
    if user is None or not user.is_active or user.is_platform_admin:
        raise HTTPException(status_code=401, detail="MPIN sign-in is not available for this account")
    device = trusted_device(db, device_id=payload.device_id, staff_user_id=user.id)
    if device is None:
        raise HTTPException(status_code=401, detail="This device is not trusted. Sign in with your password first.")
    verify_mpin(user, payload.mpin, db)
    device.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return staff_session(user)


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
    if payload.device_id and user.mpin_hash and not user.is_platform_admin:
        remember_device(db, device_id=payload.device_id, device_name=payload.device_name, staff_user_id=user.id)
        db.commit()
    return staff_session(user)


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
    response = {"message": f"OTP sent to your {kind}. It is valid for 10 minutes.", "expires_in_seconds": 600, "first_time": not bool(customer.terms_accepted_at), "has_mpin": bool(customer.mpin_hash)}
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
    return {"verification_token": create_mpin_verification_token(customer.id, payload.reset_mpin), "requires_mpin_setup": not bool(customer.mpin_hash) or payload.reset_mpin, "customer": {"id": customer.id, "name": customer.name, "age": customer.age, "gender": customer.gender, "email": customer.email, "phone": customer.phone}}


@app.post("/api/customer-auth/check-device")
def check_customer_device(payload: DeviceCheckRequest, db: Session = Depends(get_db)):
    kind, identifier = customer_identifier(payload.identifier)
    customer = db.scalar(select(CustomerUser).where(getattr(CustomerUser, kind) == identifier))
    enabled = bool(customer and customer.is_verified and customer.mpin_hash and trusted_device(db, device_id=payload.device_id, customer_id=customer.id))
    return {"mpin_login": enabled}


@app.post("/api/customer-auth/login-mpin")
def customer_mpin_login(payload: MpinLoginRequest, db: Session = Depends(get_db)):
    kind, identifier = customer_identifier(payload.identifier)
    customer = db.scalar(select(CustomerUser).where(getattr(CustomerUser, kind) == identifier))
    if customer is None or not customer.is_verified:
        raise HTTPException(status_code=401, detail="Customer account not found. Verify with OTP first.")
    device = trusted_device(db, device_id=payload.device_id, customer_id=customer.id)
    if device is None:
        raise HTTPException(status_code=401, detail="This device is not trusted. Verify with OTP first.")
    verify_mpin(customer, payload.mpin, db)
    device.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return {"access_token": create_customer_token(customer.id), "customer": {"id": customer.id, "name": customer.name, "age": customer.age, "gender": customer.gender, "email": customer.email, "phone": customer.phone}}


@app.post("/api/customer-auth/complete-mpin")
def complete_customer_mpin(payload: CustomerMpinComplete, db: Session = Depends(get_db)):
    token = decode_access_token(payload.verification_token)
    if token.get("type") != "customer_mpin_verification":
        raise HTTPException(status_code=401, detail="Invalid MPIN verification session")
    customer = db.get(CustomerUser, int(token["sub"]))
    if customer is None or not customer.is_verified:
        raise HTTPException(status_code=401, detail="Customer account not found")
    reset = bool(token.get("reset_mpin"))
    if customer.mpin_hash and not reset:
        verify_mpin(customer, payload.mpin, db)
    else:
        if payload.mpin != payload.confirm_mpin:
            raise HTTPException(status_code=422, detail="MPIN and confirmation do not match")
        if weak_mpin(payload.mpin):
            raise HTTPException(status_code=422, detail="Choose a less predictable MPIN. Avoid repeated digits and simple sequences.")
        customer.mpin_hash = hash_password(payload.mpin)
        customer.mpin_set_at = datetime.now(timezone.utc)
        customer.mpin_failed_attempts = 0
        customer.mpin_locked_until = None
        if reset:
            for item in db.scalars(select(TrustedDeviceSession).where(TrustedDeviceSession.customer_id == customer.id, TrustedDeviceSession.revoked_at.is_(None))):
                item.revoked_at = datetime.now(timezone.utc)
    remember_device(db, device_id=payload.device_id, device_name=payload.device_name, customer_id=customer.id)
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


@app.patch("/api/customer-auth/me")
def update_customer_me(payload: CustomerProfileUpdate, request: Request, db: Session = Depends(get_db)):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Customer login required")
    token = decode_access_token(header[7:])
    if token.get("type") != "customer":
        raise HTTPException(status_code=401, detail="Invalid customer session")
    customer = db.get(CustomerUser, int(token["sub"]))
    if customer is None or not customer.is_verified:
        raise HTTPException(status_code=401, detail="Customer session is no longer valid")
    customer.name = payload.name.strip()
    customer.age = payload.age
    customer.gender = payload.gender
    db.commit()
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
        if settings.environment != "production":
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
    user.mpin_hash = None
    user.mpin_set_at = None
    now = datetime.now(timezone.utc)
    for device in db.scalars(select(TrustedDeviceSession).where(TrustedDeviceSession.staff_user_id == user.id, TrustedDeviceSession.revoked_at.is_(None))):
        device.revoked_at = now
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
    phone = normalize_phone(payload.phone)
    if phone and db.scalar(select(StaffUser.id).where(StaffUser.phone == phone)):
        raise HTTPException(status_code=409, detail="This phone number is already registered")
    owner = StaffUser(shop_id=shop.id, name=payload.owner_name.strip(), email=email, phone=phone, password_hash=hash_password(payload.owner_password), role="owner")
    db.add(owner)
    audit(db, "shop.self_registered", owner, shop.id, f"Owner {email}")
    db.commit()
    db.refresh(owner)
    return staff_session(owner)


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


@app.post("/api/auth/set-mpin")
def set_staff_mpin(payload: MpinSetRequest, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    if staff.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrators must use password or Google sign-in")
    if payload.mpin != payload.confirm_mpin:
        raise HTTPException(status_code=422, detail="MPIN and confirmation do not match")
    if weak_mpin(payload.mpin):
        raise HTTPException(status_code=422, detail="Choose a less predictable MPIN. Avoid repeated digits and simple sequences.")
    if staff.mpin_hash:
        valid_current = bool(payload.current_mpin and verify_password(payload.current_mpin, staff.mpin_hash))
        valid_password = bool(payload.password and verify_password(payload.password, staff.password_hash))
        if not valid_current and not valid_password:
            raise HTTPException(status_code=400, detail="Enter your current MPIN or account password")
    staff.mpin_hash = hash_password(payload.mpin)
    staff.mpin_set_at = datetime.now(timezone.utc)
    staff.mpin_failed_attempts = 0
    staff.mpin_locked_until = None
    if payload.device_id:
        remember_device(db, device_id=payload.device_id, device_name=payload.device_name, staff_user_id=staff.id)
    db.commit()
    return {"message": "MPIN saved. You can use it on this trusted device for 90 days."}


@app.post("/api/auth/logout-all")
def logout_all_staff(staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    for device in db.scalars(select(TrustedDeviceSession).where(TrustedDeviceSession.staff_user_id == staff.id, TrustedDeviceSession.revoked_at.is_(None))):
        device.revoked_at = now
    db.commit()
    return {"message": "Signed out from all trusted devices"}


@app.get("/api/shops/{shop_id}", response_model=ShopOut)
def get_shop(shop_id: int, db: Session = Depends(get_db)):
    shop = db.scalar(select(Shop).options(selectinload(Shop.services), selectinload(Shop.barbers)).where(Shop.id == shop_id))
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    waiting = [item for item in active_queue(db, shop_id) if item.status == QueueStatus.WAITING]
    waits = estimated_waits(db, shop_id)
    ratings = [item.stars for item in shop.ratings]
    return {"id": shop.id, "name": shop.name, "address": shop.address, "phone": shop.phone, "gst_number": shop.gst_number, "slug": shop.slug, "latitude": shop.latitude, "longitude": shop.longitude, "approval_status": shop.approval_status, "average_rating": round(sum(ratings) / len(ratings), 1) if ratings else 0, "rating_count": len(ratings), "timezone": shop.timezone, "opens_at": shop.opens_at, "closes_at": shop.closes_at, "queue_paused": shop.queue_paused, "appointments_enabled": getattr(shop, "appointments_enabled", True), "photo_url": shop.photo_url, "waiting_count": len(waiting), "estimated_wait_minutes": max(waits.values(), default=0), "services": [item for item in shop.services if item.is_active], "barbers": [barber_view(db, item) for item in shop.barbers if item.is_active]}


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
    db.flush()
    # Existing active barbers inherit a newly created service. Owners can then
    # remove it from individual profiles in Team & Staff.
    memberships = db.scalars(select(ShopBarberMembership).where(ShopBarberMembership.shop_id == shop_id, ShopBarberMembership.is_active.is_(True))).all()
    for membership in memberships:
        db.add(BarberServiceAssignment(membership_id=membership.id, service_id=service.id))
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
    user = StaffUser(shop_id=shop_id, barber_id=barber.id if barber else None, barber_profile_id=barber.barber_profile_id if barber else None, name=payload.name.strip(), email=email, phone=phone, password_hash=hash_password(payload.password), role=payload.role, must_change_password=True)
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
    target.mpin_hash = None
    target.mpin_set_at = None
    now = datetime.now(timezone.utc)
    for device in db.scalars(select(TrustedDeviceSession).where(TrustedDeviceSession.staff_user_id == target.id, TrustedDeviceSession.revoked_at.is_(None))):
        device.revoked_at = now
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
    target.barber_profile_id = barber.barber_profile_id if payload.role == "barber" and barber else None
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
    entry = QueueEntry(shop_id=shop_id, customer_id=customer.id if customer else None, service_id=service.id if service else None, service_ids=[service.id] if service else [], service_names=service.name if service else None, total_duration_minutes=service.duration_minutes if service else None, total_price_rupees=service.price_rupees if service else None, barber_id=barber.id if barber else None, barber_profile_id=barber.barber_profile_id if barber else None, customer_name=payload.customer_name.strip(), phone=payload.phone, email=str(payload.email).lower() if payload.email else None, source=payload.source, queue_day=queue_day, daily_token_number=next_token_number)
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
        entry.barber_profile_id = barber.barber_profile_id
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
        assigned = db.get(Barber, entry.barber_id)
        if not barber_provides_services(db, assigned, entry.service_ids or []):
            raise HTTPException(status_code=409, detail="This barber is not assigned to all selected services. Choose another barber or update their services.")
        shop = db.get(Shop, entry.shop_id)
        service_end = now + timedelta(minutes=entry.total_duration_minutes or 20)
        local_day = now.astimezone(shop_zone(shop)).date()
        windows = [(start.astimezone(timezone.utc), end.astimezone(timezone.utc)) for start, end in scheduled_windows(db, shop, assigned, local_day)]
        if windows and not any(start <= now and service_end <= end for start, end in windows):
            raise HTTPException(status_code=409, detail="The complete service does not fit within this barber's current shift.")
        reservation = next_reservation(db, entry.barber_id, now)
        if reservation and service_end > (reservation.scheduled_at if reservation.scheduled_at.tzinfo else reservation.scheduled_at.replace(tzinfo=timezone.utc)):
            raise HTTPException(status_code=409, detail=f"This service would overlap the barber's {reservation.scheduled_at.astimezone(shop_zone(shop)).strftime('%I:%M %p')} appointment. Choose another barber or serve it after the appointment.")
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
    if payload.career_started_on and payload.career_started_on > date.today():
        raise HTTPException(status_code=422, detail="Career start date cannot be in the future")
    shop = db.get(Shop, shop_id)
    profile = BarberProfile(barber_number=new_barber_number(db), full_name=payload.name.strip(), email=str(payload.email).lower() if payload.email else None,
        phone=normalize_phone(payload.phone), career_started_on=payload.career_started_on, biography=payload.biography,
        specialities=payload.specialities, certifications=[])
    db.add(profile)
    db.flush()
    membership = ShopBarberMembership(barber_profile_id=profile.id, shop_id=shop_id, display_name=payload.name.strip(), status="active", is_active=True)
    db.add(membership)
    db.flush()
    barber = Barber(shop_id=shop_id, barber_profile_id=profile.id, membership_id=membership.id, name=payload.name.strip())
    db.add(barber)
    service_ids = payload.service_ids or list(db.scalars(select(Service.id).where(Service.shop_id == shop_id, Service.is_active.is_(True))).all())
    for service_id in service_ids:
        if db.scalar(select(Service.id).where(Service.id == service_id, Service.shop_id == shop_id)):
            db.add(BarberServiceAssignment(membership_id=membership.id, service_id=service_id))
    for weekday in range(7):
        db.add(BarberWeeklyAvailability(membership_id=membership.id, weekday=weekday, starts_at=dt_time.fromisoformat(shop.opens_at), ends_at=dt_time.fromisoformat(shop.closes_at)))
    db.commit()
    db.refresh(barber)
    await manager.queue_changed(shop_id)
    return barber_view(db, barber)


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
    return barber_view(db, barber)


@app.get("/api/barbers/{barber_id}/profile")
def get_barber_profile(barber_id: int, db: Session = Depends(get_db)):
    barber = db.get(Barber, barber_id)
    if barber is None:
        raise HTTPException(status_code=404, detail="Barber not found")
    profile = db.get(BarberProfile, barber.barber_profile_id) if barber.barber_profile_id else None
    membership = db.get(ShopBarberMembership, barber.membership_id) if barber.membership_id else None
    view = barber_view(db, barber)
    view.update({"full_name": profile.full_name if profile else barber.name, "phone": profile.phone if profile else None,
        "email": profile.email if profile else None, "gender": profile.gender if profile else None,
        "career_started_on": profile.career_started_on if profile else None, "biography": profile.biography if profile else None,
        "certifications": profile.certifications or [] if profile else [], "membership_id": membership.id if membership else None,
        "services": list(db.scalars(select(BarberServiceAssignment.service_id).where(BarberServiceAssignment.membership_id == membership.id, BarberServiceAssignment.is_active.is_(True))).all()) if membership else [],
        "weekly_availability": [{"id": row.id, "weekday": row.weekday, "starts_at": row.starts_at.strftime("%H:%M"), "ends_at": row.ends_at.strftime("%H:%M"), "is_active": row.is_active} for row in db.scalars(select(BarberWeeklyAvailability).where(BarberWeeklyAvailability.membership_id == membership.id).order_by(BarberWeeklyAvailability.weekday, BarberWeeklyAvailability.starts_at)).all()] if membership else [],
        "exceptions": [{"id": row.id, "type": row.exception_type, "starts_at": row.starts_at, "ends_at": row.ends_at, "reason": row.reason, "approval_status": row.approval_status} for row in db.scalars(select(BarberAvailabilityException).where(BarberAvailabilityException.membership_id == membership.id).order_by(BarberAvailabilityException.starts_at.desc()).limit(50)).all()] if membership else [],
        "memberships": [{"shop_id": row.shop_id, "shop_name": db.get(Shop, row.shop_id).name, "joined_on": row.joined_on, "left_on": row.left_on, "status": row.status} for row in db.scalars(select(ShopBarberMembership).where(ShopBarberMembership.barber_profile_id == profile.id).order_by(ShopBarberMembership.joined_on.desc())).all()] if profile else []})
    return view


@app.patch("/api/barbers/{barber_id}/profile")
def update_barber_profile(barber_id: int, payload: BarberProfileUpdate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    barber = db.get(Barber, barber_id)
    if barber is None:
        raise HTTPException(status_code=404, detail="Barber not found")
    if not (staff.is_platform_admin or (staff.shop_id == barber.shop_id and staff.role in ("owner", "manager")) or staff.barber_profile_id == barber.barber_profile_id):
        raise HTTPException(status_code=403, detail="You cannot edit this barber profile")
    if payload.career_started_on and payload.career_started_on > date.today():
        raise HTTPException(status_code=422, detail="Career start date cannot be in the future")
    profile = db.get(BarberProfile, barber.barber_profile_id)
    for field, value in payload.model_dump().items():
        setattr(profile, field, str(value).lower() if field == "email" and value else value)
    barber.name = payload.full_name
    db.commit()
    return get_barber_profile(barber_id, db)


@app.put("/api/barbers/{barber_id}/services")
def update_barber_services(barber_id: int, payload: BarberServicesUpdate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    barber = db.get(Barber, barber_id)
    if barber is None or not barber.membership_id:
        raise HTTPException(status_code=404, detail="Barber membership not found")
    require_shop(staff, barber.shop_id); require_owner(staff)
    valid = set(db.scalars(select(Service.id).where(Service.shop_id == barber.shop_id, Service.id.in_(payload.service_ids), Service.is_active.is_(True))).all())
    if valid != set(payload.service_ids):
        raise HTTPException(status_code=422, detail="Choose active services from this shop")
    for row in db.scalars(select(BarberServiceAssignment).where(BarberServiceAssignment.membership_id == barber.membership_id)).all():
        db.delete(row)
    for service_id in payload.service_ids:
        db.add(BarberServiceAssignment(membership_id=barber.membership_id, service_id=service_id))
    db.commit()
    return get_barber_profile(barber_id, db)


@app.put("/api/barbers/{barber_id}/availability")
def update_barber_availability(barber_id: int, payload: WeeklyAvailabilityUpdate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    barber = db.get(Barber, barber_id)
    if barber is None or not barber.membership_id:
        raise HTTPException(status_code=404, detail="Barber membership not found")
    require_shop(staff, barber.shop_id); require_owner(staff)
    for row in db.scalars(select(BarberWeeklyAvailability).where(BarberWeeklyAvailability.membership_id == barber.membership_id)).all():
        db.delete(row)
    for period in payload.periods:
        db.add(BarberWeeklyAvailability(membership_id=barber.membership_id, weekday=period.weekday, starts_at=dt_time.fromisoformat(period.starts_at), ends_at=dt_time.fromisoformat(period.ends_at), is_active=period.is_active))
    db.commit()
    return get_barber_profile(barber_id, db)


@app.post("/api/barbers/{barber_id}/exceptions", status_code=201)
def add_barber_exception(barber_id: int, payload: AvailabilityExceptionCreate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    barber = db.get(Barber, barber_id)
    if barber is None or not barber.membership_id:
        raise HTTPException(status_code=404, detail="Barber membership not found")
    require_shop(staff, barber.shop_id)
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(status_code=422, detail="Exception end must be after its start")
    approval = payload.approval_status if staff.role in ("owner", "manager") else "pending"
    item = BarberAvailabilityException(membership_id=barber.membership_id, exception_type=payload.exception_type, starts_at=payload.starts_at, ends_at=payload.ends_at, reason=payload.reason, approval_status=approval)
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "approval_status": item.approval_status}


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
    if barber.membership_id:
        membership = db.get(ShopBarberMembership, barber.membership_id)
        membership.is_active = False
        membership.status = "ended"
        membership.left_on = date.today()
    audit(db, "barber.deleted", staff, barber.shop_id, f"{barber.id}:{barber.name}")
    db.commit()
    await manager.queue_changed(barber.shop_id)


@app.get("/api/barber-profiles/search")
def search_barber_profile(barber_number: str, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    profile = db.scalar(select(BarberProfile).where(func.upper(BarberProfile.barber_number) == barber_number.strip().upper()))
    if profile is None:
        raise HTTPException(status_code=404, detail="No barber profile was found with this number")
    values = list(db.scalars(select(Rating.barber_stars).where(Rating.barber_profile_id == profile.id, Rating.barber_stars.is_not(None))).all())
    return {"barber_number": profile.barber_number, "full_name": profile.full_name, "photo_url": profile.photo_url,
        "specialities": profile.specialities or [], "experience_years": max(0, date.today().year - profile.career_started_on.year) if profile.career_started_on else 0,
        "career_rating": round(sum(values) / len(values), 1) if values else 0, "career_rating_count": len(values)}


@app.post("/api/shops/{shop_id}/barber-invitations", status_code=201)
def invite_barber(shop_id: int, payload: BarberInvitationCreate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_shop(staff, shop_id); require_owner(staff)
    profile = db.scalar(select(BarberProfile).where(func.upper(BarberProfile.barber_number) == payload.barber_number.strip().upper()))
    if profile is None:
        raise HTTPException(status_code=404, detail="No barber profile was found with this number")
    pending = db.scalar(select(BarberMembershipRequest).where(BarberMembershipRequest.barber_profile_id == profile.id, BarberMembershipRequest.shop_id == shop_id, BarberMembershipRequest.status == "pending"))
    if pending:
        raise HTTPException(status_code=409, detail="An invitation is already pending")
    item = BarberMembershipRequest(barber_profile_id=profile.id, shop_id=shop_id, requested_by_id=staff.id, message=payload.message)
    db.add(item); audit(db, "barber.invited", staff, shop_id, profile.barber_number); db.commit(); db.refresh(item)
    return {"id": item.id, "status": item.status, "barber_number": profile.barber_number}


@app.get("/api/my-barber/invitations")
def my_barber_invitations(staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    if not staff.barber_profile_id:
        return []
    rows = db.scalars(select(BarberMembershipRequest).where(BarberMembershipRequest.barber_profile_id == staff.barber_profile_id).order_by(BarberMembershipRequest.created_at.desc())).all()
    return [{"id": item.id, "shop_id": item.shop_id, "shop_name": db.get(Shop, item.shop_id).name, "status": item.status, "message": item.message, "created_at": item.created_at} for item in rows]


@app.post("/api/barber-invitations/{request_id}/action")
def respond_barber_invitation(request_id: int, payload: MembershipRequestAction, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    item = db.scalar(select(BarberMembershipRequest).where(BarberMembershipRequest.id == request_id).with_for_update())
    if item is None or item.barber_profile_id != staff.barber_profile_id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail="This invitation has already been answered")
    item.status = "approved" if payload.action == "approve" else "rejected"
    item.responded_at = datetime.now(timezone.utc)
    if payload.action == "approve":
        for old in db.scalars(select(ShopBarberMembership).where(ShopBarberMembership.barber_profile_id == item.barber_profile_id, ShopBarberMembership.is_active.is_(True))).all():
            old.is_active = False; old.status = "transferred"; old.left_on = date.today()
            for old_barber in db.scalars(select(Barber).where(Barber.membership_id == old.id)).all():
                old_barber.is_active = False
        profile = db.get(BarberProfile, item.barber_profile_id)
        membership = ShopBarberMembership(barber_profile_id=profile.id, shop_id=item.shop_id, display_name=profile.full_name, status="active", is_active=True)
        db.add(membership); db.flush()
        barber = Barber(shop_id=item.shop_id, barber_profile_id=profile.id, membership_id=membership.id, name=profile.full_name)
        db.add(barber); db.flush()
        shop = db.get(Shop, item.shop_id)
        for service_id in db.scalars(select(Service.id).where(Service.shop_id == item.shop_id, Service.is_active.is_(True))).all():
            db.add(BarberServiceAssignment(membership_id=membership.id, service_id=service_id))
        for weekday in range(7):
            db.add(BarberWeeklyAvailability(membership_id=membership.id, weekday=weekday, starts_at=dt_time.fromisoformat(shop.opens_at), ends_at=dt_time.fromisoformat(shop.closes_at)))
        staff.shop_id, staff.barber_id = item.shop_id, barber.id
    db.commit()
    return {"status": item.status}


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


@app.patch("/api/admin/shops/{shop_id}/appointments-feature", response_model=ShopOut)
def admin_toggle_appointments(shop_id: int, payload: ShopAppointmentsFeatureUpdate, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    require_platform_admin(staff)
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    shop.appointments_enabled = payload.appointments_enabled
    audit(db, "shop.appointments_feature_changed", staff, shop.id, f"appointments_enabled={payload.appointments_enabled}")
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


def available_barbers_for_slot(db: Session, shop_id: int, start: datetime, duration_minutes: int, service_ids: list[int], barber_id: int | None = None) -> list[Barber]:
    shop = db.get(Shop, shop_id)
    return eligible_barbers(db, shop, start, duration_minutes, service_ids, barber_id)


@app.get("/api/shops/{shop_id}/appointment-slots")
def appointment_slots(shop_id: int, appointment_date: date, service_ids: list[int] = Query(default=[]), service_id: int | None = None, barber_id: int | None = None, db: Session = Depends(get_db)):
    shop = db.get(Shop, shop_id)
    unique_service_ids = list(dict.fromkeys(service_ids or ([service_id] if service_id else [])))
    services = list(db.scalars(select(Service).where(Service.id.in_(unique_service_ids))).all()) if unique_service_ids else []
    barber = db.get(Barber, barber_id) if barber_id else None
    if shop is None or len(services) != len(unique_service_ids) or any(service.shop_id != shop_id or not service.is_active for service in services):
        raise HTTPException(status_code=404, detail="Shop or service is unavailable")
    if not getattr(shop, "appointments_enabled", True):
        return {"date": appointment_date.isoformat(), "service_duration_minutes": 0, "slots": []}
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
        available = available_barbers_for_slot(db, shop_id, cursor_utc, duration_minutes, unique_service_ids, barber_id)
        if cursor_utc > now and (barber in available if barber else bool(available)):
            slots.append({"value": cursor.isoformat(), "label": cursor.strftime("%I:%M %p"), "available_barbers": len(available), "barber_names": [item.name for item in available]})
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
    if not getattr(shop, "appointments_enabled", True):
        raise HTTPException(status_code=400, detail="Appointments are not enabled for this shop")
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
    available = available_barbers_for_slot(db, shop_id, payload.scheduled_at.astimezone(timezone.utc), total_duration, service_ids, payload.barber_id)
    if barber and barber not in available:
        raise HTTPException(status_code=409, detail=f"{barber.name} is unavailable for the full {total_duration}-minute booking. Choose another barber or slot.")
    if barber is None:
        if not available:
            raise HTTPException(status_code=409, detail="All barbers are busy during this service slot. Choose another time.")
        barber = available[0]
    customer = optional_customer(request, db)
    item = Appointment(shop_id=shop_id, customer_id=customer.id if customer else None, service_id=service.id, service_ids=service_ids, service_names=service_names, total_duration_minutes=total_duration, total_price_rupees=total_price, barber_id=barber.id if barber else None, barber_profile_id=barber.barber_profile_id if barber else None, customer_name=payload.customer_name.strip(), phone=payload.phone, scheduled_at=payload.scheduled_at.astimezone(timezone.utc), booking_day=booking_day, daily_booking_number=next_booking_number)
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
    barber_profile_id = visit.barber_profile_id
    if not barber_profile_id and visit.barber_id:
        assigned_barber = db.get(Barber, visit.barber_id)
        barber_profile_id = assigned_barber.barber_profile_id if assigned_barber else None
    db.add(Rating(shop_id=visit.shop_id, queue_entry_id=entry.id if entry else None, appointment_id=appointment.id if appointment else None, barber_id=visit.barber_id, barber_profile_id=barber_profile_id, stars=payload.stars, comment=payload.comment, barber_stars=barber_stars, barber_comment=barber_comment))
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
