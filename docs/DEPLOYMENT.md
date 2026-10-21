# Production deployment: Supabase PostgreSQL + Render

This is the simplest zero-cost pilot deployment. The application is one Docker
service and one external PostgreSQL database. HTTPS, WebSockets and the public URL
are handled by Render.

> Free compute is suitable for a pilot, not a service-level-guaranteed production
> system. Render's free web service sleeps after 15 idle minutes. Upgrade the
> compute plan before promising instant availability to paying shops.

## 1. Create a Supabase PostgreSQL database

1. Create a project at supabase.com.
2. Save the generated database password in a password manager.
3. In the project dashboard, click Connect.
4. Select Session pooler. This works over IPv4 and suits a persistent FastAPI
   container.
5. Copy the complete URI and replace the password placeholder.
6. Percent-encode reserved characters in the password. For example, # becomes %23.
7. Keep the URI secret. It becomes the Render DATABASE_URL.

The application converts postgresql:// automatically to SQLAlchemy's
postgresql+psycopg:// driver.

## 2. Generate application secrets

Generate a JWT secret:

    [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))

Generate Web Push VAPID keys:

    npx web-push generate-vapid-keys

Save both VAPID values. The public key is safe for the browser. The private key
must only exist in the hosting environment.

Choose a unique owner password of at least 12 characters. The startup process
creates the initial owner only when that email does not already exist.

## 3. Put the project in GitHub

From the project directory:

    git init
    git add .
    git commit -m "Build TrimTime phase 2"
    git branch -M main
    git remote add origin https://github.com/YOUR-NAME/trimtime.git
    git push -u origin main

Confirm that .env, database files and the virtual environment are not committed.
Never paste secrets into render.yaml.

## 4. Deploy the FastAPI service on Render

1. Sign in to Render and select New, then Blueprint.
2. Connect the GitHub repository.
3. Render detects render.yaml and the Dockerfile.
4. Choose the free web-service plan for the pilot.
5. Enter these secret environment variables:

| Variable | Value |
|---|---|
| DATABASE_URL | Supabase Session Pooler URI |
| ADMIN_EMAIL | Real shop-owner email |
| ADMIN_PASSWORD | Unique initial password |
| ALLOWED_HOSTS | Assigned host, such as trimtime-api.onrender.com |
| VAPID_PUBLIC_KEY | Generated public VAPID key |
| VAPID_PRIVATE_KEY | Generated private VAPID key |
| VAPID_SUBJECT | mailto:your-real-email@example.com |

SECRET_KEY is generated automatically by the Blueprint. ENVIRONMENT is already
set to production.

6. Deploy. The container runs Alembic migrations, seeds the first owner and then
starts Uvicorn. Migrations finish before the server accepts traffic.

## 5. Verify the deployment

    Invoke-RestMethod https://YOUR-HOST/health

Expected result: {"status":"ok","version":"0.2.0"}

Then verify this complete flow:

1. Open https://YOUR-HOST/staff and log in.
2. In a second browser or phone, open https://YOUR-HOST.
3. Join the queue and enable browser notifications.
4. Confirm the staff board updates immediately through WebSockets.
5. Assign a barber and click Start.
6. Confirm the customer's ticket changes and a notification is received.
7. Click Complete and confirm the queue advances.
8. Pause the queue and verify that a new customer cannot join.
9. Resume it and repeat the join.

## 6. Produce the shop QR code

The QR target is the HTTPS customer URL. Generate it with:

    npx qrcode -o shop-qr.png "https://YOUR-HOST/"

Print it at least 4 cm square and test it on both Android and iPhone.

## 7. Domain and DNS

Render provides a free onrender.com URL. A custom domain costs whatever the
registrar charges. Add the domain in Render, configure the displayed DNS record,
add the hostname to ALLOWED_HOSTS and use the final HTTPS URL in the QR.

## 8. Database and release operations

Create future migrations locally:

    alembic revision --autogenerate -m "describe change"
    alembic upgrade head

Commit migration files with the code. Before a schema release, export a backup,
review and test the migration, deploy at low traffic, then test health, login,
joining and queue advancement.

## 9. Production checklist

- Keep all secrets out of Git.
- Restrict ALLOWED_HOSTS to actual domains.
- Enable database backups suitable for the business.
- Add external uptime monitoring for /health.
- Review logs after every deployment.
- Retain customer data only as long as the privacy policy permits.
- Obtain consent before notifications.
- Add shared Redis rate limiting before a high-volume launch.
- Upgrade from free hosting before promising availability.

## Deployed architecture

    Customer/Staff browser
            | HTTPS + WSS
            v
    Render FastAPI container
      - JWT authentication
      - queue rules
      - WebSocket broadcasts
      - Web Push sender
      - Alembic migrations
            | TLS PostgreSQL
            v
    Supabase PostgreSQL
