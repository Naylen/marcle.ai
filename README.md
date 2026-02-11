# marcle.ai

Self-hosted homelab operations stack with two products behind one nginx entrypoint:

- Status dashboard (`/`) for service health, incidents, and operational metadata
- Ask app (`/ask`) for Google-authenticated questions, Discord notification, and email answers

The stack is intentionally simple: static frontend (HTML/CSS/JS) + FastAPI backend + JSON/SQLite runtime state.

## Architecture

```
Internet
  -> Cloudflare Tunnel
    -> nginx (frontend container, host port 9182)
      -> /, /admin, /ask/* static pages
      -> /api/* and /healthz proxied to FastAPI backend (:8000 internal)
      -> n8n.marcle.ai and hooks.marcle.ai proxied to n8n (:5678 internal)
```

## n8n Routing Model

- UI/editor: `https://n8n.marcle.ai` (protect this hostname with Cloudflare Access)
- Webhooks: `https://hooks.marcle.ai` (do not protect with Access browser login)
- Both hostnames should be configured in Cloudflare Tunnel to the same origin (`frontend` nginx container).

Reason for two hostnames: UI should require OTP/SSO for humans, while webhook endpoints must remain reachable by external machine clients.

## Repository Layout

```
.
├── frontend/
│   ├── index.html           Public status dashboard
│   ├── admin.html           Admin console
│   ├── ask/                 Ask app (HTML/CSS/JS)
│   ├── status.js            Dashboard data + drawer logic
│   ├── admin.js             Admin API client + forms
│   └── nginx.conf           Static + proxy routing
├── backend/
│   ├── app/main.py          FastAPI app, status loop, admin/status routes
│   ├── app/routers/ask.py   Ask auth/questions/answers/admin routes
│   ├── app/ask_services/    Google OAuth, Discord, SMTP integrations
│   ├── app/config_store.py  Runtime service config (JSON)
│   ├── app/observations_store.py Incident/flapping persistence (JSON)
│   ├── app/notifications_store.py Notification endpoints config (JSON)
│   └── tests/               API and store coverage
├── data/
│   ├── services.json        Runtime service definitions (safe to commit)
│   └── notifications.json   Runtime notification endpoint config (safe to commit)
├── docker-compose.yml
├── .env.example
└── scripts/audit_services.py
```

## Quick Start (Docker)

```bash
cp .env.example .env
# Fill required values (at minimum ADMIN_TOKEN if using /admin,
# and Ask OAuth/SMTP/webhook values if using /ask)

docker compose up --build
```

Default URLs:

- Status dashboard: `http://localhost:9182`
- Ask app: `http://localhost:9182/ask`
- Admin panel: `http://localhost:9182/admin`
- Status API: `http://localhost:9182/api/status`
- Health probe: `http://localhost:9182/healthz`

Backend port `8000` stays internal by default (not published to host).

For local n8n parity, prefer subdomains with hosts entries:

- `n8n.marcle.ai` -> `127.0.0.1`
- `hooks.marcle.ai` -> `127.0.0.1`

If you cannot do local DNS/hosts mapping, a temporary fallback is:

- `N8N_HOST=localhost`
- `N8N_EDITOR_BASE_URL=http://localhost:9182/`

Subdomain-based config is still recommended to match production behavior.

## What the Status System Does

- Loads service definitions from `services.json`
- Runs background checks every `REFRESH_INTERVAL_SECONDS` (default `30`)
- Stores the latest status payload in memory for fast `/api/status` responses
- Persists incident transitions and flapping metadata in `observations.json`
- Computes overview metadata for `/api/overview` (counts, cache age, last incident)

### Check Types

Built-in `check_type` profiles include:

- `proxmox`, `unifi-network`, `unifi-protect`, `homeassistant`
- `plex` (custom integration with now-playing extraction)
- `arrs`, `radarr`, `sonarr`, `overseerr`, `tautulli`
- `ollama`, `n8n`, `generic`

### Auth for Service Checks (`auth_ref`)

`services.json` stores only auth metadata, never raw secrets.

Supported schemes:

- `none`
- `bearer` -> `Authorization: Bearer <ENV_VALUE>`
- `basic` -> `Authorization: Basic base64(user:pass)` where env value is `USER:PASS`
- `header` -> custom `<header_name>: <ENV_VALUE>`
- `query_param` -> `?<param_name>=<ENV_VALUE>`

Example:

```json
{
  "id": "tautulli",
  "name": "Tautulli",
  "group": "media",
  "url": "https://tautulli.local",
  "check_type": "tautulli",
  "enabled": true,
  "auth_ref": {
    "scheme": "query_param",
    "env": "TAUTULLI_API_KEY",
    "param_name": "apikey"
  }
}
```

## What the Ask App Does

Flow:

1. User signs in via Google OAuth (`/api/ask/auth/login` -> callback)
2. Ask app creates/updates user in SQLite (`ask.db`) and sets `ask_session` cookie
3. User submits a question (points are deducted atomically)
4. Backend sends the question to Discord webhook
5. Marc/n8n submits answer to `/api/ask/answers` with `X-Webhook-Secret`
6. Backend stores answer and emails user via SMTP

