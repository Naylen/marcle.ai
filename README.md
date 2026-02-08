# marcle.ai

Public, read-only homelab operations dashboard with a protected runtime admin API and **ask.marcle.ai** Q&A sub-app.

## Structure

```
├── frontend/          Static landing page + admin UI (HTML/CSS/JS, nginx)
│   └── ask/           Ask app frontend (HTML/CSS/JS)
├── backend/           Status/admin/ask API (Python, FastAPI)
│   └── app/
│       ├── routers/ask.py       Ask API router
│       ├── ask_db.py            SQLite schema + connection
│       └── ask_services/        Google OAuth, Discord webhook, email
├── data/              Runtime data (services.json, ask.db, etc.)
├── docker-compose.yml Local dev stack
└── .env.example       Required environment variables
```

## Quick Start

```bash
cp .env.example .env
# Fill in service URLs, secrets, and Ask app config (Google OAuth, Discord, SMTP)

docker compose up --build
```

Status Dashboard: `http://localhost:9182`
Ask App: `http://localhost:9182/ask`
API (via nginx proxy): `http://localhost:9182/api/status`
Admin UI: `http://localhost:9182/admin`
Backend container port `8000` is internal-only by default in `docker-compose.yml`.

## Frontend

Plain HTML + CSS + minimal JS. No build step. No frameworks.
- Public dashboard fetches `/api/status` and `/api/overview` for service tiles, overview widgets, incident banner, and service detail drawer.
- Admin dashboard uses bearer token auth for runtime service management, bulk enable/disable, health preview, and audit log viewing.

To point the frontend at a different API origin, set `window.MARCLE_API_BASE` before the script loads, or configure your reverse proxy to route `/api/*` to the backend.

## Backend

### Running locally (without Docker)

PowerShell:
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Bash:
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### API

Public endpoints:
- `GET /api/status`
- `GET /api/overview`
- `GET /api/incidents?limit=50`
- `GET /api/services/{id}`

Admin endpoints (require `Authorization: Bearer <ADMIN_TOKEN>`):
- `GET /api/admin/services`
- `GET /api/admin/audit?limit=200`
- `GET /api/admin/notifications`
- `PUT /api/admin/notifications`
- `POST /api/admin/notifications/test`
- `POST /api/admin/services`
- `PUT /api/admin/services/{service_id}`
- `DELETE /api/admin/services/{service_id}`
- `POST /api/admin/services/{service_id}/toggle`
- `POST /api/admin/services/bulk`

`/api/status` returns normalized status for enabled services from `services.json`.
Checks run in a background loop and `/api/status` returns the latest in-memory payload immediately.
The loop runs every `REFRESH_INTERVAL_SECONDS` (default `30`) with `MAX_CONCURRENCY` (default `10`) and per-check timeout `REQUEST_TIMEOUT_SECONDS` (default `4`).
`/api/overview` returns derived dashboard metadata (counts, cache age, last incident, and per-service last-changed info).
`/api/incidents` returns recent incident transitions (most recent first).
`/api/services/{id}` returns service detail + recent incidents for drawer views.

Ask endpoints (require Google OAuth session cookie):
- `GET /api/ask/auth/login` — redirect to Google OAuth
- `GET /api/ask/auth/callback` — OAuth callback
- `POST /api/ask/auth/logout` — clear session
- `GET /api/ask/me` — current user + points balance
- `POST /api/ask/questions` — submit question (costs points, posts to Discord)
- `GET /api/ask/questions` — list user's questions

Ask answer webhook (require `X-Webhook-Secret` header):
- `POST /api/ask/answers` — submit answer, emails user

Ask admin (require `Authorization: Bearer <ADMIN_TOKEN>`):
- `GET /api/ask/admin/users` — list all users
- `POST /api/ask/admin/points` — adjust user point balance

### Runtime Service Config (`services.json`)

`services.json` stores only non-secret service metadata.

