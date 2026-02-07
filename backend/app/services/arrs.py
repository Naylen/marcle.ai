"""Arr Stack health check — aggregated Radarr and Sonarr status."""

import asyncio
import logging

from app import config
from app.models import ServiceStatus, ServiceGroup, Status
from app.services import http_check

logger = logging.getLogger("marcle.services.arrs")


async def _check_radarr() -> ServiceStatus:
    headers = {}
    if config.RADARR_API_KEY:
        headers["X-Api-Key"] = config.RADARR_API_KEY

    return await http_check(
        id="radarr",
        name="Radarr",
        group=ServiceGroup.MEDIA,
        url=config.RADARR_URL,
        path="/api/v3/health",
        headers=headers,
        icon="radarr.svg",
    )


async def _check_sonarr() -> ServiceStatus:
    headers = {}
    if config.SONARR_API_KEY:
        headers["X-Api-Key"] = config.SONARR_API_KEY

    return await http_check(
        id="sonarr",
        name="Sonarr",
        group=ServiceGroup.MEDIA,
        url=config.SONARR_URL,
        path="/api/v3/health",
        headers=headers,
        icon="sonarr.svg",
    )


async def check_arrs() -> ServiceStatus:
    """Aggregated check. Healthy only if both are healthy."""
    radarr, sonarr = await asyncio.gather(_check_radarr(), _check_sonarr())

    statuses = {radarr.status, sonarr.status}

    if Status.DOWN in statuses:
        agg_status = Status.DOWN
    elif Status.DEGRADED in statuses or Status.UNKNOWN in statuses:
        agg_status = Status.DEGRADED
    else:
        agg_status = Status.HEALTHY

    # Average latency where available
    latencies = [s.latency_ms for s in (radarr, sonarr) if s.latency_ms is not None]
    avg_latency = int(sum(latencies) / len(latencies)) if latencies else None

    return ServiceStatus(
        id="arr-stack",
        name="Arr Stack",
        group=ServiceGroup.MEDIA,
        status=agg_status,
        latency_ms=avg_latency,
        description="Radarr + Sonarr",
        icon="arr.svg",
    )
