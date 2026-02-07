"""Home Assistant health check."""

from app import config
from app.models import AuthRef, ServiceGroup, ServiceStatus
from app.services import http_check


async def check_homeassistant() -> ServiceStatus:
    return await http_check(
        id="homeassistant",
        name="Home Assistant",
        group=ServiceGroup.CORE,
        url=config.HOMEASSISTANT_URL,
        path="/api/",
        auth_ref=AuthRef(scheme="bearer", env="HOMEASSISTANT_TOKEN"),
        description="Home automation",
        icon="homeassistant.svg",
    )