Operational dashboard metadata is persisted separately in `observations.json`
(default `/data/observations.json`) and contains only status transitions:
`services.<id>.last_status`, `last_changed_at`, `last_seen_at`, and
global `last_incident` plus capped `incident_history`.
Each service observation also tracks `change_timestamps` and `flapping`.

Auth is configured with `auth_ref`, which points to environment variable names:

```json
{
  "id": "proxmox",
  "name": "Proxmox",
  "group": "core",
  "url": "https://pve.local:8006",
  "check_type": "proxmox",
  "enabled": true,
  "auth_ref": {
    "scheme": "bearer",
    "env": "PROXMOX_API_TOKEN"
  }
}
```

Supported auth schemes:
- `none`
- `bearer` → `Authorization: Bearer <ENV_VALUE>`
- `basic` → `Authorization: Basic base64(user:pass)` where env value is `USER:PASS`
- `header` → custom `<header_name>: <ENV_VALUE>`
- `query_param` → appends `<param_name>=<ENV_VALUE>` to the request URL query string

Tautulli default:
- check path/profile uses `GET /api/v2` with `cmd=status` as query params
- set `auth_ref` to `{"scheme":"query_param","env":"TAUTULLI_API_KEY","param_name":"apikey"}`

Never put token/password values into `services.json`.
Set actual secret values only in backend environment variables (`.env`/container env).

### Required Environment Variables

See `.env.example`. All are optional; unconfigured or missing-credential services report `unknown`.

Important:
- `ADMIN_TOKEN` controls admin API access.
- `CHECK_TIMEOUT_SECONDS` optionally overrides per-check timeout (defaults to `REQUEST_TIMEOUT_SECONDS`).
- `SERVICES_CONFIG_PATH` points to runtime config file (default `/data/services.json`).
- `OBSERVATIONS_PATH` points to persisted operational metadata (default `/data/observations.json`).
- `OBSERVATIONS_HISTORY_LIMIT` caps stored incident history entries (default `200`).
- `AUDIT_LOG_PATH` points to append-only admin audit JSONL (default `/data/audit.log`).
- `AUDIT_LOG_MAX_BYTES` caps audit file size before trimming oldest lines (default `5242880`).
- `EXPOSE_SERVICE_URLS` controls whether `/api/services/{id}` includes `url` (default `false`).
- `FLAP_WINDOW_SECONDS` defines the flapping lookback window (default `600`).
- `FLAP_THRESHOLD` defines minimum transitions in window for flapping (default `3`).
- `REFRESH_INTERVAL_SECONDS` controls background refresh cadence (default `30`).
- `REQUEST_TIMEOUT_SECONDS` controls per-check timeout (default `4`).
- `MAX_CONCURRENCY` controls in-flight checks per refresh cycle (default `10`).
- `auth_ref.env` names must exist in backend runtime environment.

## Deployment

Designed to run behind a Cloudflare Tunnel. No inbound ports required. TLS handled by the tunnel.
In production, keep `/admin` behind Cloudflare Access and still require `Authorization: Bearer <ADMIN_TOKEN>` at the backend.
Route `ask.marcle.ai` via Cloudflare Tunnel to the same nginx container (port 9182).

```
Internet → Cloudflare Tunnel → nginx (:80 inside container, :9182 on host)
                                ├── /           → static status dashboard
                                ├── /admin      → admin UI
                                ├── /ask        → ask.marcle.ai frontend
                                └── /api/*      → backend (uvicorn :8000)
```

### Ask App

The Ask app (`/ask`) uses Google OAuth2 for authentication and SQLite for data storage.
Questions are posted to a Discord channel via webhook. Answers are delivered via email.
User points are managed via the admin API or can be seeded with `DEFAULT_STARTING_POINTS`.

Required env vars for Ask: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URL`,
`SESSION_SECRET`, `DISCORD_WEBHOOK_URL`, `SMTP_*`, `ASK_ANSWER_WEBHOOK_SECRET`.
See `.env.example` for full list.
