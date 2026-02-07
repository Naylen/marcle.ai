"""Ollama health check."""

from app import config
from app.models import ServiceStatus, ServiceGroup
from app.services import http_check


async def check_ollama() -> ServiceStatus:
    return await http_check(
        id="ollama",
        name="Ollama",
        group=ServiceGroup.AUTOMATION,
        url=config.OLLAMA_URL,
        path="/api/tags",
        description="Local LLM inference",
        icon="ollama.svg",
    )
