"""marcle.ai status API — main application."""

import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
import httpx

from app import config
from app.auth import InvalidCredentialFormatError, MissingCredentialError, build_auth_headers, build_auth_params
from app.audit_log import audit_log_store
from app.config_store import config_store
from app.models import (
    AdminAuditEntry,
    AdminBulkServicesRequest,
    AdminNotificationEndpoint,
    AdminNotificationsConfigResponse,
    AdminServiceConfig,
    AdminServicesConfigResponse,
    AuthRef,
    NotificationsConfig,
    OverallStatus,
    ServiceConfig,
    ServiceStatus,
    Status,
    StatusResponse,
)
from app.notifications_store import notifications_store
from app.observations_store import observations_store
from app.services import http_check
from app.state import state

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("marcle.api")


def _log_startup_env_warnings() -> None:
    if not os.getenv("ADMIN_TOKEN"):
        logger.warning("ADMIN_TOKEN is not set; admin endpoints are disabled.")
    if not os.getenv("TAUTULLI_API_KEY"):
        logger.warning("TAUTULLI_API_KEY is not set; Tautulli checks may report unknown.")


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
    "tautulli": {"path": "/api/v2", "params": {"cmd": "status"}, "healthy_status_codes": {200}},
    "arrs": {"path": "/api/v3/health", "healthy_status_codes": {200}},
    "radarr": {"path": "/api/v3/health", "healthy_status_codes": {200}},
    "sonarr": {"path": "/api/v3/health", "healthy_status_codes": {200}},
    "ollama": {"path": "/api/tags", "healthy_status_codes": {200}},
    "n8n": {"path": "/healthz", "healthy_status_codes": {200, 204}},
    "generic": {"path": "/", "healthy_status_codes": {200}},
}
MAX_INCIDENTS_LIMIT = 200
DEFAULT_SERVICE_INCIDENTS_LIMIT = 20
MAX_ADMIN_AUDIT_LIMIT = 500


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
        params=profile.get("params"),
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


def _services_from_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    services = payload.get("services", [])
    if not isinstance(services, list):
        return []
    normalized: list[dict[str, Any]] = []
    for service in services:
        if isinstance(service, Mapping):
            normalized.append(dict(service))
    return normalized


def _find_service_in_payload(services: list[dict[str, Any]], service_id: str) -> dict[str, Any] | None:
    for service in services:
        if service.get("id") == service_id:
            return service
    return None


async def _initialize_observations(payload: Mapping[str, Any], observed_at: datetime) -> None:
    services = _services_from_payload(payload)
    await asyncio.to_thread(observations_store.initialize_services, services, observed_at)


async def _apply_observations(payload: Mapping[str, Any], observed_at: datetime) -> dict[str, Any]:
    services = _services_from_payload(payload)
    return await asyncio.to_thread(observations_store.apply_refresh, services, observed_at)


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
    try:
        await _initialize_observations(encoded, payload.generated_at)
    except Exception:
        logger.exception("Failed initializing observations")
    return encoded


async def _get_cached_payload_or_initialize() -> dict:
    cached_payload = await state.get_cached_payload()
    if cached_payload is None:
        return await _set_startup_payload()
    return cached_payload


async def _refresh_loop() -> None:
    while True:
        try:
            payload, refreshed_at, duration_ms, counts = await _refresh_once()
            await state.set_cached_payload(
                payload,
                refreshed_at=refreshed_at,
                refresh_duration_ms=duration_ms,
            )
            try:
                await _apply_observations(payload, refreshed_at)
            except Exception:
                logger.exception("Failed persisting observations")
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
    _log_startup_env_warnings()
    await _set_startup_payload()
    # Initialize Ask DB
    from app.ask_db import init_db as _ask_init_db
    await asyncio.to_thread(_ask_init_db)
    logger.info("Ask database initialized")
    refresh_task = asyncio.create_task(_refresh_loop(), name="status-refresh-loop")
    try:
        yield
    finally:
        refresh_task.cancel()
        with suppress(asyncio.CancelledError):
            await refresh_task


# --- App ---
app = FastAPI(
    title="marcle.ai",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)

