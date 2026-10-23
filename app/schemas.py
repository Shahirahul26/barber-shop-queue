from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from .models import QueueStatus


class LoginRequest(BaseModel):
    identifier: str | None = Field(default=None, min_length=3, max_length=255)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=20)


class CustomerOtpRequest(BaseModel):
    identifier: str = Field(min_length=5, max_length=255)


class CustomerOtpVerify(BaseModel):
    identifier: str = Field(min_length=5, max_length=255)
    otp: str = Field(min_length=6, max_length=6, pattern="^[0-9]{6}$")
    name: str | None = Field(default=None, min_length=2, max_length=100)
    age: int | None = Field(default=None, ge=5, le=110)
    gender: str | None = Field(default=None, pattern="^(male|female|non_binary|prefer_not_to_say)$")
    terms_accepted: bool = False


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=255)


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=20, max_length=255)
    new_password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    shop_id: int
    staff_name: str
    is_platform_admin: bool = False
    must_change_password: bool = False
    role: str
    barber_id: int | None = None


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    duration_minutes: int
    price_rupees: int
    is_active: bool


class ServiceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    duration_minutes: int = Field(ge=5, le=480)
    price_rupees: int = Field(ge=0, le=100000)


class ServiceUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    duration_minutes: int = Field(ge=5, le=480)
    price_rupees: int = Field(ge=0, le=100000)
    is_active: bool


class BarberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    is_active: bool


class BarberCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)


class BarberUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    is_active: bool


class QueueJoin(BaseModel):
    customer_name: str = Field(min_length=2, max_length=100)
    phone: str | None = Field(default=None, min_length=10, max_length=20, pattern="^[0-9+ -]+$")
    email: EmailStr | None = None
    service_id: int | None = None
    service_ids: list[int] | None = None
    barber_id: int | None = None
    source: str = Field(default="online", pattern="^(online|walk_in)$")


class QueueEntryOut(BaseModel):
    id: int
    public_token: str
    token: str
    shop_id: int
    service_id: int | None
    service_ids: list[int]
    customer_name: str
    email: EmailStr | None
    service_name: str
    barber_id: int | None
    barber_name: str | None
    status: QueueStatus
    position: int | None
    people_ahead: int | None
    ahead_label: str
    estimated_wait_minutes: int
    availability_message: str | None
    source: str
    joined_at: datetime


class ShopOut(BaseModel):
    id: int
    name: str
    address: str
    phone: str | None
    gst_number: str | None
    slug: str
    latitude: float | None
    longitude: float | None
    approval_status: str
    average_rating: float
    rating_count: int
    timezone: str
    opens_at: str
    closes_at: str
    queue_paused: bool
    photo_url: str | None
    waiting_count: int
    estimated_wait_minutes: int
    services: list[ServiceOut]
    barbers: list[BarberOut]


class ShopUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=5, max_length=240)
    phone: str | None = Field(default=None, max_length=20)
    gst_number: str | None = Field(default=None, min_length=15, max_length=15, pattern="^[0-9A-Z]{15}$")
    timezone: str = Field(default="Asia/Kolkata", max_length=64)
    opens_at: str = Field(pattern="^([01][0-9]|2[0-3]):[0-5][0-9]$")
    closes_at: str = Field(pattern="^([01][0-9]|2[0-3]):[0-5][0-9]$")


class BannerUpdate(BaseModel):
    software_name: str = Field(min_length=2, max_length=40)
    eyebrow: str = Field(min_length=2, max_length=40)
    title: str = Field(min_length=2, max_length=100)
    message: str = Field(min_length=2, max_length=240)


class StaffCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, min_length=10, max_length=20, pattern="^[0-9+ -]+$")
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="barber", pattern="^(owner|manager|barber|receptionist)$")
    barber_id: int | None = None


class StaffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: EmailStr
    phone: str | None
    role: str
    is_active: bool
    must_change_password: bool
    barber_id: int | None


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class StaffPasswordReset(BaseModel):
    temporary_password: str = Field(min_length=8, max_length=128)


class StaffStatusUpdate(BaseModel):
    is_active: bool


class StaffProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    role: str = Field(pattern="^(owner|manager|barber|receptionist)$")
    barber_id: int | None = None


class StaffAction(BaseModel):
    action: str = Field(pattern="^(start|complete|skip|cancel|restore)$")
    barber_id: int | None = None
    service_id: int | None = None
    service_ids: list[int] | None = Field(default=None, max_length=20)


class CustomerAction(BaseModel):
    public_token: str


class ShopStateUpdate(BaseModel):
    queue_paused: bool


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    public_token: str
    endpoint: str = Field(max_length=1000)
    keys: PushKeys


class AdminShopCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=5, max_length=240)
    phone: str | None = Field(default=None, max_length=20)
    gst_number: str | None = Field(default=None, min_length=15, max_length=15, pattern="^[0-9A-Z]{15}$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    owner_name: str = Field(min_length=2, max_length=100)
    owner_email: EmailStr
    owner_password: str = Field(min_length=8, max_length=128)
    terms_accepted: bool = False


class ApprovalUpdate(BaseModel):
    approval_status: str = Field(pattern="^(pending|approved|suspended)$")


class AppointmentCreate(BaseModel):
    customer_name: str = Field(min_length=2, max_length=100)
    phone: str | None = Field(default=None, min_length=10, max_length=20, pattern="^[0-9+ -]+$")
    service_id: int | None = None
    service_ids: list[int] | None = Field(default=None, min_length=1, max_length=20)
    barber_id: int | None = None
    scheduled_at: datetime


class AppointmentOut(BaseModel):
    id: int
    public_token: str
    token: str
    shop_id: int
    service_id: int
    service_ids: list[int]
    barber_id: int | None
    customer_name: str
    phone: str | None
    service_name: str
    total_duration_minutes: int
    total_price_rupees: int
    barber_name: str | None
    scheduled_at: datetime
    status: str


class AppointmentAction(BaseModel):
    status: str = Field(pattern="^(booked|confirmed|serving|completed|cancelled|no_show)$")


class RatingCreate(BaseModel):
    queue_public_token: str | None = None
    appointment_public_token: str | None = None
    stars: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)
    barber_stars: int | None = Field(default=None, ge=1, le=5)
    barber_comment: str | None = Field(default=None, max_length=500)
