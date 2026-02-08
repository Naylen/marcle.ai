"""marcle.ai status API — main application."""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.config_store import config_store
from app.models import (
    AdminServiceConfig,
    AdminServicesConfigResponse,
    AuthRef,
    OverallStatus,
    ServiceConfig,
    ServiceStatus,
    Status,
    StatusResponse,
)
from app.services import http_check
from app.state import state

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("marcle.api")

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
    "arrs": {"path": "/api/v3/health", "healthy_status_codes": {200}},
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
    if Status.UNKNOWN in statuses:
        return OverallStatus.DEGRADED
    return OverallStatus.HEALTHY


def _enabled_services() -> list[ServiceConfig]:
    try:
        return [service for service in config_store.list_services() if service.enabled]
    except Exception:
        logger.exception("Failed loading services config")
        return []


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


def _unknown_service_status(service: ServiceConfig, checked_at: datetime) -> ServiceStatus:
    return ServiceStatus(
        id=service.id,
        name=service.name,
        group=service.group,
        status=Status.UNKNOWN,
        latency_ms=None,
        url=service.url or None,
        description=service.description,
        icon=service.icon,
        last_checked=checked_at,
    )


def _build_unknown_payload(services: list[ServiceConfig]) -> StatusResponse:
    now = datetime.now(timezone.utc)
    unknown_services = [_unknown_service_status(service, now) for service in services]
    return StatusResponse(
        generated_at=now,
        overall_status=_compute_overall(unknown_services),
        services=unknown_services,
    )


async def _check_service_with_limits(service: ServiceConfig, semaphore: asyncio.Semaphore) -> ServiceStatus:
    async with semaphore:
        try:
            return await asyncio.wait_for(
                _check_service(service),
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Timed out checking %s after %.2fs",
                service.id,
                config.REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning("Unexpected failure checking %s (%s)", service.id, exc.__class__.__name__)
        return _unknown_service_status(service, datetime.now(timezone.utc))


def _status_counts(services: list[ServiceStatus]) -> dict[Status, int]:
    counts = {
        Status.HEALTHY: 0,
        Status.DEGRADED: 0,
        Status.DOWN: 0,
        Status.UNKNOWN: 0,
    }
    for service in services:
        counts[service.status] += 1
    return counts


async def _refresh_once() -> tuple[dict, datetime, int, dict[Status, int]]:
    """Run all checks concurrently and return json-encoded payload plus metrics."""
    refresh_started_at = datetime.now(timezone.utc)
    start = time.monotonic()
    services_to_check = _enabled_services()

    if services_to_check:
        semaphore = asyncio.Semaphore(max(config.MAX_CONCURRENCY, 1))
        services = await asyncio.gather(
            *(_check_service_with_limits(service, semaphore) for service in services_to_check),
            return_exceptions=False,
        )
    else:
        services = []

    elapsed = int((time.monotonic() - start) * 1000)
    payload = StatusResponse(
        generated_at=datetime.now(timezone.utc),
        overall_status=_compute_overall(services),
        services=services,
    )
    return jsonable_encoder(payload), refresh_started_at, elapsed, _status_counts(services)


async def _set_startup_payload() -> dict:
    payload = _build_unknown_payload(_enabled_services())
    encoded = jsonable_encoder(payload)
    await state.set_cached_payload(
        encoded,
        refreshed_at=payload.generated_at,
        refresh_duration_ms=0,
    )
    return encoded


async def _refresh_loop() -> None:
    while True:
        try:
            payload, refreshed_at, duration_ms, counts = await _refresh_once()
            await state.set_cached_payload(
                payload,
                refreshed_at=refreshed_at,
                refresh_duration_ms=duration_ms,
            )
            logger.info(
                "Refresh cycle duration_ms=%d healthy=%d degraded=%d down=%d unknown=%d",
                duration_ms,
                counts[Status.HEALTHY],
                counts[Status.DEGRADED],
                counts[Status.DOWN],
                counts[Status.UNKNOWN],
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Refresh cycle failed")

        if await state.consume_needs_refresh():
            continue
        await state.wait_for_refresh_signal(config.REFRESH_INTERVAL_SECONDS)


async def _invalidate_and_refresh() -> None:
    await _set_startup_payload()
    await state.mark_needs_refresh()


@asynccontextmanager
async def _lifespan(_: FastAPI):
    await _set_startup_payload()
    refresh_task = asyncio.create_task(_refresh_loop(), name="status-refresh-loop")
    try:
        yield
    finally:
        refresh_task.cancel()
        with suppress(asyncio.CancelledError):
            await refresh_task


# --- App ---
app = FastAPI(
    title="marcle.ai status",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    cached = await state.get_cached_payload()
    if cached is not None:
        return cached
    return await _set_startup_payload()


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


def _credential_present(auth_ref: AuthRef | None) -> bool | None:
    if auth_ref is None or auth_ref.scheme == "none":
        return None
    env_name = (auth_ref.env or "").strip()
    if not env_name:
        return False
    value = os.getenv(env_name)
    return bool(value and value.strip())


def _to_admin_service(service: ServiceConfig) -> AdminServiceConfig:
    payload = service.model_dump(mode="python")
    payload["credential_present"] = _credential_present(service.auth_ref)
    return AdminServiceConfig.model_validate(payload)


@app.get("/api/admin/services", response_model=AdminServicesConfigResponse)
async def list_admin_services(_: None = Depends(_require_admin)):
    services = [_to_admin_service(service) for service in config_store.list_services()]
    return AdminServicesConfigResponse(services=services)


@app.post("/api/admin/services", response_model=AdminServiceConfig, status_code=status.HTTP_201_CREATED)
async def create_admin_service(service: ServiceConfig, _: None = Depends(_require_admin)):
    try:
        config_store.create_service(service)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await _invalidate_and_refresh()
    return _to_admin_service(service)


@app.put("/api/admin/services/{service_id}", response_model=AdminServiceConfig)
async def upsert_admin_service(
    service_id: str,
    service: ServiceConfig,
    _: None = Depends(_require_admin),
):
    if service_id != service.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id must match body id")
    config_store.upsert_service(service)
    await _invalidate_and_refresh()
    return _to_admin_service(service)


@app.delete("/api/admin/services/{service_id}", response_model=AdminServiceConfig)
async def delete_admin_service(service_id: str, _: None = Depends(_require_admin)):
    removed = config_store.delete_service(service_id)
    if removed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    await _invalidate_and_refresh()
    return _to_admin_service(removed)


@app.post("/api/admin/services/{service_id}/toggle", response_model=AdminServiceConfig)
async def toggle_admin_service(service_id: str, _: None = Depends(_require_admin)):
    updated = config_store.toggle_service(service_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    await _invalidate_and_refresh()
    return _to_admin_service(updated)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