if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Webhook-Secret"],
    )

# --- Include Ask router ---
from app.routers.ask import router as ask_router  # noqa: E402
app.include_router(ask_router)


def _apply_url_visibility(payload: dict[str, Any]) -> dict[str, Any]:
    if config.EXPOSE_SERVICE_URLS:
        return payload

    services = payload.get("services")
    if not isinstance(services, list):
        return payload

    for service in services:
        if isinstance(service, dict):
            service["url"] = None
    return payload


@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    payload = await _get_cached_payload_or_initialize()
    return _apply_url_visibility(payload)


@app.get("/api/incidents")
async def get_incidents(limit: int = Query(default=50, ge=1)):
    bounded_limit = min(limit, MAX_INCIDENTS_LIMIT)
    return await asyncio.to_thread(observations_store.get_global_incidents, bounded_limit)


@app.get("/api/services/{service_id}")
async def get_service_details(service_id: str):
    cached_payload = await _get_cached_payload_or_initialize()
    services_payload = _services_from_payload(cached_payload)
    service = _find_service_in_payload(services_payload, service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")

    service_observation = await asyncio.to_thread(observations_store.get_service_observation, service_id) or {}
    service_response = {
        "id": service.get("id"),
        "name": service.get("name"),
        "group": service.get("group"),
        "status": service.get("status"),
        "latency_ms": service.get("latency_ms"),
        "icon": service.get("icon"),
        "description": service.get("description"),
        "last_checked": service.get("last_checked"),
        "last_changed_at": service_observation.get("last_changed_at"),
        "flapping": bool(service_observation.get("flapping", False)),
    }
    if config.EXPOSE_SERVICE_URLS:
        service_response["url"] = service.get("url")

    recent_incidents = await asyncio.to_thread(
        observations_store.get_recent_incidents,
        service_id,
        DEFAULT_SERVICE_INCIDENTS_LIMIT,
    )
    return {
        "service": service_response,
        "recent_incidents": recent_incidents,
    }


@app.get("/api/overview")
async def get_overview():
    now = datetime.now(timezone.utc)
    cached_payload = await _get_cached_payload_or_initialize()

    refresh_meta = await state.get_refresh_metadata()
    last_refresh_at = refresh_meta.get("last_refresh_at")
    cache_age_seconds: int | None = None
    if isinstance(last_refresh_at, datetime):
        cache_age_seconds = max(0, int((now - last_refresh_at).total_seconds()))

    services_payload = _services_from_payload(cached_payload)
    counts = {
        "healthy": 0,
        "degraded": 0,
        "down": 0,
        "unknown": 0,
        "total": len(services_payload),
    }
    for service in services_payload:
        status_value = service.get("status")
        if status_value in counts:
            counts[status_value] += 1

    observations = await asyncio.to_thread(observations_store.get_snapshot)
    observed_services = observations.get("services", {})
    overview_services: list[dict[str, Any]] = []
    for service in services_payload:
        service_id = service.get("id")
        if not isinstance(service_id, str):
            continue
        observed = observed_services.get(service_id, {})
        if not isinstance(observed, Mapping):
            observed = {}
        overview_services.append(
            {
                "id": service_id,
                "last_changed_at": observed.get("last_changed_at"),
                "last_status": observed.get("last_status"),
            }
        )

    last_incident_raw = observations.get("last_incident")
    last_incident = None
    if isinstance(last_incident_raw, Mapping):
        service_id = last_incident_raw.get("service_id")
        from_status = last_incident_raw.get("from_status")
        to_status = last_incident_raw.get("to_status")
        at_value = last_incident_raw.get("at")
        if (
            isinstance(service_id, str)
            and isinstance(from_status, str)
            and isinstance(to_status, str)
            and isinstance(at_value, str)
        ):
            last_incident = {
                "service_id": service_id,
                "from": from_status,
                "to": to_status,
                "at": at_value,
            }

    return {
        "generated_at": now,
        "last_refresh_at": last_refresh_at,
        "cache_age_seconds": cache_age_seconds,
        "counts": counts,
        "last_incident": last_incident,
        "services": overview_services,
    }


def _require_admin(authorization: str = Header(default="")) -> None:
    if not config.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API is disabled",
        )

    prefix = "Bearer "
    token = authorization[len(prefix):] if authorization.startswith(prefix) else ""
    if not hmac.compare_digest(token, config.ADMIN_TOKEN):
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


