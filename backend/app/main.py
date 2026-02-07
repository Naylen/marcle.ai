"""marcle.ai status API — main application."""

import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models import StatusResponse, OverallStatus, Status
from app.cache import cache
from app import config

# Service checks
from app.services.proxmox import check_proxmox
from app.services.unifi import check_unifi_network, check_unifi_protect
from app.services.homeassistant import check_homeassistant
from app.services.plex import check_plex
from app.services.overseerr import check_overseerr
from app.services.tautulli import check_tautulli
from app.services.arrs import check_arrs
from app.services.ollama import check_ollama
from app.services.n8n import check_n8n

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("marcle.api")

# --- App ---
app = FastAPI(
    title="marcle.ai status",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# All service check functions, executed concurrently
SERVICE_CHECKS = [
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


def _compute_overall(services) -> OverallStatus:
    statuses = {s.status for s in services}
    if Status.DOWN in statuses:
        return OverallStatus.DOWN
    if Status.DEGRADED in statuses:
        return OverallStatus.DEGRADED
    return OverallStatus.HEALTHY


async def _gather_status() -> StatusResponse:
    """Run all checks concurrently and assemble the response."""
    start = time.monotonic()
    results = await asyncio.gather(
        *(check() for check in SERVICE_CHECKS),
        return_exceptions=True,
    )

    services = []
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
