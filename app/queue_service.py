from sqlalchemy import case, select
from sqlalchemy.orm import Session, joinedload
from .models import Barber, QueueEntry, QueueStatus


ACTIVE_STATUSES = (QueueStatus.WAITING, QueueStatus.SERVING)


def active_queue(db: Session, shop_id: int) -> list[QueueEntry]:
    priority_order = case((QueueEntry.source == "appointment", 0), else_=1)
    statement = select(QueueEntry).options(joinedload(QueueEntry.service), joinedload(QueueEntry.barber)).where(QueueEntry.shop_id == shop_id, QueueEntry.status.in_(ACTIVE_STATUSES)).order_by(priority_order, QueueEntry.joined_at, QueueEntry.id)
    return list(db.scalars(statement).all())


def estimated_waits(db: Session, shop_id: int) -> dict[int, int]:
    entries = active_queue(db, shop_id)
    barber_ids = list(db.scalars(select(Barber.id).where(Barber.shop_id == shop_id, Barber.is_active.is_(True))).all())
    if not barber_ids:
        return {entry.id: 0 for entry in entries}
    workloads = {barber_id: 0 for barber_id in barber_ids}
    for entry in entries:
        if entry.status == QueueStatus.SERVING:
            assigned = entry.barber_id if entry.barber_id in workloads else min(workloads, key=workloads.get)
            workloads[assigned] += max(5, entry.service.duration_minutes // 2)
    waits: dict[int, int] = {}
    for entry in (item for item in entries if item.status == QueueStatus.WAITING):
        eligible = entry.barber_id if entry.barber_id in workloads else min(workloads, key=workloads.get)
        waits[entry.id] = workloads[eligible]
        workloads[eligible] += entry.service.duration_minutes
    return waits


def queue_view(db: Session, entry: QueueEntry) -> dict:
    entries = active_queue(db, entry.shop_id)
    waiting = [item for item in entries if item.status == QueueStatus.WAITING]
    waiting_ids = [item.id for item in waiting]
    if entry.status == QueueStatus.WAITING and entry.id in waiting_ids:
        position = waiting_ids.index(entry.id) + 1
        people_ahead = position - 1
        estimated_wait = estimated_waits(db, entry.shop_id).get(entry.id, 0)
    elif entry.status == QueueStatus.SERVING:
        position, people_ahead, estimated_wait = 0, 0, 0
    else:
        position, people_ahead, estimated_wait = None, None, 0
    token = f"B-{entry.appointment_id:03d}" if entry.appointment_id else f"A-{entry.id:03d}"
    return {"id": entry.id, "public_token": entry.public_token, "token": token, "customer_name": entry.customer_name, "email": entry.email, "service_name": entry.service.name, "barber_id": entry.barber_id, "barber_name": entry.barber.name if entry.barber else None, "status": entry.status, "position": position, "people_ahead": people_ahead, "estimated_wait_minutes": estimated_wait, "source": entry.source, "joined_at": entry.joined_at}
