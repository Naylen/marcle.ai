# marcle.ai

Public landing page plus status/admin API for a personal homelab environment.

## Structure

```
├── frontend/          Static landing page + admin UI (HTML/CSS/JS, nginx)
├── backend/           Status/admin API (Python, FastAPI)
├── data/services.json Runtime service definitions (safe to commit)
├── docker-compose.yml Local dev stack
└── .env.example       Required environment variables
```

## Quick Start

```bash
cp .env.example .env
# Fill in service URLs and env-backed secrets

docker compose up --build
```

Frontend: `http://localhost:8080`
API (via nginx proxy): `http://localhost:8080/api/status`
Admin UI: `http://localhost:8080/admin`
Backend container port `8000` is internal-only by default in `docker-compose.yml`.

## Frontend

Plain HTML + CSS + minimal JS. No build step. No frameworks.
- Public page fetches `/api/status` and renders service cards.
- Admin page uses `/api/admin/services` with bearer token auth.

To point the frontend at a different API origin, set `window.MARCLE_API_BASE` before the script loads, or configure your reverse proxy to route `/api/*` to the backend.

## Backend

### Running locally (without Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### API

Public endpoint:
- `GET /api/status`
- `GET /api/overview`
- `GET /api/incidents?limit=50`
- `GET /api/services/{id}`

Admin endpoints (require `Authorization: Bearer <ADMIN_TOKEN>`):
- `GET /api/admin/services`
- `POST /api/admin/services`
- `PUT /api/admin/services/{service_id}`
- `DELETE /api/admin/services/{service_id}`
- `POST /api/admin/services/{service_id}/toggle`

`/api/status` returns normalized status for enabled services from `services.json`.
Checks run in a background loop and `/api/status` returns the latest in-memory payload immediately.
The loop runs every `REFRESH_INTERVAL_SECONDS` (default `30`) with `MAX_CONCURRENCY` (default `10`) and per-check timeout `REQUEST_TIMEOUT_SECONDS` (default `4`).
`/api/overview` returns derived dashboard metadata (counts, cache age, last incident, and per-service last-changed info).
`/api/incidents` returns recent incident transitions (most recent first).
`/api/services/{id}` returns service detail + recent incidents for drawer views.

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

Never put token/password values into `services.json`.
Set actual secret values only in backend environment variables (`.env`/container env).

### Required Environment Variables

See `.env.example`. All are optional; unconfigured or missing-credential services report `unknown`.

Important:
- `ADMIN_TOKEN` controls admin API access.
- `SERVICES_CONFIG_PATH` points to runtime config file (default `/data/services.json`).
- `OBSERVATIONS_PATH` points to persisted operational metadata (default `/data/observations.json`).
- `OBSERVATIONS_HISTORY_LIMIT` caps stored incident history entries (default `200`).
- `EXPOSE_SERVICE_URLS` controls whether `/api/services/{id}` includes `url` (default `false`).
- `FLAP_WINDOW_SECONDS` defines the flapping lookback window (default `600`).
- `FLAP_THRESHOLD` defines minimum transitions in window for flapping (default `3`).
- `REFRESH_INTERVAL_SECONDS` controls background refresh cadence (default `30`).
- `REQUEST_TIMEOUT_SECONDS` controls per-check timeout (default `4`).
- `MAX_CONCURRENCY` controls in-flight checks per refresh cycle (default `10`).
- `auth_ref.env` names must exist in backend runtime environment.

## Deployment

Designed to run behind a Cloudflare Tunnel. No inbound ports required. TLS handled by the tunnel.

```
Internet → Cloudflare Tunnel → reverse proxy → frontend (nginx :80)
                                             → backend (uvicorn :8000)
```