def _to_admin_notifications_config(cfg: NotificationsConfig) -> AdminNotificationsConfigResponse:
    endpoints: list[AdminNotificationEndpoint] = []
    for endpoint in cfg.endpoints:
        payload = endpoint.model_dump(mode="python")
        payload["credential_present"] = _credential_present(endpoint.auth_ref)
        endpoints.append(AdminNotificationEndpoint.model_validate(payload))
    return AdminNotificationsConfigResponse(enabled=cfg.enabled, endpoints=endpoints)


def _sanitize_audit_value(value: str | None, max_length: int) -> str | None:
    if not value:
        return None
    compact = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    if not compact:
        return None
    return compact[:max_length]


def _best_effort_client_ip(request: Request, x_forwarded_for: str | None) -> str | None:
    if x_forwarded_for:
        forwarded = x_forwarded_for.split(",")[0].strip()
        cleaned_forwarded = _sanitize_audit_value(forwarded, max_length=128)
        if cleaned_forwarded:
            return cleaned_forwarded
    client_host = request.client.host if request.client else None
    return _sanitize_audit_value(client_host, max_length=128)


async def _append_admin_audit_entry(
    *,
    action: str,
    request: Request,
    x_forwarded_for: str | None,
    user_agent: str | None,
    service_id: str | None = None,
    ids: list[str] | None = None,
    enabled: bool | None = None,
) -> None:
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "service_id": service_id,
        "ip": _best_effort_client_ip(request, x_forwarded_for),
        "user_agent": _sanitize_audit_value(user_agent, max_length=512),
    }
    if ids is not None:
        payload["ids"] = ids
    if enabled is not None:
        payload["enabled"] = enabled

    try:
        await asyncio.to_thread(audit_log_store.append, payload)
    except Exception:
        logger.warning("Failed to append admin audit entry for action=%s", action, exc_info=True)


async def _dispatch_test_notifications(cfg: NotificationsConfig) -> int:
    if not cfg.enabled:
        return 0

    payload = {
        "event": "test",
        "source": "marcle.ai",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "message": "Test notification from admin panel",
    }
    timeout = httpx.Timeout(timeout=config.REQUEST_TIMEOUT_SECONDS)
    dispatched = 0

    async with httpx.AsyncClient(timeout=timeout) as client:
        for endpoint in cfg.endpoints:
            headers = {"Content-Type": "application/json"}
            try:
                headers.update(build_auth_headers(endpoint.auth_ref))
                params = build_auth_params(endpoint.auth_ref)
            except MissingCredentialError as exc:
                logger.warning("Skipping notification endpoint %s due to missing env %s", endpoint.id, exc.env_name)
                continue
            except InvalidCredentialFormatError as exc:
                logger.warning(
                    "Skipping notification endpoint %s due to invalid %s credential in %s",
                    endpoint.id,
                    exc.scheme,
                    exc.env_name,
                )
                continue

            try:
                await client.post(endpoint.url, json=payload, headers=headers, params=params)
                dispatched += 1
            except Exception:
                logger.warning("Failed sending test notification to endpoint %s", endpoint.id, exc_info=True)

    return dispatched


@app.get("/api/admin/services", response_model=AdminServicesConfigResponse)
async def list_admin_services(_: None = Depends(_require_admin)):
    services = [_to_admin_service(service) for service in config_store.list_services()]
    return AdminServicesConfigResponse(services=services)


@app.get("/api/admin/audit", response_model=list[AdminAuditEntry])
async def get_admin_audit(
    limit: int = Query(default=200, ge=1),
    _: None = Depends(_require_admin),
):
    bounded_limit = min(limit, MAX_ADMIN_AUDIT_LIMIT)
    return await asyncio.to_thread(audit_log_store.recent, bounded_limit)


