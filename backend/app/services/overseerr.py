"""Overseerr health check."""

from app import config
from app.models import ServiceStatus, ServiceGroup
from app.services import http_check


async def check_overseerr() -> ServiceStatus:
    headers = {}
    if config.OVERSEERR_API_KEY:
        headers["X-Api-Key"] = config.OVERSEERR_API_KEY

    return await http_check(
        id="overseerr",
        name="Overseerr",
        group=ServiceGroup.MEDIA,
        url=config.OVERSEERR_URL,
        path="/api/v1/status",
        headers=headers,
        description="Media requests",
        icon="overseerr.svg",
    )
