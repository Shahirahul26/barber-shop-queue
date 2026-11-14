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


def calculate_available_slots_fast(
    db: Session,
    shop: Shop,
    appointment_date: date,
    duration_minutes: int,
    service_ids: list[int],
    barber_id: int | None = None
) -> list[dict]:
    statement = select(Barber).where(Barber.shop_id == shop.id, Barber.is_active.is_(True)).order_by(Barber.id)
    if barber_id:
        statement = statement.where(Barber.id == barber_id)
    barbers = list(db.scalars(statement).all())
    if not barbers:
        return []

    membership_ids = [b.membership_id for b in barbers if b.membership_id]
    barber_services: dict[int, set[int]] = {}
    if membership_ids:
        assignments = list(db.scalars(select(BarberServiceAssignment).where(
            BarberServiceAssignment.membership_id.in_(membership_ids),
            BarberServiceAssignment.is_active.is_(True)
        )).all())
        for a in assignments:
            barber_services.setdefault(a.membership_id, set()).add(a.service_id)

    qualified_barbers = []
    for b in barbers:
        if not b.membership_id:
            qualified_barbers.append(b)
        else:
            assigned = barber_services.get(b.membership_id, set())
            if not assigned or set(service_ids).issubset(assigned):
                qualified_barbers.append(b)

    if not qualified_barbers:
        return []

    shop_timezone = shop_zone(shop)
    opening, closing = shop_window(shop, appointment_date)
    open_utc = opening.astimezone(timezone.utc)
    close_utc = closing.astimezone(timezone.utc)

    barber_weekly: dict[int, list[tuple[datetime, datetime]]] = {}
    if membership_ids:
        weekly_rows = list(db.scalars(select(BarberWeeklyAvailability).where(
            BarberWeeklyAvailability.membership_id.in_(membership_ids),
            BarberWeeklyAvailability.weekday == appointment_date.weekday(),
            BarberWeeklyAvailability.is_active.is_(True)
        ).order_by(BarberWeeklyAvailability.starts_at)).all())
        for row in weekly_rows:
            w_start = datetime.combine(appointment_date, row.starts_at, tzinfo=shop_timezone)
            w_end = datetime.combine(appointment_date, row.ends_at, tzinfo=shop_timezone)
            if w_end <= w_start:
                w_end += timedelta(days=1)
            w_start, w_end = max(w_start, opening), min(w_end, closing)
            if w_start < w_end:
                barber_weekly.setdefault(row.membership_id, []).append((
                    w_start.astimezone(timezone.utc),
                    w_end.astimezone(timezone.utc)
                ))

    barber_extra: dict[int, list[tuple[datetime, datetime]]] = {}
    barber_unavail: dict[int, list[tuple[datetime, datetime]]] = {}
    if membership_ids:
        exceptions = list(db.scalars(select(BarberAvailabilityException).where(
            BarberAvailabilityException.membership_id.in_(membership_ids),
            BarberAvailabilityException.approval_status == "approved",
            BarberAvailabilityException.starts_at < close_utc,
            BarberAvailabilityException.ends_at > open_utc
        )).all())
        for exc in exceptions:
            s_utc = aware(exc.starts_at)
            e_utc = aware(exc.ends_at)
            if exc.exception_type == "extra_hours":
                barber_extra.setdefault(exc.membership_id, []).append((s_utc, e_utc))
            elif exc.exception_type in UNAVAILABLE_EXCEPTIONS:
                barber_unavail.setdefault(exc.membership_id, []).append((s_utc, e_utc))

    cleanup = shop.cleanup_buffer_minutes or 0
    appointments = list(db.scalars(select(Appointment).where(
        Appointment.shop_id == shop.id,
        Appointment.status.in_(ACTIVE_APPOINTMENTS),
        Appointment.scheduled_at < close_utc + timedelta(hours=3),
        Appointment.scheduled_at > open_utc - timedelta(hours=3)
    )).all())
    barber_appts: dict[int, list[tuple[datetime, datetime]]] = {}
    for appt in appointments:
        a_start = aware(appt.scheduled_at)
        a_end = a_start + timedelta(minutes=appt.total_duration_minutes + cleanup)
        barber_appts.setdefault(appt.barber_id, []).append((a_start, a_end))

    serving_entries = list(db.scalars(select(QueueEntry).where(
        QueueEntry.shop_id == shop.id,
        QueueEntry.status == QueueStatus.SERVING
    )).all())
    barber_serving: dict[int, list[tuple[datetime, datetime]]] = {}
    for entry in serving_entries:
        if not entry.barber_id:
            continue
        s_start = aware(entry.started_at or datetime.now(timezone.utc))
        total_m = entry.total_duration_minutes or (entry.service.duration_minutes if entry.service else 20)
        barber_serving.setdefault(entry.barber_id, []).append((s_start, s_start + timedelta(minutes=total_m)))

    now_utc = datetime.now(timezone.utc)
    slots = []
    cursor = opening
    step = timedelta(minutes=duration_minutes)

    while cursor + step <= closing:
        cursor_utc = cursor.astimezone(timezone.utc)
        slot_end_utc = cursor_utc + timedelta(minutes=duration_minutes + cleanup)

        if cursor_utc > now_utc:
            available_barbers = []
            for b in qualified_barbers:
                if not b.membership_id:
                    normal_windows = [(open_utc, close_utc)]
                else:
                    normal_windows = barber_weekly.get(b.membership_id, [])

                extra_windows = barber_extra.get(b.membership_id, []) if b.membership_id else []
                all_allowed = normal_windows + extra_windows

                if not any(a <= cursor_utc and slot_end_utc <= b for a, b in all_allowed):
                    continue

                unavail = barber_unavail.get(b.membership_id, []) if b.membership_id else []
                if any(u_start < slot_end_utc and cursor_utc < u_end for u_start, u_end in unavail):
                    continue

                appts = barber_appts.get(b.id, [])
                if any(apt_start < slot_end_utc and cursor_utc < apt_end for apt_start, apt_end in appts):
                    continue

                serving = barber_serving.get(b.id, [])
                if any(srv_start < slot_end_utc and cursor_utc < srv_end for srv_start, srv_end in serving):
                    continue

                available_barbers.append(b)

            if available_barbers:
                slots.append({
                    "value": cursor.isoformat(),
                    "label": cursor.strftime("%I:%M %p"),
                    "available_barbers": len(available_barbers),
                    "barber_names": [b.name for b in available_barbers]
                })

        cursor += step

    return slots

