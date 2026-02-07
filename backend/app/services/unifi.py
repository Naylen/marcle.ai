"""UniFi Network and Protect health checks."""

from app import config
from app.models import ServiceStatus, ServiceGroup
from app.services import http_check


async def check_unifi_network() -> ServiceStatus:
    return await http_check(
        id="unifi-network",
        name="UniFi Network",
        group=ServiceGroup.CORE,
        url=config.UNIFI_URL,
        path="/",
        description="Network management",
        icon="unifi.svg",
        healthy_status_codes={200, 302},
    )


async def check_unifi_protect() -> ServiceStatus:
    headers = {}
    if config.UNIFI_PROTECT_API_KEY:
        headers["Authorization"] = f"Bearer {config.UNIFI_PROTECT_API_KEY}"

    return await http_check(
        id="unifi-protect",
        name="UniFi Protect",
        group=ServiceGroup.CORE,
        url=config.UNIFI_PROTECT_URL,
        path="/proxy/protect/api",
        headers=headers,
        description="Camera surveillance",
        icon="unifi-protect.svg",
    )
