"""Persistent service configuration backed by a JSON file.

Reads/writes ``services.json`` — the file is safe to commit because it never
contains secret values, only *references* to environment variable names.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from app.models import ServiceConfig

logger = logging.getLogger("marcle.config_store")

_DEFAULT_PATH = os.getenv("SERVICES_CONFIG_PATH", "/data/services.json")


class ConfigStore:
    """Thread-safe (single-worker) JSON config store for service definitions."""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = Path(path or _DEFAULT_PATH)
        self._services: list[ServiceConfig] = []
        self._load()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def all(self) -> list[ServiceConfig]:
        """Return all service configs (enabled + disabled)."""
        return list(self._services)

    def enabled(self) -> list[ServiceConfig]:
        """Return only enabled service configs."""
        return [s for s in self._services if s.enabled]

    def get(self, service_id: str) -> Optional[ServiceConfig]:
        for s in self._services:
            if s.id == service_id:
                return s
        return None

    def upsert(self, cfg: ServiceConfig) -> ServiceConfig:
        """Insert or replace a service config entry, then persist."""
        for i, existing in enumerate(self._services):
            if existing.id == cfg.id:
                self._services[i] = cfg
                self._save()
                return cfg
        self._services.append(cfg)
        self._save()
        return cfg

    def delete(self, service_id: str) -> bool:
        before = len(self._services)
        self._services = [s for s in self._services if s.id != service_id]
        if len(self._services) < before:
            self._save()
            return True
        return False

    def reload(self) -> None:
        """Re-read the JSON file from disk."""
        self._load()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            logger.info("Config file %s not found — starting with empty list", self._path)
            self._services = []
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raw = raw.get("services", [])
            self._services = [ServiceConfig.model_validate(entry) for entry in raw]
            logger.info("Loaded %d service configs from %s", len(self._services), self._path)
        except Exception:
            logger.exception("Failed to load %s — starting with empty list", self._path)
            self._services = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [s.model_dump(mode="json") for s in self._services]
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self._path)
        logger.info("Saved %d service configs to %s", len(self._services), self._path)


# Module-level singleton — import and use directly.
store = ConfigStore()
