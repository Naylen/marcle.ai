"""Shared utilities for service health checks."""

import time
import logging
from typing import Optional

import httpx

from app import config
from app.auth import AuthRef, MissingCredentialError, build_auth_headers
from app.models import ServiceConfig, ServiceStatus, Status, ServiceGroup

logger = logging.getLogger("marcle.services")

TIMEOUT = httpx.Timeout(timeout=config.CHECK_TIMEOUT_SECONDS)


async def http_check(
    *,
    id: str,
    name: str,
    group: ServiceGroup,
    url: str,
    path: str = "/",
    headers: Optional[dict] = None,
    verify_ssl: bool = False,
    description: Optional[str] = None,
    icon: Optional[str] = None,
    healthy_status_codes: set[int] = {200},
    auth_ref: Optional[AuthRef] = None,
) -> ServiceStatus:
    """Generic HTTP health check. Returns ServiceStatus, never raises."""
    if not url:
        return ServiceStatus(
            id=id, name=name, group=group, status=Status.UNKNOWN,
            description=description, icon=icon,
        )

    # Merge explicit headers with auth_ref-resolved headers.
    merged_headers: dict[str, str] = dict(headers or {})
    try:
        merged_headers.update(build_auth_headers(auth_ref))
    except MissingCredentialError:
        return ServiceStatus(
            id=id, name=name, group=group, status=Status.UNKNOWN,
            url=url, description=description, icon=icon,
        )

    full_url = url.rstrip("/") + path
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(verify=verify_ssl, timeout=TIMEOUT) as client:
            resp = await client.get(full_url, headers=merged_headers)
        latency = int((time.monotonic() - start) * 1000)

        status = Status.HEALTHY if resp.status_code in healthy_status_codes else Status.DEGRADED

        return ServiceStatus(
            id=id, name=name, group=group, status=status,
            latency_ms=latency, url=url, description=description, icon=icon,
        )
    except httpx.TimeoutException:
        logger.warning("Timeout checking %s at %s", id, full_url)
        return ServiceStatus(
            id=id, name=name, group=group, status=Status.DOWN,
            url=url, description=description, icon=icon,
        )
    except Exception as exc:
        logger.warning("Error checking %s: %s", id, str(exc))
        return ServiceStatus(
            id=id, name=name, group=group, status=Status.DOWN,
            url=url, description=description, icon=icon,
        )


async def check_service(cfg: ServiceConfig) -> ServiceStatus:
    """Run a generic HTTP health check from a ServiceConfig entry."""
    return await http_check(
        id=cfg.id,
        name=cfg.name,
        group=cfg.group,
        url=cfg.url,
        path=cfg.path,
        headers=cfg.extra_headers or None,
        verify_ssl=cfg.verify_ssl,
        description=cfg.description,
        icon=cfg.icon,
        healthy_status_codes=set(cfg.healthy_status_codes),
        auth_ref=cfg.auth_ref,
    )
