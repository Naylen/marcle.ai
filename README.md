# marcle.ai

Self-hosted homelab operations stack with two products behind one nginx entrypoint:

- Status dashboard (`/`) for service health, incidents, and operational metadata
- Ask app (`/ask`) for Google-authenticated questions, Discord notification, live SSE updates, and fallback answers

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
├── docker-compose.hardened.yml
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

Never share raw `docker compose config` output; it can include resolved secrets.
Use redacted output instead:

```bash
bash scripts/safe_compose_config.sh
```

Default compose is host-compatible and keeps hardening like non-root execution (backend),
`cap_drop: [ALL]`, `read_only: true`, and tmpfs mounts. Strict
`no-new-privileges:true` is opt-in via overlay.

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
2. Ask app creates/updates user in SQLite (`ask.db`) and sets `ask_session` + `ask_csrf` cookies
3. User submits a question (points are deducted atomically)
4. Backend posts the question to Discord and attempts to open a question thread
5. Ask UI subscribes to SSE (`/api/ask/questions/{id}/events`) for live status/answer updates
6. If a Discord user with `DISCORD_SUPPORT_ROLE_ID` replies in the thread or replies to the bot question message in-channel first, backend stores that human answer
7. If no answer arrives by `ASK_HUMAN_WAIT_SECONDS` (default 300), backend tries local LLM first; if still unanswered by `ASK_OPENAI_WAIT_SECONDS` (default 600), backend tries OpenAI fallback
8. SSE pushes `status`/`answer`/`snapshot` events to the user in real time

Session/auth model for Ask user routes:

- In-memory session dict keyed by `ask_session` cookie token
- Session payload fields: `user_id`, `google_id`, `email`, `name`, `picture_url`, `csrf_token`, `created_at`
- `ask_session` cookie: HttpOnly, SameSite=Lax, Path=/, 24h max-age (Secure when `BASE_PUBLIC_URL` is https)
- `ask_csrf` cookie: non-HttpOnly double-submit token; required for mutable Ask user POSTs
- No JWT and no `request.state.user` principal model

Features implemented:

- Google OAuth2 login
- In-memory session tokens (24h expiry)
- Per-user in-memory rate limit (5 questions / 60s)
- Points system (feature-flag controlled via ASK_POINTS_ENABLED; currently disabled by default)
- SSE stream endpoint for per-question updates
- CSRF protection (`X-CSRF-Token` must match both `ask_csrf` cookie and server-side session `csrf_token` for `POST /api/ask/questions` and `POST /api/ask/auth/logout`)
- SSE ownership enforcement (only question owner can subscribe)
- SSE abuse protections (per-session/per-IP concurrent caps and per-session connect-rate limit, returning `429 {"error":"too_many_streams"}`)
- SSE payload minimization (`status`, `answer`, `snapshot` with truncated `answer_text`)
- Discord role-gated human answer ingestion (thread messages + in-channel replies to the bot question)
- Discord idempotency guard (already-answered questions are not overwritten unless admin override token is explicitly provided)
- Two-stage fallback worker (local LLM first, OpenAI second)
- LLM hardening for fallback answers (pre-call injection classifier, strict system prompt, post-output sensitive-term filter)
- Webhook hardening (constant-time secret compare and payload size limit)
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
- `POST /api/ask/auth/logout` (requires `X-CSRF-Token` matching `ask_csrf` cookie)
- `GET /api/ask/me`
- `POST /api/ask/questions` (requires `X-CSRF-Token` matching `ask_csrf` cookie)
- `GET /api/ask/questions?limit=20`
- `GET /api/ask/questions/{question_id}/events` (SSE)
  - Unauthorized/invalid session: `401 {"error":"unauthorized"}`
  - Non-owner or unknown question: `404` (anti-enumeration behavior)
  - Rate-limited streams: `429 {"error":"too_many_streams"}`

### Ask Answer Webhook

- `POST /api/ask/answers`
- Required header: `X-Webhook-Secret: <ASK_ANSWER_WEBHOOK_SECRET>`
- Payload size is limited (configurable via `ASK_WEBHOOK_MAX_BYTES`, default 64KB)

### Ask n8n Token Endpoints (`X-N8N-TOKEN: <N8N_TOKEN>`)

- `POST /api/ask/discord/question` (Discord -> Ask upsert)
- `POST /api/ask/discord/answer` (Discord answer attach + email; optional `X-ADMIN-OVERRIDE: <ADMIN_TOKEN>` to force overwrite)

### Ask Admin Endpoints (`Authorization: Bearer <ADMIN_TOKEN>`)

