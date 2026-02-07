# marcle.ai

Public landing page and status API for a personal homelab environment.

## Structure

```
├── frontend/          Static landing page (HTML/CSS/JS, nginx)
├── backend/           Status aggregation API (Python, FastAPI)
├── docker-compose.yml Local dev stack
└── .env.example       Required environment variables
```

## Quick Start

```bash
cp .env.example .env
# Fill in service URLs and API keys

docker compose up --build
```

Frontend: `http://localhost:8080`
API: `http://localhost:8000/api/status`

## Frontend

Plain HTML + CSS + minimal JS. No build step. No frameworks. Fetches `/api/status` and renders service cards. Degrades gracefully — the page is usable without JS or a running API.

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

Single endpoint:

```
GET /api/status
```

Returns normalized status for all configured services. Response is cached in-memory with a 45-second TTL. All checks run concurrently. No single integration failure affects the others.

### Adding a new integration

1. Create `backend/app/services/yourservice.py`
2. Implement an async function returning `ServiceStatus`:

```python
from app.models import ServiceStatus, ServiceGroup
from app.services import http_check

async def check_yourservice() -> ServiceStatus:
    return await http_check(
        id="yourservice",
        name="Your Service",
        group=ServiceGroup.CORE,
        url=config.YOURSERVICE_URL,
        path="/health",
    )
```

3. Add config vars to `app/config.py`
4. Import and add to `SERVICE_CHECKS` in `app/main.py`

### Required Environment Variables

See `.env.example`. All are optional — unconfigured services report `unknown` status.

## Deployment

Designed to run behind a Cloudflare Tunnel. No inbound ports required. TLS handled by the tunnel.

```
Internet → Cloudflare Tunnel → reverse proxy → frontend (nginx :80)
                                             → backend (uvicorn :8000)
```
