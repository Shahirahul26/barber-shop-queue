from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .models import (Appointment, Barber, BarberAvailabilityException, BarberServiceAssignment,
                     BarberWeeklyAvailability, QueueEntry, QueueStatus, Shop)


ACTIVE_APPOINTMENTS = ("booked", "confirmed", "queued", "serving")
UNAVAILABLE_EXCEPTIONS = ("leave", "unavailable", "emergency", "holiday")


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def shop_zone(shop: Shop):
    try:
        return ZoneInfo(shop.timezone)
    except ZoneInfoNotFoundError:
        return timezone.utc


def shop_window(shop: Shop, day: date) -> tuple[datetime, datetime]:
    zone = shop_zone(shop)
    start = datetime.combine(day, time.fromisoformat(shop.opens_at), tzinfo=zone)
    end = datetime.combine(day, time.fromisoformat(shop.closes_at), tzinfo=zone)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def barber_provides_services(db: Session, barber: Barber, service_ids: list[int]) -> bool:
    if not barber.membership_id:
        return True
    assigned = set(db.scalars(select(BarberServiceAssignment.service_id).where(
        BarberServiceAssignment.membership_id == barber.membership_id,
        BarberServiceAssignment.is_active.is_(True))).all())
    return not assigned or set(service_ids).issubset(assigned)


def scheduled_windows(db: Session, shop: Shop, barber: Barber, day: date) -> list[tuple[datetime, datetime]]:
    opening, closing = shop_window(shop, day)
    if not barber.membership_id:
        return [(opening, closing)]
    rows = list(db.scalars(select(BarberWeeklyAvailability).where(
        BarberWeeklyAvailability.membership_id == barber.membership_id,
        BarberWeeklyAvailability.weekday == day.weekday(),
        BarberWeeklyAvailability.is_active.is_(True)).order_by(BarberWeeklyAvailability.starts_at)).all())
    if not rows:
        return []
    zone = shop_zone(shop)
    windows = []
    for row in rows:
        start = datetime.combine(day, row.starts_at, tzinfo=zone)
        end = datetime.combine(day, row.ends_at, tzinfo=zone)
        if end <= start:
            end += timedelta(days=1)
        start, end = max(start, opening), min(end, closing)
        if start < end:
            windows.append((start, end))
    return windows


def barber_is_available(db: Session, shop: Shop, barber: Barber, start_utc: datetime, duration_minutes: int,
                        service_ids: list[int], ignore_appointment_id: int | None = None) -> bool:
    start_utc, end_utc = aware(start_utc).astimezone(timezone.utc), aware(start_utc).astimezone(timezone.utc) + timedelta(minutes=duration_minutes + (shop.cleanup_buffer_minutes or 0))
    if not barber.is_active or not barber_provides_services(db, barber, service_ids):
        return False
    local_start = start_utc.astimezone(shop_zone(shop))
    normal = [(a.astimezone(timezone.utc), b.astimezone(timezone.utc)) for a, b in scheduled_windows(db, shop, barber, local_start.date())]
    exceptions = []
    if barber.membership_id:
        exceptions = list(db.scalars(select(BarberAvailabilityException).where(
            BarberAvailabilityException.membership_id == barber.membership_id,
            BarberAvailabilityException.approval_status == "approved",
            BarberAvailabilityException.starts_at < end_utc,
            BarberAvailabilityException.ends_at > start_utc)).all())
    extra = [(aware(item.starts_at), aware(item.ends_at)) for item in exceptions if item.exception_type == "extra_hours"]
    if not any(a <= start_utc and end_utc <= b for a, b in normal + extra):
        return False
    if any(aware(item.starts_at) < end_utc and start_utc < aware(item.ends_at) for item in exceptions if item.exception_type in UNAVAILABLE_EXCEPTIONS):
        return False
    statement = select(Appointment).where(Appointment.barber_id == barber.id, Appointment.status.in_(ACTIVE_APPOINTMENTS))
    if ignore_appointment_id:
        statement = statement.where(Appointment.id != ignore_appointment_id)
    for item in db.scalars(statement).all():
        existing_start = aware(item.scheduled_at)
        existing_end = existing_start + timedelta(minutes=item.total_duration_minutes + (shop.cleanup_buffer_minutes or 0))
        if existing_start < end_utc and start_utc < existing_end:
            return False
    for entry in db.scalars(select(QueueEntry).where(QueueEntry.barber_id == barber.id, QueueEntry.status == QueueStatus.SERVING)).all():
        service_start = aware(entry.started_at or datetime.now(timezone.utc))
        total = entry.total_duration_minutes or (entry.service.duration_minutes if entry.service else 20)
        if service_start < end_utc and start_utc < service_start + timedelta(minutes=total):
            return False
    return True


def eligible_barbers(db: Session, shop: Shop, start_utc: datetime, duration_minutes: int, service_ids: list[int], barber_id: int | None = None) -> list[Barber]:
    statement = select(Barber).where(Barber.shop_id == shop.id, Barber.is_active.is_(True)).order_by(Barber.id)
    if barber_id:
        statement = statement.where(Barber.id == barber_id)
    return [barber for barber in db.scalars(statement).all() if barber_is_available(db, shop, barber, start_utc, duration_minutes, service_ids)]


def next_reservation(db: Session, barber_id: int, after: datetime) -> Appointment | None:
    return db.scalar(select(Appointment).where(Appointment.barber_id == barber_id,
        Appointment.status.in_(ACTIVE_APPOINTMENTS), Appointment.scheduled_at >= after).order_by(Appointment.scheduled_at))
