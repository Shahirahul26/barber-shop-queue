from datetime import datetime, timezone

from sqlalchemy import and_, case, select
from sqlalchemy.orm import Session, joinedload

from .models import Barber, QueueEntry, QueueStatus


ACTIVE_STATUSES = (QueueStatus.WAITING, QueueStatus.SERVING)


def active_queue(db: Session, shop_id: int) -> list[QueueEntry]:
    priority_order = case(
        (and_(QueueEntry.source == "appointment", QueueEntry.priority_active.is_(True)), 0), else_=1
    )
    statement = (
        select(QueueEntry)
        .options(joinedload(QueueEntry.service), joinedload(QueueEntry.barber), joinedload(QueueEntry.appointment))
        .where(QueueEntry.shop_id == shop_id, QueueEntry.status.in_(ACTIVE_STATUSES))
        .order_by(priority_order, QueueEntry.joined_at, QueueEntry.id)
    )
    return list(db.scalars(statement).all())


def entry_duration(entry: QueueEntry) -> int:
    if entry.total_duration_minutes:
        return entry.total_duration_minutes
    if entry.appointment and entry.appointment.total_duration_minutes:
        return entry.appointment.total_duration_minutes
    return entry.service.duration_minutes if entry.service else 20


def queue_metrics(db: Session, shop_id: int) -> tuple[dict[int, dict], int]:
    """Simulate the continuously moving queue over the active barber lanes."""
    entries = active_queue(db, shop_id)
    barber_ids = list(db.scalars(select(Barber.id).where(
        Barber.shop_id == shop_id, Barber.is_active.is_(True)
    ).order_by(Barber.id)).all())
    if not barber_ids:
        return ({entry.id: {"wait": 0, "ahead": 0, "message": "Service temporarily unavailable"}
                 for entry in entries}, 0)

    workloads = {barber_id: 0 for barber_id in barber_ids}
    customers_before = {barber_id: 0 for barber_id in barber_ids}
    now = datetime.now(timezone.utc)

    # Serving customers contribute remaining time, but not a displayed turn.
    for entry in entries:
        if entry.status != QueueStatus.SERVING:
            continue
        assigned = entry.barber_id if entry.barber_id in workloads else min(
            workloads, key=lambda barber_id: (workloads[barber_id], barber_id)
        )
        remaining = entry_duration(entry)
        if entry.started_at:
            started_at = entry.started_at if entry.started_at.tzinfo else entry.started_at.replace(tzinfo=timezone.utc)
            elapsed = max(0, int((now - started_at).total_seconds() // 60))
            remaining = max(1, remaining - elapsed)
        else:
            remaining = max(5, remaining // 2)
        workloads[assigned] += remaining

    metrics: dict[int, dict] = {}
    waiting_index = 0
    for entry in (item for item in entries if item.status == QueueStatus.WAITING):
        if entry.barber_id is not None and entry.barber_id not in workloads:
            metrics[entry.id] = {"wait": 0, "ahead": 0,
                                 "message": "Selected barber unavailable - reassignment required"}
            continue
        eligible_ids = [entry.barber_id] if entry.barber_id is not None else barber_ids
        assigned = min(eligible_ids, key=lambda barber_id: (workloads[barber_id], barber_id))
        # Any-barber customers display stable FIFO service rounds. Barber-specific
        # customers display only the work queued on their selected barber's lane.
        ahead = waiting_index // len(barber_ids) if entry.barber_id is None else customers_before[assigned]
        metrics[entry.id] = {"wait": workloads[assigned], "ahead": ahead, "message": None}
        workloads[assigned] += entry_duration(entry)
        customers_before[assigned] += 1
        waiting_index += 1
    return metrics, len(barber_ids)


def estimated_waits(db: Session, shop_id: int) -> dict[int, int]:
    metrics, _ = queue_metrics(db, shop_id)
    return {entry_id: values["wait"] for entry_id, values in metrics.items()}


def queue_view(db: Session, entry: QueueEntry) -> dict:
    entries = active_queue(db, entry.shop_id)
    waiting_ids = [item.id for item in entries if item.status == QueueStatus.WAITING]
    metrics, active_barber_count = queue_metrics(db, entry.shop_id)
    ahead_label = "turns ahead" if active_barber_count > 1 else "people ahead"
    availability_message = None
    if entry.status == QueueStatus.WAITING and entry.id in waiting_ids:
        position = waiting_ids.index(entry.id) + 1
        entry_metrics = metrics.get(entry.id, {"wait": 0, "ahead": 0, "message": None})
        people_ahead = entry_metrics["ahead"]
        estimated_wait = entry_metrics["wait"]
        availability_message = entry_metrics["message"]
    elif entry.status == QueueStatus.SERVING:
        position, people_ahead, estimated_wait = 0, 0, 0
    else:
        position, people_ahead, estimated_wait = None, None, 0

    token = f"B{(entry.appointment.daily_booking_number or entry.appointment.id):02d}" if entry.appointment_id else f"A{(entry.daily_token_number or entry.id):02d}"
    service_name = entry.service_names or (entry.appointment.service_names if entry.appointment and entry.appointment.service_names else entry.service.name if entry.service else "Service not assigned")
    service_ids = entry.service_ids or (entry.appointment.service_ids if entry.appointment else ([entry.service_id] if entry.service_id else []))
    return {"id": entry.id, "public_token": entry.public_token, "token": token, "shop_id": entry.shop_id,
            "service_id": entry.service_id, "service_ids": service_ids, "customer_name": entry.customer_name,
            "email": entry.email, "service_name": service_name, "barber_id": entry.barber_id,
            "barber_name": entry.barber.name if entry.barber else None, "status": entry.status,
            "position": position, "people_ahead": people_ahead, "ahead_label": ahead_label,
            "estimated_wait_minutes": estimated_wait, "availability_message": availability_message,
            "source": entry.source, "joined_at": entry.joined_at}
