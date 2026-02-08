"""Tautulli health check."""

from app import config
from app.models import AuthRef, ServiceGroup, ServiceStatus
from app.services import http_check


async def check_tautulli() -> ServiceStatus:
    return await http_check(
        id="tautulli",
        name="Tautulli",
        group=ServiceGroup.MEDIA,
        url=config.TAUTULLI_URL,
        path="/api/v2",
        params={"cmd": "status"},
        auth_ref=AuthRef(scheme="query_param", env="TAUTULLI_API_KEY", param_name="apikey"),
        description="Plex monitoring",
        icon="tautulli.svg",
    )
