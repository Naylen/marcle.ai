"""Proxmox VE health check."""

from app import config
from app.models import ServiceStatus, ServiceGroup
from app.services import http_check


async def check_proxmox() -> ServiceStatus:
    headers = {}
    if config.PROXMOX_TOKEN_ID and config.PROXMOX_TOKEN_SECRET:
        headers["Authorization"] = (
            f"PVEAPIToken={config.PROXMOX_TOKEN_ID}={config.PROXMOX_TOKEN_SECRET}"
        )

    return await http_check(
        id="proxmox",
        name="Proxmox",
        group=ServiceGroup.CORE,
        url=config.PROXMOX_URL,
        path="/api2/json/version",
        headers=headers,
        description="Virtualisation platform",
        icon="proxmox.svg",
    )
