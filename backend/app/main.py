"""marcle.ai status API — main application."""

import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.cache import cache
from app.config_store import config_store
from app.models import OverallStatus, ServiceConfig, ServicesConfigResponse, Status, StatusResponse
from app.services import http_check
from app import config

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

CHECK_TYPE_PROFILES: dict[str, dict] = {
    "proxmox": {"path": "/api2/json/version", "healthy_status_codes": {200}},
    "unifi-network": {"path": "/", "healthy_status_codes": {200, 302}},
    "unifi-protect": {"path": "/proxy/protect/api", "healthy_status_codes": {200}},
    "homeassistant": {"path": "/api/", "healthy_status_codes": {200}},
    "plex": {
        "path": "/identity",
        "healthy_status_codes": {200},
        "headers": {"Accept": "application/json"},
    },
    "overseerr": {"path": "/api/v1/status", "healthy_status_codes": {200}},
    "tautulli": {"path": "/api/v2?cmd=arnold", "healthy_status_codes": {200}},
    "radarr": {"path": "/api/v3/health", "healthy_status_codes": {200}},
    "sonarr": {"path": "/api/v3/health", "healthy_status_codes": {200}},
    "ollama": {"path": "/api/tags", "healthy_status_codes": {200}},
    "n8n": {"path": "/healthz", "healthy_status_codes": {200, 204}},
    "generic": {"path": "/", "healthy_status_codes": {200}},
}


def _compute_overall(services) -> OverallStatus:
    statuses = {s.status for s in services}
    if Status.DOWN in statuses:
        return OverallStatus.DOWN
    if Status.DEGRADED in statuses:
        return OverallStatus.DEGRADED
    return OverallStatus.HEALTHY


def _get_profile(service: ServiceConfig) -> dict:
    profile = dict(CHECK_TYPE_PROFILES.get(service.check_type, CHECK_TYPE_PROFILES["generic"]))
    if service.path:
        profile["path"] = service.path
    if service.healthy_status_codes:
        profile["healthy_status_codes"] = set(service.healthy_status_codes)
    profile["verify_ssl"] = service.verify_ssl
    return profile


async def _check_service(service: ServiceConfig):
    profile = _get_profile(service)
    return await http_check(
        id=service.id,
        name=service.name,
        group=service.group,
        url=service.url,
        path=profile.get("path", "/"),
        headers=profile.get("headers"),
        auth_ref=service.auth_ref,
        verify_ssl=profile.get("verify_ssl", False),
        description=service.description,
        icon=service.icon,
        healthy_status_codes=profile.get("healthy_status_codes", {200}),
    )


async def _gather_status() -> StatusResponse:
    """Run all checks concurrently and assemble the response."""
    start = time.monotonic()
    services_to_check = [svc for svc in config_store.list_services() if svc.enabled]
    results = await asyncio.gather(
        *(_check_service(service) for service in services_to_check),
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


def _require_admin(authorization: str = Header(default="")) -> None:
    if not config.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API is disabled",
        )

    prefix = "Bearer "
    token = authorization[len(prefix):] if authorization.startswith(prefix) else None
    if token != config.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.get("/api/admin/services", response_model=ServicesConfigResponse)
async def list_admin_services(_: None = Depends(_require_admin)):
    return ServicesConfigResponse(services=config_store.list_services())


@app.post("/api/admin/services", response_model=ServiceConfig, status_code=status.HTTP_201_CREATED)
async def create_admin_service(service: ServiceConfig, _: None = Depends(_require_admin)):
    try:
        config_store.create_service(service)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    cache.clear()
    return service


@app.put("/api/admin/services/{service_id}", response_model=ServiceConfig)
async def upsert_admin_service(
    service_id: str,
    service: ServiceConfig,
    _: None = Depends(_require_admin),
):
    if service_id != service.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id must match body id")
    config_store.upsert_service(service)
    cache.clear()
    return service


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
