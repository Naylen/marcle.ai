"""n8n health check."""

from app import config
from app.models import ServiceStatus, ServiceGroup
from app.services import http_check


async def check_n8n() -> ServiceStatus:
    return await http_check(
        id="n8n",
        name="n8n",
        group=ServiceGroup.AUTOMATION,
        url=config.N8N_URL,
        path="/healthz",
        description="Workflow automation",
        icon="n8n.svg",
        healthy_status_codes={200, 204},
    )
