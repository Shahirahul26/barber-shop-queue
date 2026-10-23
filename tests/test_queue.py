import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

os.environ["DATABASE_URL"] = "sqlite:///./test-barber.db"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough"

from fastapi.testclient import TestClient
from app.database import SessionLocal
from app.main import app
from app.models import Appointment, QueueEntry, QueueStatus


def test_phase_two_customer_and_staff_flow():
    Path("test-barber.db").unlink(missing_ok=True)
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "ChangeMe123!"})
        assert login.status_code == 200
        auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

        shop = client.get("/api/shops/1").json()
        created = client.post("/api/shops/1/queue", json={"customer_name": "Rahul", "phone": "9876543210", "email": "rahul.queue@example.com", "service_id": shop["services"][0]["id"], "source": "walk_in"})
        assert created.status_code == 201
        entry = created.json()
        assert entry["public_token"]
        assert entry["email"] == "rahul.queue@example.com"
        assert entry["source"] == "walk_in"

        queue = client.get("/api/shops/1/queue", headers=auth)
        assert queue.status_code == 200

        started = client.post(f"/api/queue/{entry['id']}/action", headers=auth, json={"action": "start", "barber_id": shop["barbers"][0]["id"]})
        assert started.status_code == 200
        assert started.json()["status"] == "serving"

        completed = client.post(f"/api/queue/{entry['id']}/action", headers=auth, json={"action": "complete"})
        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"
        rated = client.post("/api/ratings", json={"queue_public_token": entry["public_token"], "stars": 5, "comment": "Excellent shop", "barber_stars": 4, "barber_comment": "Great haircut"})
        assert rated.status_code == 201
        duplicate = client.post("/api/ratings", json={"queue_public_token": entry["public_token"], "stars": 5, "barber_stars": 5})
        assert duplicate.status_code == 409
        analytics = client.get("/api/shops/1/analytics", headers=auth).json()
        rated_barber = next(item for item in analytics["barbers"] if item["barber_id"] == shop["barbers"][0]["id"])
        assert rated_barber["average_rating"] == 4
        assert rated_barber["review_count"] == 1


def test_queue_pause_blocks_customer_join():
    with TestClient(app) as client:
        token = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "ChangeMe123!"}).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        client.patch("/api/shops/1/state", headers=auth, json={"queue_paused": True})
        shop = client.get("/api/shops/1").json()
        response = client.post("/api/shops/1/queue", json={"customer_name": "Neha", "phone": "9876543211", "service_id": shop["services"][0]["id"]})
        assert response.status_code == 409
        client.patch("/api/shops/1/state", headers=auth, json={"queue_paused": False})


def test_skipped_customer_remains_active_and_moves_to_end():
    with TestClient(app) as client:
        token = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "ChangeMe123!"}).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        shop = client.get("/api/shops/1").json()
        first = client.post("/api/shops/1/queue", json={"customer_name": "Late Customer", "phone": "9876543220", "service_id": shop["services"][0]["id"]}).json()
        skipped = client.post(f"/api/queue/{first['id']}/action", headers=auth, json={"action": "skip"})
        assert skipped.status_code == 200
        assert skipped.json()["status"] == "waiting"
        second = client.post("/api/shops/1/queue", json={"customer_name": "Present Customer", "phone": "9876543221", "service_id": shop["services"][0]["id"]}).json()
        visible = client.get("/api/shops/1/queue", headers=auth).json()
        assert next(index for index, item in enumerate(visible) if item["id"] == first["id"]) < next(index for index, item in enumerate(visible) if item["id"] == second["id"])
        repeated_skip = client.post(f"/api/queue/{first['id']}/action", headers=auth, json={"action": "skip"})
        assert repeated_skip.status_code == 200
        visible = client.get("/api/shops/1/queue", headers=auth).json()
        assert next(index for index, item in enumerate(visible) if item["id"] == second["id"]) < next(index for index, item in enumerate(visible) if item["id"] == first["id"])


def test_platform_admin_creates_shop_with_unique_qr_and_appointment():
    with TestClient(app) as client:
        session = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "ChangeMe123!"}).json()
        assert session["is_platform_admin"] is True
        auth = {"Authorization": f"Bearer {session['access_token']}"}
        created = client.post("/api/admin/shops", headers=auth, json={"name": "Test Studio", "address": "12 Test Road", "phone": "9999999999", "latitude": 19.076, "longitude": 72.8777, "owner_name": "Test Owner", "owner_email": "test-owner@example.com", "owner_password": "StrongPass123!"})
        assert created.status_code == 201
        shop = created.json()
        assert shop["slug"] == "test-studio"
        qr = client.get(f"/api/shops/{shop['id']}/qr")
        assert qr.status_code == 200
        assert qr.headers["content-type"] == "image/png"


