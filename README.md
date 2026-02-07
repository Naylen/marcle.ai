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
API: `http://localhost:8000/api/status`
Admin UI: `http://localhost:8080/admin.html`

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

Admin endpoints (require `Authorization: Bearer <ADMIN_TOKEN>`):
- `GET /api/admin/services`
- `POST /api/admin/services`
- `PUT /api/admin/services/{service_id}`

`/api/status` returns normalized status for enabled services from `services.json`.
Responses are cached in-memory with a 45-second TTL. All checks run concurrently.

### Runtime Service Config (`services.json`)

`services.json` stores only non-secret service metadata.

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
- `SERVICES_CONFIG_PATH` points to runtime config file (default `./data/services.json`).
- `auth_ref.env` names must exist in backend runtime environment.

## Deployment

Designed to run behind a Cloudflare Tunnel. No inbound ports required. TLS handled by the tunnel.

```
Internet → Cloudflare Tunnel → reverse proxy → frontend (nginx :80)
                                             → backend (uvicorn :8000)
```
