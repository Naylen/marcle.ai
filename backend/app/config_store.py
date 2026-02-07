"""Runtime service configuration store backed by JSON on disk."""

import json
import logging
import os
from pathlib import Path
from threading import Lock

from pydantic import TypeAdapter

from app import config
from app.models import AuthRef, ServiceConfig, ServiceGroup

logger = logging.getLogger("marcle.config_store")

_SERVICES_ADAPTER = TypeAdapter(list[ServiceConfig])


def _default_services() -> list[ServiceConfig]:
    return [
        ServiceConfig(
            id="proxmox",
            name="Proxmox",
            group=ServiceGroup.CORE,
            url=os.getenv("PROXMOX_URL", ""),
            check_type="proxmox",
            icon="proxmox.svg",
            enabled=True,
            description="Virtualisation platform",
            auth_ref=AuthRef(scheme="bearer", env="PROXMOX_API_TOKEN"),
        ),
        ServiceConfig(
            id="unifi-network",
            name="UniFi Network",
            group=ServiceGroup.CORE,
            url=os.getenv("UNIFI_URL", ""),
            check_type="unifi-network",
            icon="unifi.svg",
            enabled=True,
            description="Network management",
        ),
        ServiceConfig(
            id="unifi-protect",
            name="UniFi Protect",
            group=ServiceGroup.CORE,
            url=os.getenv("UNIFI_PROTECT_URL", ""),
            check_type="unifi-protect",
            icon="unifi-protect.svg",
            enabled=True,
            description="Camera surveillance",
            auth_ref=AuthRef(scheme="bearer", env="UNIFI_API_KEY"),
        ),
        ServiceConfig(
            id="homeassistant",
            name="Home Assistant",
            group=ServiceGroup.CORE,
            url=os.getenv("HOMEASSISTANT_URL", ""),
            check_type="homeassistant",
            icon="homeassistant.svg",
            enabled=True,
            description="Home automation",
            auth_ref=AuthRef(scheme="bearer", env="HOMEASSISTANT_TOKEN"),
        ),
        ServiceConfig(
            id="plex",
            name="Plex",
            group=ServiceGroup.MEDIA,
            url=os.getenv("PLEX_URL", ""),
            check_type="plex",
            icon="plex.svg",
            enabled=True,
            description="Media server",
            auth_ref=AuthRef(scheme="header", env="PLEX_TOKEN", header_name="X-Plex-Token"),
        ),
        ServiceConfig(
            id="overseerr",
            name="Overseerr",
            group=ServiceGroup.MEDIA,
            url=os.getenv("OVERSEERR_URL", ""),
            check_type="overseerr",
            icon="overseerr.svg",
            enabled=True,
            description="Media requests",
            auth_ref=AuthRef(scheme="header", env="OVERSEERR_API_KEY", header_name="X-Api-Key"),
        ),
        ServiceConfig(
            id="tautulli",
            name="Tautulli",
            group=ServiceGroup.MEDIA,
            url=os.getenv("TAUTULLI_URL", ""),
            check_type="tautulli",
            icon="tautulli.svg",
            enabled=True,
            description="Plex monitoring",
            auth_ref=AuthRef(scheme="header", env="TAUTULLI_API_KEY", header_name="X-Api-Key"),
        ),
        ServiceConfig(
            id="radarr",
            name="Radarr",
            group=ServiceGroup.MEDIA,
            url=os.getenv("RADARR_URL", ""),
            check_type="radarr",
            icon="radarr.svg",
            enabled=True,
            auth_ref=AuthRef(scheme="header", env="RADARR_API_KEY", header_name="X-Api-Key"),
        ),
        ServiceConfig(
            id="sonarr",
            name="Sonarr",
            group=ServiceGroup.MEDIA,
            url=os.getenv("SONARR_URL", ""),
            check_type="sonarr",
            icon="sonarr.svg",
            enabled=True,
            auth_ref=AuthRef(scheme="header", env="SONARR_API_KEY", header_name="X-Api-Key"),
        ),
        ServiceConfig(
            id="ollama",
            name="Ollama",
            group=ServiceGroup.AUTOMATION,
            url=os.getenv("OLLAMA_URL", ""),
            check_type="ollama",
            icon="ollama.svg",
            enabled=True,
            description="Local LLM inference",
        ),
        ServiceConfig(
            id="n8n",
            name="n8n",
            group=ServiceGroup.AUTOMATION,
            url=os.getenv("N8N_URL", ""),
            check_type="n8n",
            icon="n8n.svg",
            enabled=True,
            description="Workflow automation",
        ),
    ]


class ConfigStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self._lock = Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_services_unlocked(_default_services())
        logger.info("Created default service config at %s", self.path)

    def _read_services_unlocked(self) -> list[ServiceConfig]:
        raw = self.path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if isinstance(payload, dict):
            data = payload.get("services", [])
        elif isinstance(payload, list):
            data = payload
        else:
            raise ValueError("Invalid services config format")
        return _SERVICES_ADAPTER.validate_python(data)

    def _write_services_unlocked(self, services: list[ServiceConfig]) -> None:
        payload = {
            "services": [svc.model_dump(mode="json", exclude_none=True) for svc in services],
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def list_services(self) -> list[ServiceConfig]:
        with self._lock:
            return self._read_services_unlocked()

    def create_service(self, service: ServiceConfig) -> None:
        with self._lock:
            services = self._read_services_unlocked()
            if any(s.id == service.id for s in services):
                raise ValueError(f"Service '{service.id}' already exists")
            services.append(service)
            self._write_services_unlocked(services)

    def upsert_service(self, service: ServiceConfig) -> None:
        with self._lock:
            services = self._read_services_unlocked()
            replaced = False
            for i, existing in enumerate(services):
                if existing.id == service.id:
                    services[i] = service
                    replaced = True
                    break
            if not replaced:
                services.append(service)
            self._write_services_unlocked(services)


config_store = ConfigStore(config.SERVICES_CONFIG_PATH)
