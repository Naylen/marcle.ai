"""Home Assistant health check."""

from app import config
from app.models import ServiceStatus, ServiceGroup
from app.services import http_check


async def check_homeassistant() -> ServiceStatus:
    headers = {}
    if config.HOMEASSISTANT_TOKEN:
        headers["Authorization"] = f"Bearer {config.HOMEASSISTANT_TOKEN}"

    return await http_check(
        id="homeassistant",
        name="Home Assistant",
        group=ServiceGroup.CORE,
        url=config.HOMEASSISTANT_URL,
        path="/api/",
        headers=headers,
        description="Home automation",
        icon="homeassistant.svg",
    )
