# marcle.ai

Public homelab operations dashboard and **ask.marcle.ai** Q&A app. Self-hosted, no frameworks, zero build step.

## Structure

```
├── frontend/                Static sites served by nginx
│   ├── index.html           Status dashboard
│   ├── admin.html           Admin panel
│   ├── styles.css           Shared design system
│   └── ask/                 Ask app (HTML/CSS/JS)
├── backend/                 FastAPI application
│   └── app/
│       ├── main.py          Status API + refresh loop
│       ├── routers/ask.py   Ask API (auth, questions, answers)
│       ├── ask_db.py        SQLite schema + connections
│       └── ask_services/    Google OAuth, Discord webhook, SMTP email
├── data/                    Runtime state (mounted volume)
│   ├── services.json        Service definitions
│   ├── observations.json    Incident tracking
│   ├── audit.log            Admin audit trail
│   └── ask.db               Ask app database
├── docker-compose.yml       Container orchestration
└── .env.example             All environment variables
```

## Quick Start

```bash
cp .env.example .env
# Fill in values — service URLs, admin token, and Ask app config

docker compose up --build
```

| Page | URL |
|------|-----|
| Status Dashboard | `http://localhost:9182` |
| Ask App | `http://localhost:9182/ask` |
| Admin Panel | `http://localhost:9182/admin` |
| API | `http://localhost:9182/api/status` |

Backend port `8000` is internal-only.

## Status Dashboard

Plain HTML + CSS + vanilla JS. No build step.

The dashboard polls `/api/status` and `/api/overview` every 60 seconds for service tiles, overview widgets, incident banners, and a service detail drawer. Checks run in a background loop every `REFRESH_INTERVAL_SECONDS` (default `30`) with `MAX_CONCURRENCY` (default `10`) concurrent checks.

## Ask App

The Ask app (`/ask`) lets authenticated users submit questions to Marc.

**How it works:**
1. User signs in with Google OAuth2.
2. User submits a question (costs Marcle Points).
3. Question is posted to a Discord channel via webhook.
4. Marc answers in Discord, then calls the answer endpoint.
5. User receives the answer by email.

**Key features:**
- Google OAuth2 with CSRF-safe sessions (`SameSite=Lax`, `HttpOnly` cookies)
- Marcle Points system (configurable starting balance and cost per question)
- Atomic points decrement with DB-level `CHECK (points >= 0)` constraint
- Rate limiting (5 questions per user per 60 seconds)
- Discord webhook with rich embeds and inline answer instructions
- HTML + plain text email delivery
- Admin endpoints for user management and points adjustment

**Designed for future integration** with n8n workflows and local LLM answering.

### Ask Environment Variables

| Variable | Purpose |
|----------|---------|
| `GOOGLE_CLIENT_ID` | Google OAuth2 client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth2 client secret |
| `GOOGLE_REDIRECT_URL` | OAuth callback URL (`http://localhost:9182/api/ask/auth/callback`) |
| `SESSION_SECRET` | Secret for session token generation |
| `DISCORD_WEBHOOK_URL` | Discord channel webhook for question notifications |
| `SMTP_HOST` / `PORT` / `USER` / `PASS` / `FROM` | SMTP config for answer emails |
| `ASK_ANSWER_WEBHOOK_SECRET` | Shared secret for the answer endpoint |
| `DEFAULT_STARTING_POINTS` | Points given to new users (default `10`) |
| `POINTS_PER_QUESTION` | Points deducted per question (default `1`) |
| `BASE_PUBLIC_URL` | Public URL for redirects and Discord messages |
| `ASK_DB_PATH` | SQLite database path (default `/data/ask.db`) |

## API Reference

### Public (no auth)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/status` | Current service statuses |
| `GET` | `/api/overview` | Dashboard metadata (counts, cache age, last incident) |
| `GET` | `/api/incidents?limit=50` | Recent incident transitions |
| `GET` | `/api/services/{id}` | Service detail + recent incidents |
| `GET` | `/healthz` | Health probe |

### Admin (`Authorization: Bearer <ADMIN_TOKEN>`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/admin/services` | List all services with credential flags |
| `POST` | `/api/admin/services` | Create service |
| `PUT` | `/api/admin/services/{id}` | Upsert service |
| `DELETE` | `/api/admin/services/{id}` | Delete service |
| `POST` | `/api/admin/services/{id}/toggle` | Toggle enabled |
| `POST` | `/api/admin/services/bulk` | Bulk enable/disable |
| `GET` | `/api/admin/audit?limit=200` | Audit log |
| `GET` | `/api/admin/notifications` | Notification config |
| `PUT` | `/api/admin/notifications` | Update notifications |
| `POST` | `/api/admin/notifications/test` | Test notifications |

### Ask — User (session cookie via Google OAuth)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/ask/auth/login` | Redirect to Google OAuth |
| `GET` | `/api/ask/auth/callback` | OAuth callback (sets session cookie) |
| `POST` | `/api/ask/auth/logout` | Clear session |
| `GET` | `/api/ask/me` | Current user + points balance |
| `POST` | `/api/ask/questions` | Submit question (costs points, posts to Discord) |
| `GET` | `/api/ask/questions` | List user's questions |

### Ask — Answer Webhook (`X-Webhook-Secret` header)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/ask/answers` | Submit answer → marks answered + emails user |

### Ask — Admin (`Authorization: Bearer <ADMIN_TOKEN>`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/ask/admin/users` | List all users |
| `POST` | `/api/ask/admin/points` | Adjust user point balance |

## Service Configuration

`services.json` stores non-secret service metadata. Auth is configured via `auth_ref` pointing to environment variable names:

```json
{
  "id": "proxmox",
  "name": "Proxmox",
  "group": "core",
  "url": "https://pve.local:8006",
  "check_type": "proxmox",
  "enabled": true,
  "auth_ref": { "scheme": "bearer", "env": "PROXMOX_API_TOKEN" }
}
```

**Auth schemes:** `none`, `bearer`, `basic`, `header`, `query_param`

Never put secrets in `services.json`. Set values only in `.env` or container environment.

## Status Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `ADMIN_TOKEN` | — | Admin API access (required to enable admin endpoints) |
| `REFRESH_INTERVAL_SECONDS` | `30` | Background check cadence |
| `REQUEST_TIMEOUT_SECONDS` | `4` | Per-check HTTP timeout |
| `MAX_CONCURRENCY` | `10` | In-flight checks per cycle |
| `EXPOSE_SERVICE_URLS` | `false` | Include URLs in public API responses |
| `FLAP_WINDOW_SECONDS` | `600` | Flapping detection lookback window |
| `FLAP_THRESHOLD` | `3` | Transitions in window to trigger flapping |

## Running Locally (without Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Deployment

Designed for Cloudflare Tunnel — no inbound ports, TLS handled by the tunnel.

```
Internet → Cloudflare Tunnel → nginx (:80 container, :9182 host)
                                ├── /         → status dashboard
                                ├── /ask      → ask.marcle.ai
                                ├── /admin    → admin panel
                                └── /api/*    → backend (uvicorn :8000)
```

In production:
- Keep `/admin` behind Cloudflare Access
- Always require `Authorization: Bearer <ADMIN_TOKEN>` at the backend
- Route `ask.marcle.ai` via Cloudflare Tunnel to the same nginx container
- Generate strong values for `SESSION_SECRET` and `ASK_ANSWER_WEBHOOK_SECRET`
