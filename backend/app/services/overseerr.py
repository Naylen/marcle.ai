"""Overseerr health check."""

from app import config
from app.models import AuthRef, ServiceGroup, ServiceStatus
from app.services import http_check


async def check_overseerr() -> ServiceStatus:
    return await http_check(
        id="overseerr",
        name="Overseerr",
        group=ServiceGroup.MEDIA,
        url=config.OVERSEERR_URL,
        path="/api/v1/status",
        auth_ref=AuthRef(scheme="header", env="OVERSEERR_API_KEY", header_name="X-Api-Key"),
        description="Media requests",
        icon="overseerr.svg",
    )