@app.get("/api/admin/notifications", response_model=AdminNotificationsConfigResponse)
async def get_admin_notifications(_: None = Depends(_require_admin)):
    cfg = notifications_store.get()
    return _to_admin_notifications_config(cfg)


@app.put("/api/admin/notifications", response_model=AdminNotificationsConfigResponse)
async def put_admin_notifications(
    payload: NotificationsConfig,
    request: Request,
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    _: None = Depends(_require_admin),
):
    saved = notifications_store.put(payload)
    await _append_admin_audit_entry(
        action="notifications_update",
        service_id=None,
        request=request,
        x_forwarded_for=x_forwarded_for,
        user_agent=user_agent,
    )
    return _to_admin_notifications_config(saved)


@app.post("/api/admin/notifications/test")
async def post_admin_notifications_test(
    request: Request,
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    _: None = Depends(_require_admin),
):
    cfg = notifications_store.get()
    dispatched = await _dispatch_test_notifications(cfg)
    await _append_admin_audit_entry(
        action="notifications_test",
        service_id=None,
        request=request,
        x_forwarded_for=x_forwarded_for,
        user_agent=user_agent,
    )
    return {
        "status": "queued",
        "dispatched": dispatched,
    }


@app.post("/api/admin/services", response_model=AdminServiceConfig, status_code=status.HTTP_201_CREATED)
async def create_admin_service(
    service: ServiceConfig,
    request: Request,
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    _: None = Depends(_require_admin),
):
    try:
        config_store.create_service(service)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await _append_admin_audit_entry(
        action="create",
        service_id=service.id,
        request=request,
        x_forwarded_for=x_forwarded_for,
        user_agent=user_agent,
    )
    await _invalidate_and_refresh()
    return _to_admin_service(service)


@app.put("/api/admin/services/{service_id}", response_model=AdminServiceConfig)
async def upsert_admin_service(
    service_id: str,
    service: ServiceConfig,
    request: Request,
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    _: None = Depends(_require_admin),
):
    if service_id != service.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id must match body id")
    config_store.upsert_service(service)
    await _append_admin_audit_entry(
        action="update",
        service_id=service.id,
        request=request,
        x_forwarded_for=x_forwarded_for,
        user_agent=user_agent,
    )
    await _invalidate_and_refresh()
    return _to_admin_service(service)


@app.delete("/api/admin/services/{service_id}", response_model=AdminServiceConfig)
async def delete_admin_service(
    service_id: str,
    request: Request,
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    _: None = Depends(_require_admin),
):
    removed = config_store.delete_service(service_id)
    if removed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    await _append_admin_audit_entry(
        action="delete",
        service_id=removed.id,
        request=request,
        x_forwarded_for=x_forwarded_for,
        user_agent=user_agent,
    )
    await _invalidate_and_refresh()
    return _to_admin_service(removed)


@app.post("/api/admin/services/bulk", response_model=AdminServicesConfigResponse)
async def bulk_admin_services(
    payload: AdminBulkServicesRequest,
    request: Request,
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    _: None = Depends(_require_admin),
):
    updated = config_store.bulk_set_enabled(payload.ids, payload.enabled)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching services found")
    await _append_admin_audit_entry(
        action="bulk",
        service_id=None,
        ids=payload.ids,
        enabled=payload.enabled,
        request=request,
        x_forwarded_for=x_forwarded_for,
        user_agent=user_agent,
    )
    await _invalidate_and_refresh()
    services = [_to_admin_service(service) for service in updated]
    return AdminServicesConfigResponse(services=services)


@app.post("/api/admin/services/{service_id}/toggle", response_model=AdminServiceConfig)
async def toggle_admin_service(
    service_id: str,
    request: Request,
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    _: None = Depends(_require_admin),
):
    updated = config_store.toggle_service(service_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    await _append_admin_audit_entry(
        action="toggle",
        service_id=updated.id,
        enabled=updated.enabled,
        request=request,
        x_forwarded_for=x_forwarded_for,
        user_agent=user_agent,
    )
    await _invalidate_and_refresh()
    return _to_admin_service(updated)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