def test_staff_password_change_admin_reset_and_account_status():
    with TestClient(app) as client:
        admin_session = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "ChangeMe123!"}).json()
        auth = {"Authorization": f"Bearer {admin_session['access_token']}"}
        created = client.post("/api/shops/1/staff", headers=auth, json={"name": "Queue Staff", "email": "queue-staff@example.com", "phone": "9876500011", "password": "Temporary123!", "role": "receptionist"})
        assert created.status_code == 201
        staff_user = created.json()
        assert staff_user["must_change_password"] is True

        login = client.post("/api/auth/login", json={"email": "queue-staff@example.com", "password": "Temporary123!"})
        assert login.status_code == 200
        assert login.json()["must_change_password"] is True
        staff_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
        blocked_until_changed = client.get("/api/shops/1/queue", headers=staff_auth)
        assert blocked_until_changed.status_code == 403
        changed = client.post("/api/auth/change-password", headers=staff_auth, json={"current_password": "Temporary123!", "new_password": "Permanent123!"})
        assert changed.status_code == 200
        assert client.post("/api/auth/login", json={"email": "queue-staff@example.com", "password": "Permanent123!"}).json()["must_change_password"] is False

        phone_login = client.post("/api/auth/login", json={"identifier": "9876500011", "password": "Permanent123!"})
        assert phone_login.status_code == 200
        forgot = client.post("/api/auth/forgot-password", json={"identifier": "9876500011"})
        assert forgot.status_code == 200
        reset_token = forgot.json()["development_reset_url"].split("reset_token=")[1]
        reset_by_email = client.post("/api/auth/reset-password", json={"token": reset_token, "new_password": "EmailReset123!"})
        assert reset_by_email.status_code == 200
        assert client.post("/api/auth/login", json={"identifier": "9876500011", "password": "EmailReset123!"}).status_code == 200
        assert client.post("/api/auth/reset-password", json={"token": reset_token, "new_password": "CannotReuse123!"}).status_code == 400

        reset = client.patch(f"/api/staff/{staff_user['id']}/password", headers=auth, json={"temporary_password": "ResetPass123!"})
        assert reset.status_code == 200
        assert reset.json()["must_change_password"] is True
        disabled = client.patch(f"/api/staff/{staff_user['id']}/status", headers=auth, json={"is_active": False})
        assert disabled.status_code == 200
        inactive_login = client.post("/api/auth/login", json={"email": "queue-staff@example.com", "password": "ResetPass123!"})
        assert inactive_login.status_code == 403
        assert "inactive" in inactive_login.json()["detail"].lower()


