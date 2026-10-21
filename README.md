# TrimTime – Barber Queue PWA

TrimTime is a zero-cost-first MVP for managing barber-shop queues. Customers open
the PWA from a shop QR code, inspect the live queue, join it, and track their
position. Staff use a protected dashboard to add walk-ins and advance the queue.

## Stack

- **Backend:** FastAPI, SQLAlchemy and SQLite locally
- **Production database:** PostgreSQL on Supabase's free tier
- **Frontend:** HTML, CSS and vanilla JavaScript PWA
- **Live updates:** FastAPI WebSockets
- **Deployment:** Render/Koyeb-compatible FastAPI service or another free container
- **Notifications:** standards-based Web Push with VAPID

SQLite makes the first phase run without a cloud account. Set `DATABASE_URL` to a
PostgreSQL URL when deploying; no application code needs to change.

The current local configuration uses PostgreSQL database `barber` on
`localhost:5432`, user `postgres`. The application reads the ignored `.env`
file automatically; `.env.example` is only a safe template.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. The demo shop is created automatically. Open the
staff dashboard at <http://127.0.0.1:8000/staff>. Development credentials are
`owner@example.com` and `ChangeMe123!`; production startup rejects this password.

For a phone-based local QR demo, start Uvicorn with `--host 0.0.0.0`, open the
staff dashboard through the computer's LAN address (for example,
`http://192.168.1.20:8000/staff`), and scan the generated QR from the Shop
Details tab. The phone and computer must be on the same Wi-Fi network.

## Test

```powershell
pytest
```

## Phase plan

### Phase 1 – one-shop pilot (implemented)

- One shop and one active queue
- Customer joins using name and service
- Live position and estimated wait
- Staff adds walk-ins, starts, completes, skips or cancels entries
- Installable PWA shell and printable shop QR URL
- SQLite locally, PostgreSQL-ready data layer

### Phase 2 – reliable shop operation (implemented)

- JWT staff authentication with Argon2 password hashing
- Multiple barbers, assignment and barber-aware wait estimates
- Opening hours and queue pause/resume controls
- WebSocket customer/staff updates
- Web Push plus in-page two-ahead and next alerts
- PostgreSQL support and Alembic migrations
- Docker, health checks and production secret validation

See docs/DEPLOYMENT.md for the complete Supabase and Render deployment flow.

### Phase 3 – multi-shop marketplace

- Shop registeion and owner approval
- Nearby-shop search using latitude/longitude
- Appointment slots alongside walk-ins
- Supabase PostgreSQL and object storage
- Notification delivery logs and optional FCM integration
- Analytics and audit logs

### Phase 4 – production and business features

- Payment integration if required
- Plans for shop owners
- Monitoring, backups and rate limiting
- Privacy policy, data deletion and consent management
- Optional native application only after the PWA is validated

## Project map

```text
app/
  main.py          FastAPI routes and application startup
  database.py      SQLAlchemy engine and session lifecycle
  models.py        Database tables
  schemas.py       Request/response validation
  queue_service.py Queue ordering and waiting-time rules
  security.py      Argon2 passwords and JWT authentication
  realtime.py      WebSocket connection manager
  notifications.py Web Push milestone delivery
  static/           PWA HTML, CSS, JavaScript and manifest
tests/
  test_queue.py     Queue API behaviour
docs/
  ARCHITECTURE.md   Detailed frontend/backend explanation
  DEPLOYMENT.md     Supabase and Render deployment runbook
```

