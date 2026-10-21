# Architecture and code walkthrough

## Request flow

```text
Customer PWA ──HTTP JSON──> FastAPI routes ──> Queue service ──> SQLAlchemy ──> Database
      ↑                            │                                      │
      └──── five-second refresh ───┴──────── customer-safe result ───────┘
```

The frontend never connects directly to the database. FastAPI validates every
request, applies queue rules and returns only the fields that screen needs.

## Backend, file by file

### `database.py`

1. `DATABASE_URL` reads the production database address from the environment.
2. If it is absent, the app uses the local `barber-phase2.db` SQLite file.
3. `create_engine` owns database connections.
4. `SessionLocal` creates one unit of database work per HTTP request.
5. `Base` is inherited by every database model.
6. `get_db` opens a session, yields it to a route and closes it even on failure.

### `models.py`

1. `QueueStatus` limits records to known lifecycle states.
2. `Shop` owns services and queue entries.
3. `Service` stores both price and expected duration. Duration drives estimates.
4. `QueueEntry` stores one customer's place and timestamps every lifecycle step.
5. Foreign keys prevent a queue entry from pointing at a missing shop or service.

### `schemas.py`

Pydantic schemas form the API boundary. `QueueJoin` rejects blank names, unknown
source values and oversized input before business logic executes. Output schemas
prevent private fields such as phone numbers and password hashes from leaking.

### `queue_service.py`

`active_queue` always orders entries by join time and then ID. The ID tie-breaker
makes ordering deterministic when two users join within the same timestamp.

`queue_view` calculates position from the current database state rather than
storing a fragile position number. The Phase 2 estimator distributes waiting
services across active barbers and respects a customer's preferred barber.

### `main.py`

1. `lifespan` creates local tables and seed data when the app starts.
2. `app.mount` exposes frontend assets under `/static`.
3. Page routes return the customer or staff HTML shell.
4. `GET /api/shops/{id}` returns public shop data and summary counts.
5. `POST /api/shops/{id}/queue` validates the selected service and creates an entry.
6. `GET /api/my-queue/{public_token}` recalculates a customer's latest position
   without exposing a predictable numeric booking URL.
7. Staff queue access and mutations require a signed JWT and matching shop.
8. An action changes status, records timestamps, broadcasts over WebSockets and
   evaluates notification milestones.

## Frontend, file by file

### `index.html`

This contains semantic page structure only: the live shop summary, join form and
ticket. The ticket starts hidden and becomes visible after a successful booking.

### `app.js`

1. `api` is the single JSON request helper and converts API failures into errors.
2. `loadShop` refreshes public queue totals and creates service options.
3. The submit listener serializes the form and calls the join endpoint.
4. A random public token is saved in `localStorage`, so refreshing retains a ticket
   without exposing credentials or relying on an easily guessed numeric ID.
5. `refreshTicket` fetches the current position every five seconds.
6. The service worker is registered when the browser supports it.

### `staff.js`

1. `loadQueue` sends the staff bearer token and receives the active queue.
2. `render` builds cards using DOM operations and escapes customer text.
3. Action buttons call one protected backend endpoint.
4. A timer refreshes the board every five seconds.

### PWA files

`manifest.webmanifest` lets supported browsers install the website. `sw.js` caches
the frontend shell for basic offline loading; API requests deliberately remain
network-only because stale queue information would be dangerous.

## Phase 2 implementation

Staff authenticate with Argon2 password hashes and signed JWT access tokens.
Barbers are modeled separately and assigned before service starts. WebSocket
channels broadcast queue changes without polling. Web Push subscriptions are tied
to random customer queue tokens, and notification timestamps prevent duplicate
two-ahead and next alerts.

## PostgreSQL deployment

Create a free Supabase project, copy its PostgreSQL connection string and set it as
`DATABASE_URL` in the hosting dashboard. Production should use SSL and Alembic
migrations. Never put the database password, staff secrets or notification private
keys in JavaScript or commit them to Git.