def test_shop_self_registration_barber_permissions_and_appointment_conflict():
    with TestClient(app) as client:
        rejected = client.post("/api/auth/register-shop", json={"name": "Rejected Salon", "address": "45 Market Road", "owner_name": "Salon Owner", "owner_email": "rejected-owner@example.com", "owner_password": "StrongPass123!"})
        assert rejected.status_code == 422
        registered = client.post("/api/auth/register-shop", json={"name": "Self Serve Salon", "address": "45 Market Road", "owner_name": "Salon Owner", "owner_email": "self-owner@example.com", "owner_password": "StrongPass123!", "terms_accepted": True})
        assert registered.status_code == 201
        session = registered.json()
        assert session["role"] == "owner"
        auth = {"Authorization": f"Bearer {session['access_token']}"}
        shop_id = session["shop_id"]

        barber = client.post(f"/api/shops/{shop_id}/barbers", headers=auth, json={"name": "Asha"}).json()
        service = client.post(f"/api/shops/{shop_id}/services", headers=auth, json={"name": "Haircut", "duration_minutes": 30, "price_rupees": 300}).json()
        staff = client.post(f"/api/shops/{shop_id}/staff", headers=auth, json={"name": "Asha", "email": "asha@example.com", "password": "Temporary123!", "role": "barber", "barber_id": barber["id"]})
        assert staff.status_code == 201
        assert staff.json()["barber_id"] == barber["id"]

        appointment_time = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=1)).replace(hour=12, minute=30, second=0, microsecond=0).isoformat()
        slot_date = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=1)).date().isoformat()
        slots = client.get(f"/api/shops/{shop_id}/appointment-slots", params={"appointment_date": slot_date, "service_id": service["id"]})
        assert slots.status_code == 200
        assert slots.json()["service_duration_minutes"] == 30
        assert slots.json()["slots"]
        first = client.post(f"/api/shops/{shop_id}/appointments", json={"customer_name": "First Customer", "phone": "9876543210", "service_id": service["id"], "barber_id": barber["id"], "scheduled_at": appointment_time})
        assert first.status_code == 201
        assert first.json()["token"] == "B01"
        conflict = client.post(f"/api/shops/{shop_id}/appointments", json={"customer_name": "Second Customer", "phone": "9876543211", "service_id": service["id"], "barber_id": barber["id"], "scheduled_at": appointment_time})
        assert conflict.status_code == 409
        assert "unavailable" in conflict.json()["detail"]

        barber_login = client.post("/api/auth/login", json={"email": "asha@example.com", "password": "Temporary123!"}).json()
        barber_auth = {"Authorization": f"Bearer {barber_login['access_token']}"}
        client.post("/api/auth/change-password", headers=barber_auth, json={"current_password": "Temporary123!", "new_password": "Permanent123!"})
        queue_entry = client.post(f"/api/shops/{shop_id}/queue", json={"customer_name": "Walk In", "phone": "9876543212", "service_id": service["id"]}).json()
        started = client.post(f"/api/queue/{queue_entry['id']}/action", headers=barber_auth, json={"action": "start"})
        assert started.status_code == 200
        assert started.json()["barber_id"] == barber["id"]
        completed = client.post(f"/api/queue/{queue_entry['id']}/action", headers=barber_auth, json={"action": "complete"})
        assert completed.status_code == 200
        analytics = client.get(f"/api/shops/{shop_id}/analytics", headers=auth).json()
        assert analytics["barbers"][0]["completed_services"] == 1
        assert analytics["today_revenue_rupees"] == 300
        assert analytics["month_revenue_rupees"] == 300
        assert analytics["daily_revenue"][0]["barbers"][0]["barber_name"] == "Asha"
        cancelled = client.patch(f"/api/appointments/{first.json()['id']}", headers=auth, json={"status": "cancelled"})
        assert cancelled.status_code == 200
        customer_view = client.get(f"/api/my-appointment/{first.json()['public_token']}")
        assert customer_view.status_code == 200
        assert customer_view.json()["status"] == "cancelled"
        visible_appointments = client.get(f"/api/shops/{shop_id}/appointments", headers=auth).json()
        assert all(item["id"] != first.json()["id"] for item in visible_appointments)
        analytics = client.get(f"/api/shops/{shop_id}/analytics", headers=auth, params={"start_date": datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat(), "end_date": slot_date}).json()
        assert analytics["cancelled_appointments"] == 1
        assert analytics["barbers"][0]["cancelled_appointments"] == 1
        outside_hours = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=1)).replace(hour=21, minute=0, second=0, microsecond=0)
        rejected_time = client.post(f"/api/shops/{shop_id}/appointments", json={"customer_name": "Late Customer", "phone": "9876543213", "service_id": service["id"], "barber_id": barber["id"], "scheduled_at": outside_hours.isoformat()})
        assert rejected_time.status_code == 409
        assert "opening hours" in rejected_time.json()["detail"]
        customer_booking_time = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=1)).replace(hour=13, minute=30, second=0, microsecond=0)
        customer_booking = client.post(f"/api/shops/{shop_id}/appointments", json={"customer_name": "Customer Cancel", "phone": "9876543214", "service_id": service["id"], "barber_id": barber["id"], "scheduled_at": customer_booking_time.isoformat()}).json()
        assert customer_booking["token"] == "B02"
        customer_cancelled = client.post("/api/my-appointment/cancel", json={"public_token": customer_booking["public_token"]})
        assert customer_cancelled.status_code == 200
        assert customer_cancelled.json()["status"] == "cancelled"
        next_service_day = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=2)).replace(hour=12, minute=30, second=0, microsecond=0)
        next_day_booking = client.post(f"/api/shops/{shop_id}/appointments", json={"customer_name": "New Day First", "phone": "9876543215", "service_id": service["id"], "barber_id": barber["id"], "scheduled_at": next_service_day.isoformat()})
        assert next_day_booking.status_code == 201
        assert next_day_booking.json()["token"] == "B01"


