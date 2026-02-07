"""Tautulli health check."""

from app import config
from app.models import ServiceStatus, ServiceGroup
from app.services import http_check


async def check_tautulli() -> ServiceStatus:
    path = "/api/v2"
    if config.TAUTULLI_API_KEY:
        path += f"?apikey={config.TAUTULLI_API_KEY}&cmd=arnold"

    return await http_check(
        id="tautulli",
        name="Tautulli",
        group=ServiceGroup.MEDIA,
        url=config.TAUTULLI_URL,
        path=path,
        description="Plex monitoring",
        icon="tautulli.svg",
    )
