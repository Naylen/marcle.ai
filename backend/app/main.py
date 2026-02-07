"""marcle.ai status API — main application."""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    OverallStatus,
    ServiceConfig,
    ServiceStatus,
    Status,
    StatusResponse,
)
from app.cache import cache
from app.config_store import store
from app.services import check_service

# Legacy hardcoded checkers (used as fallback when services.json is empty)
from app.services.proxmox import check_proxmox
from app.services.unifi import check_unifi_network, check_unifi_protect
from app.services.homeassistant import check_homeassistant
from app.services.plex import check_plex
from app.services.overseerr import check_overseerr
from app.services.tautulli import check_tautulli
from app.services.arrs import check_arrs
from app.services.ollama import check_ollama
from app.services.n8n import check_n8n

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("marcle.api")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="marcle.ai status",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Legacy hardcoded checks — used only when services.json is empty
# ---------------------------------------------------------------------------
LEGACY_CHECKS = [
    check_proxmox,
    check_unifi_network,
    check_unifi_protect,
    check_homeassistant,
    check_plex,
    check_overseerr,
    check_tautulli,
    check_arrs,
    check_ollama,
    check_n8n,
]


# ---------------------------------------------------------------------------
# Admin auth dependency
# ---------------------------------------------------------------------------

async def require_admin(request: Request) -> None:
    """Verify the request carries a valid admin bearer token."""
    token = os.environ.get("ADMIN_TOKEN", "")
    if not token:
        raise HTTPException(503, detail="Admin API is disabled (ADMIN_TOKEN not set)")
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != token:
        raise HTTPException(401, detail="Invalid or missing admin token")


# ---------------------------------------------------------------------------
# Status logic
# ---------------------------------------------------------------------------

def _compute_overall(services: list[ServiceStatus]) -> OverallStatus:
    statuses = {s.status for s in services}
    if Status.DOWN in statuses:
        return OverallStatus.DOWN
    if Status.DEGRADED in statuses:
        return OverallStatus.DEGRADED
    return OverallStatus.HEALTHY


async def _gather_status() -> StatusResponse:
    """Run all checks concurrently and assemble the response."""
    start = time.monotonic()

    # Prefer services.json-driven checks when available.
    configured = store.enabled()

    if configured:
        results = await asyncio.gather(
            *(check_service(cfg) for cfg in configured),
            return_exceptions=True,
        )
    else:
        # Fallback: legacy hardcoded checkers.
        results = await asyncio.gather(
            *(fn() for fn in LEGACY_CHECKS),
            return_exceptions=True,
        )

    services: list[ServiceStatus] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("Check %d raised unexpectedly: %s", i, result)
            continue
        services.append(result)

    elapsed = int((time.monotonic() - start) * 1000)
    logger.info("Status check completed in %dms for %d services", elapsed, len(services))

    return StatusResponse(
        generated_at=datetime.now(timezone.utc),
        overall_status=_compute_overall(services),
        services=services,
    )


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    cached = cache.get()
    if cached is not None:
        logger.info("Serving cached response")
        return cached

    response = await _gather_status()
    cache.set(response)
    return response


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Admin endpoints — token-protected, never return secret values
# ---------------------------------------------------------------------------

@app.get("/api/admin/services", dependencies=[Depends(require_admin)])
async def admin_list_services():
    """Return all service configs. auth_ref contains env var *names* only."""
    services = store.all()
    return [s.model_dump(mode="json") for s in services]


@app.get("/api/admin/services/{service_id}", dependencies=[Depends(require_admin)])
async def admin_get_service(service_id: str):
    svc = store.get(service_id)
    if svc is None:
        raise HTTPException(404, detail="Service not found")
    return svc.model_dump(mode="json")


@app.put("/api/admin/services/{service_id}", dependencies=[Depends(require_admin)])
async def admin_upsert_service(service_id: str, body: ServiceConfig):
    """Create or update a service config entry.

    The request body may include an ``auth_ref`` with scheme and env var
    name, but **never** the actual secret value.
    """
    if body.id != service_id:
        raise HTTPException(400, detail="Service id in URL and body must match")
    saved = store.upsert(body)
    cache.invalidate()
    return saved.model_dump(mode="json")


@app.delete("/api/admin/services/{service_id}", dependencies=[Depends(require_admin)])
async def admin_delete_service(service_id: str):
    if not store.delete(service_id):
        raise HTTPException(404, detail="Service not found")
    cache.invalidate()
    return {"deleted": service_id}