def test_active_barbers_display_fixed_fifo_rounds_not_workload_lanes():
    with TestClient(app) as client:
        registered = client.post("/api/auth/register-shop", json={"name": "Round Queue Salon", "address": "50 Queue Road", "owner_name": "Round Owner", "owner_email": "round-owner@example.com", "owner_password": "StrongPass123!", "terms_accepted": True}).json()
        auth = {"Authorization": f"Bearer {registered['access_token']}"}
        shop_id = registered["shop_id"]
        barber_one = client.post(f"/api/shops/{shop_id}/barbers", headers=auth, json={"name": "Barber One"}).json()
        barber_two = client.post(f"/api/shops/{shop_id}/barbers", headers=auth, json={"name": "Barber Two"}).json()
        client.post(f"/api/shops/{shop_id}/barbers", headers=auth, json={"name": "Barber Three"})
        service = client.post(f"/api/shops/{shop_id}/services", headers=auth, json={"name": "Standard Cut", "duration_minutes": 30, "price_rupees": 300}).json()

        serving = []
        for number, barber in enumerate((barber_one, barber_two), start=1):
            entry = client.post(f"/api/shops/{shop_id}/queue", json={"customer_name": f"Serving {number}", "phone": f"987650010{number}", "service_id": service["id"], "barber_id": barber["id"], "source": "walk_in"}).json()
            serving.append(client.post(f"/api/queue/{entry['id']}/action", headers=auth, json={"action": "start", "barber_id": barber["id"]}).json())

        waiting_ids = []
        for number in range(1, 8):
            entry = client.post(f"/api/shops/{shop_id}/queue", json={"customer_name": f"Waiting {number}", "phone": f"987650020{number}", "service_id": service["id"], "source": "walk_in"}).json()
            waiting_ids.append(entry["id"])

        queue = client.get(f"/api/shops/{shop_id}/queue", headers=auth).json()
        waiting = [next(item for item in queue if item["id"] == entry_id) for entry_id in waiting_ids]
        assert [item["people_ahead"] for item in waiting] == [0, 0, 0, 1, 1, 1, 2]
        assert all(item["ahead_label"] == "turns ahead" for item in waiting)
        assert [item["token"] for item in queue if item["id"] in waiting_ids] == ["A03", "A04", "A05", "A06", "A07", "A08", "A09"]

        unassigned = client.post(f"/api/shops/{shop_id}/queue", json={"customer_name": "Needs Assignment", "phone": "9876500299"}).json()
        missing_both = client.post(f"/api/queue/{unassigned['id']}/action", headers=auth, json={"action": "start"})
        assert missing_both.status_code == 400
        assert missing_both.json()["detail"] == "Please choose a service and assign a barber before starting"
        missing_barber = client.post(f"/api/queue/{unassigned['id']}/action", headers=auth, json={"action": "start", "service_ids": [service["id"]]})
        assert missing_barber.status_code == 400
        assert missing_barber.json()["detail"] == "Please assign a barber before starting"
        missing_service = client.post(f"/api/queue/{unassigned['id']}/action", headers=auth, json={"action": "start", "barber_id": barber_one["id"]})
        assert missing_service.status_code == 400
        assert missing_service.json()["detail"] == "Please choose at least one service before starting"
        busy_barber = client.post(f"/api/queue/{unassigned['id']}/action", headers=auth, json={"action": "start", "barber_id": barber_one["id"], "service_ids": [service["id"]]})
        assert busy_barber.status_code == 409
        assert "already serving another customer" in busy_barber.json()["detail"]


