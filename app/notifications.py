import json
from datetime import datetime, timezone

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from .config import settings
from .models import PushSubscription, QueueStatus
from .queue_service import active_queue, queue_view


def notify_queue_milestones(db: Session, shop_id: int) -> None:
    if not settings.vapid_private_key:
        return
    changed = False
    for entry in active_queue(db, shop_id):
        if not entry.push_subscriptions:
            continue
        view = queue_view(db, entry)
        if view["availability_message"]:
            continue
        title = body = None
        if entry.status == QueueStatus.SERVING and entry.next_notified_at is None:
            title, body = "Your barber is ready", "Please proceed to the chair."
            entry.next_notified_at = datetime.now(timezone.utc)
        elif view["people_ahead"] == 0 and entry.next_notified_at is None:
            title, body = "You are next", "Please reach the shop now."
            entry.next_notified_at = datetime.now(timezone.utc)
        elif view["people_ahead"] is not None and view["people_ahead"] <= 2 and entry.two_ahead_notified_at is None:
            unit = "turns" if view["ahead_label"] == "turns ahead" else "customers"
            title, body = f"Only two {unit} left", "Get ready to leave for the shop."
            entry.two_ahead_notified_at = datetime.now(timezone.utc)
        if not body:
            continue
        delivered = False
        for subscription in list(entry.push_subscriptions):
            try:
                webpush(
                    subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
                    data=json.dumps({"title": title, "body": body, "url": "/"}),
                    vapid_private_key=settings.vapid_private_key,
                    vapid_claims={"sub": settings.vapid_subject},
                    timeout=5,
                )
                delivered = True
            except WebPushException as exc:
                if getattr(exc.response, "status_code", None) in (404, 410):
                    db.delete(subscription)
        changed = changed or delivered
    if changed:
        db.commit()
