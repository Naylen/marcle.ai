"""Shared utilities for service health checks."""

import time
import logging
from typing import Optional

import httpx

from app import config
from app.models import ServiceStatus, Status, ServiceGroup

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
) -> ServiceStatus:
    """Generic HTTP health check. Returns ServiceStatus, never raises."""
    if not url:
        return ServiceStatus(
            id=id, name=name, group=group, status=Status.UNKNOWN,
            description=description, icon=icon,
        )

    full_url = url.rstrip("/") + path
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(verify=verify_ssl, timeout=TIMEOUT) as client:
            resp = await client.get(full_url, headers=headers or {})
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