Features implemented:

- Google OAuth2 login
- In-memory session tokens (24h expiry)
- Per-user in-memory rate limit (5 questions / 60s)
- Points system with DB constraint to prevent negative balances
- Ask admin endpoints for listing users and adjusting points

## API Reference

### Public Status Endpoints

- `GET /api/status`
- `GET /api/overview`
- `GET /api/incidents?limit=50`
- `GET /api/services/{id}`
- `GET /healthz`

### Admin Status Endpoints (`Authorization: Bearer <ADMIN_TOKEN>`)

- `GET /api/admin/services`
- `POST /api/admin/services`
- `PUT /api/admin/services/{id}`
- `DELETE /api/admin/services/{id}`
- `POST /api/admin/services/{id}/toggle`
- `POST /api/admin/services/bulk`
- `GET /api/admin/audit?limit=200`
- `GET /api/admin/notifications`
- `PUT /api/admin/notifications`
- `POST /api/admin/notifications/test`

### Ask User Endpoints (session cookie)

- `GET /api/ask/auth/login`
- `GET /api/ask/auth/callback`
- `POST /api/ask/auth/logout`
- `GET /api/ask/me`
- `POST /api/ask/questions`
- `GET /api/ask/questions?limit=20`

### Ask Answer Webhook

- `POST /api/ask/answers`
- Required header: `X-Webhook-Secret: <ASK_ANSWER_WEBHOOK_SECRET>`

### Ask Admin Endpoints (`Authorization: Bearer <ADMIN_TOKEN>`)

- `GET /api/ask/admin/users`
- `POST /api/ask/admin/points`

## Runtime Files

These files are created/updated at runtime in `/data` (Docker bind-mounts `./data:/data`):

- `services.json` -> service definitions
- `notifications.json` -> outbound notification endpoint config
- `observations.json` -> last status changes, incident history, flapping timestamps
- `audit.log` -> append-only admin action log (size-capped)
- `ask.db` -> Ask app SQLite DB (`users`, `questions`)

## Environment Variables

Use `.env.example` as source of truth. Important groups:

- Core status loop: `REFRESH_INTERVAL_SECONDS`, `REQUEST_TIMEOUT_SECONDS`, `MAX_CONCURRENCY`
- Runtime paths: `SERVICES_CONFIG_PATH`, `NOTIFICATIONS_CONFIG_PATH`, `OBSERVATIONS_PATH`, `AUDIT_LOG_PATH`, `ASK_DB_PATH`
- Security/admin: `ADMIN_TOKEN`, `EXPOSE_SERVICE_URLS`, `CORS_ORIGINS`
- Flapping/incident behavior: `FLAP_WINDOW_SECONDS`, `FLAP_THRESHOLD`, `OBSERVATIONS_HISTORY_LIMIT`
- Ask OAuth/session/webhook/mail: `GOOGLE_*`, `SESSION_SECRET`, `ASK_ANSWER_WEBHOOK_SECRET`, `DISCORD_WEBHOOK_URL`, `SMTP_*`, `BASE_PUBLIC_URL`

Notes:

- Missing service URLs or credentials produce `unknown` status, not hard failures.
- Admin endpoints return `503` when `ADMIN_TOKEN` is unset.
- OpenAPI/docs are disabled in FastAPI (`docs_url`, `redoc_url`, `openapi_url` are `None`).
- For Ask OAuth in production, set `BASE_PUBLIC_URL` to your public domain (for example `https://marcle.ai`).
- `GOOGLE_REDIRECT_URL` is optional; if unset it is derived as `<BASE_PUBLIC_URL>/api/ask/auth/callback`.

## Local Development (without Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Serve frontend with any static server that mirrors nginx routing, or use Docker compose for parity.

## Tests

```bash
cd backend
pytest
```

Current tests cover:

- Admin auth and runtime config mutations
- Audit log behavior and limits
- Auth reference handling (including query-param auth)
- Status cache behavior and URL exposure controls
- Observation/incident/flapping derivation

## Utility Script

`scripts/audit_services.py` audits runtime config vs status health.

```bash
MARCLE_BASE_URL=http://localhost:9182 ADMIN_TOKEN=... python scripts/audit_services.py
```

Note: script default base URL is `http://localhost:9181`; set `MARCLE_BASE_URL` explicitly for this repo's compose defaults.

## Deployment Notes

Recommended production posture:

- Keep `/admin` behind Cloudflare Access (or equivalent)
- Require strong `ADMIN_TOKEN`
- Use strong random values for `SESSION_SECRET` and `ASK_ANSWER_WEBHOOK_SECRET`
- Keep secrets only in environment variables, never in `services.json` or `notifications.json`
- Route external traffic through Cloudflare Tunnel; do not expose backend directly
- Protect `n8n.marcle.ai` with Cloudflare Access (human editor login)
- Keep `hooks.marcle.ai` outside Access browser login; use n8n auth/secrets plus Cloudflare WAF/rate limits