def test_due_appointment_enters_queue_with_priority_and_stays_linked():
    with TestClient(app) as client:
        session = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "ChangeMe123!"}).json()
        auth = {"Authorization": f"Bearer {session['access_token']}"}
        shop = client.get("/api/shops/1").json()
        walk_in = client.post("/api/shops/1/queue", json={"customer_name": "Walk In First", "phone": "9876543230", "service_id": shop["services"][0]["id"]}).json()
        scheduled_time = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
        booked_response = client.post("/api/shops/1/appointments", json={"customer_name": "Priority Booking", "service_id": shop["services"][0]["id"], "barber_id": shop["barbers"][0]["id"], "scheduled_at": scheduled_time.isoformat()})
        assert booked_response.status_code == 201
        booked = booked_response.json()
        assert booked["phone"] is None
        with SessionLocal() as db:
            appointment = db.get(Appointment, booked["id"])
            service_duration = db.get(QueueEntry, walk_in["id"]).service.duration_minutes
            appointment.scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=service_duration, seconds=-1)
            db.commit()
        queue = client.get("/api/shops/1/queue", headers=auth).json()
        priority = next(item for item in queue if item["customer_name"] == "Priority Booking")
        assert priority["source"] == "appointment"
        assert priority["token"] == booked["token"]
        assert priority["token"].startswith("B")
        assert queue.index(priority) < next(index for index, item in enumerate(queue) if item["id"] == walk_in["id"])
        client.post(f"/api/queue/{priority['id']}/action", headers=auth, json={"action": "start", "barber_id": shop["barbers"][0]["id"]})
        client.post(f"/api/queue/{priority['id']}/action", headers=auth, json={"action": "complete"})
        appointments = client.get("/api/shops/1/appointments", headers=auth).json()
        assert all(item["id"] != booked["id"] for item in appointments)
        with SessionLocal() as db:
            stale_entry = db.get(QueueEntry, walk_in["id"])
            stale_entry.joined_at = datetime.now(timezone.utc) - timedelta(days=1)
            db.commit()
        queue_after_reset = client.get("/api/shops/1/queue", headers=auth).json()
        assert all(item["id"] != walk_in["id"] for item in queue_after_reset)
        with SessionLocal() as db:
            assert db.get(QueueEntry, walk_in["id"]).status == QueueStatus.CANCELLED


def test_staff_appointment_list_hides_past_shop_local_dates():
    with TestClient(app) as client:
        session = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "ChangeMe123!"}).json()
        auth = {"Authorization": f"Bearer {session['access_token']}"}
        shop = client.get("/api/shops/1").json()
        tomorrow = (datetime.now(ZoneInfo(shop["timezone"])) + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
        created = client.post("/api/shops/1/appointments", json={"customer_name": "Old Appointment", "phone": "9876500777", "service_id": shop["services"][0]["id"], "scheduled_at": tomorrow.isoformat()})
        assert created.status_code == 201
        appointment_id = created.json()["id"]
        with SessionLocal() as db:
            appointment = db.get(Appointment, appointment_id)
            appointment.scheduled_at = datetime.now(timezone.utc) - timedelta(days=1)
            db.commit()
        visible = client.get("/api/shops/1/appointments", headers=auth)
        assert visible.status_code == 200
        assert all(item["id"] != appointment_id for item in visible.json())


def test_customer_first_login_otp_terms_and_persistent_session():
    with TestClient(app) as client:
        requested = client.post("/api/customer-auth/request-otp", json={"identifier": "9876500999"})
        assert requested.status_code == 200
        payload = requested.json()
        assert payload["expires_in_seconds"] == 600
        assert payload["first_time"] is True
        rejected = client.post("/api/customer-auth/verify-otp", json={"identifier": "9876500999", "otp": payload["development_otp"], "name": "Verified Customer", "age": 28, "gender": "prefer_not_to_say", "terms_accepted": False})
        assert rejected.status_code == 422
        verified = client.post("/api/customer-auth/verify-otp", json={"identifier": "9876500999", "otp": payload["development_otp"], "name": "Verified Customer", "age": 28, "gender": "prefer_not_to_say", "terms_accepted": True})
        assert verified.status_code == 200
        token = verified.json()["access_token"]
        me = client.get("/api/customer-auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["name"] == "Verified Customer"
        customer_auth = {"Authorization": f"Bearer {token}"}
        shop = client.get("/api/shops/1").json()
        visit = client.post("/api/shops/1/queue", headers=customer_auth, json={"customer_name": "Verified Customer", "phone": "9876500999", "service_id": shop["services"][0]["id"]})
        assert visit.status_code == 201
        owner = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "ChangeMe123!"}).json()
        owner_auth = {"Authorization": f"Bearer {owner['access_token']}"}
        client.post(f"/api/queue/{visit.json()['id']}/action", headers=owner_auth, json={"action": "start", "barber_id": shop["barbers"][0]["id"]})
        client.post(f"/api/queue/{visit.json()['id']}/action", headers=owner_auth, json={"action": "complete"})
        history = client.get("/api/customer-auth/history", headers=customer_auth)
        assert history.status_code == 200
        assert history.json()[0]["service"] == shop["services"][0]["name"]
        assert history.json()[0]["barber"] == shop["barbers"][0]["name"]
