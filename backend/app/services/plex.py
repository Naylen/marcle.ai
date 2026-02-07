"""Plex Media Server health check."""

from app import config
from app.models import AuthRef, ServiceGroup, ServiceStatus
from app.services import http_check


async def check_plex() -> ServiceStatus:
    headers = {"Accept": "application/json"}

    return await http_check(
        id="plex",
        name="Plex",
        group=ServiceGroup.MEDIA,
        url=config.PLEX_URL,
        path="/identity",
        headers=headers,
        auth_ref=AuthRef(scheme="header", env="PLEX_TOKEN", header_name="X-Plex-Token"),
        description="Media server",
        icon="plex.svg",
    )
