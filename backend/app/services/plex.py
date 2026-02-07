"""Plex Media Server health check."""

from app import config
from app.models import ServiceStatus, ServiceGroup
from app.services import http_check


async def check_plex() -> ServiceStatus:
    headers = {"Accept": "application/json"}
    path = "/identity"
    if config.PLEX_TOKEN:
        path += f"?X-Plex-Token={config.PLEX_TOKEN}"

    return await http_check(
        id="plex",
        name="Plex",
        group=ServiceGroup.MEDIA,
        url=config.PLEX_URL,
        path=path,
        headers=headers,
        description="Media server",
        icon="plex.svg",
    )