- `GET /api/ask/admin/users`
- `POST /api/ask/admin/points`
- `POST /api/ask/admin/email/test`

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
- Runtime hardening knobs: `FRONTEND_MEM_LIMIT`, `BACKEND_MEM_LIMIT`, `BACKEND_UID`, `BACKEND_GID`
- Runtime paths: `SERVICES_CONFIG_PATH`, `NOTIFICATIONS_CONFIG_PATH`, `OBSERVATIONS_PATH`, `AUDIT_LOG_PATH`, `ASK_DB_PATH`
- Security/admin: `ADMIN_TOKEN`, `EXPOSE_SERVICE_URLS`, `CORS_ORIGINS`
- Flapping/incident behavior: `FLAP_WINDOW_SECONDS`, `FLAP_THRESHOLD`, `OBSERVATIONS_HISTORY_LIMIT`
- Ask OAuth/session/webhook/mail: `GOOGLE_*`, `SESSION_SECRET`, `ASK_ANSWER_WEBHOOK_SECRET`, `DISCORD_WEBHOOK_URL`, `SMTP_*`, `BASE_PUBLIC_URL`, `ASK_POINTS_ENABLED`
- Ask Discord + fallback worker: `DISCORD_BOT_TOKEN`, `DISCORD_ASK_CHANNEL_ID`, `DISCORD_GUILD_ID`, `DISCORD_SUPPORT_ROLE_ID`, `ASK_HUMAN_WAIT_SECONDS`, `ASK_OPENAI_WAIT_SECONDS`
- Ask n8n integration: `N8N_TOKEN`
- Ask webhook size guard: `ASK_WEBHOOK_MAX_BYTES`
- Ask SSE controls: `ASK_SSE_MAX_CONN_PER_SESSION`, `ASK_SSE_MAX_CONN_PER_IP`, `ASK_SSE_CONN_RATE_PER_MIN`
- Ask LLM fallback: local (`LOCAL_LLM_BASE_URL`, `LOCAL_LLM_API_KEY`, `LOCAL_LLM_MODEL`, `LOCAL_LLM_TIMEOUT_SECONDS`) and OpenAI (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `OPENAI_TIMEOUT_SECONDS`)
  - Docker Model Runner base URL should use OpenAI-compatible path style, for example `http://172.16.2.220:12434/engines/v1`

Notes:

- Missing service URLs or credentials produce `unknown` status, not hard failures.
- Admin endpoints return `503` when `ADMIN_TOKEN` is unset.
- OpenAPI/docs are disabled in FastAPI (`docs_url`, `redoc_url`, `openapi_url` are `None`).
- For Ask OAuth in production, set `BASE_PUBLIC_URL` to your public domain (for example `https://marcle.ai`).
- `GOOGLE_REDIRECT_URL` is optional; if unset it is derived as `<BASE_PUBLIC_URL>/api/ask/auth/callback`.
- SSE is proxied through nginx with buffering disabled, gzip disabled, and long-lived connection timeouts on `/api/ask/questions/*/events`.
- `/ask` and `/admin` are served with strict security headers in nginx: CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and restrictive `Permissions-Policy`.
- `Cache-Control: no-store` is set for Ask/Admin pages and Ask SSE responses.
- SMTP auth uses `SMTP_USER`/`SMTP_PASS`, while message sender uses `SMTP_FROM`.
- Backend runs as non-root by default (`10001:10001`). If `./data` permissions fail on Linux hosts, run `sudo chown -R 10001:10001 ./data` or set `BACKEND_UID`/`BACKEND_GID` in `.env`.

## Secrets Handling

See `docs/security/secrets.md` for operational policy and redaction workflow.

- Safe resolved compose output: `bash scripts/safe_compose_config.sh`
- Do not share raw `docker compose config` output in tickets/chats.

### Optional Docker Secrets Overlay

Default `.env` behavior is unchanged. For file-backed secrets:

```bash
docker compose -f docker-compose.yml -f docker-compose.secrets.yml up -d
```

Place secret files under `./secrets/` (for example `secrets/ADMIN_TOKEN`, `secrets/SESSION_SECRET`).

### Optional Strict Runtime Hardening

Enable strict hardening (frontend + backend `no-new-privileges:true`) without editing base
compose files:

```bash
docker compose -f docker-compose.yml -f docker-compose.hardened.yml up -d --build
```

On some hosts (including certain Proxmox setups), strict mode may block startup with
`operation not permitted` at exec time (examples: `exec /usr/local/bin/python: operation not permitted`
or `exec /docker-entrypoint.sh: operation not permitted`). Keep strict mode opt-in unless verified.

### Log Secret Redaction

Backend logs redact sensitive query values and bearer tokens while preserving operational context.

- Before: `HTTP Request: GET http://tautulli.local/api/v2?apikey=abc123`
- After: `HTTP response method=GET url=http://tautulli.local/api/v2?apikey=*** status=200`

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

Additional security utilities:

- `bash scripts/safe_compose_config.sh` — redacted compose config output
- `bash scripts/audit_arch.sh` — default host-compatible hardening + leak checks
- `STRICT_HARDENING=1 bash scripts/audit_arch.sh` — strict runtime hardening validation (host dependent)

## Deployment Notes

Recommended production posture:

- Keep `/admin` behind Cloudflare Access (or equivalent)
- Require strong `ADMIN_TOKEN`
- Use strong random values for `SESSION_SECRET` and `ASK_ANSWER_WEBHOOK_SECRET`
- Use strong random values for `N8N_TOKEN`
- Keep secrets only in environment variables, never in `services.json` or `notifications.json`
- Route external traffic through Cloudflare Tunnel; do not expose backend directly
- Keep `DISCORD_BOT_TOKEN` secret and set `DISCORD_SUPPORT_ROLE_ID` to a trusted support role
- Protect `n8n.marcle.ai` with Cloudflare Access (human editor login)
- Keep `hooks.marcle.ai` outside Access browser login; use n8n auth/secrets plus Cloudflare WAF/rate limits
