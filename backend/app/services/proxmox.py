"""Proxmox VE health check."""

from app import config
from app.models import AuthRef, ServiceGroup, ServiceStatus
from app.services import http_check


async def check_proxmox() -> ServiceStatus:
    return await http_check(
        id="proxmox",
        name="Proxmox",
        group=ServiceGroup.CORE,
        url=config.PROXMOX_URL,
        path="/api2/json/version",
        auth_ref=AuthRef(scheme="bearer", env="PROXMOX_API_TOKEN"),
        description="Virtualisation platform",
        icon="proxmox.svg",
    )
