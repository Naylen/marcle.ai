"""Runtime notifications configuration store backed by JSON on disk."""

import json
import os
import tempfile
from pathlib import Path
from threading import Lock

from pydantic import TypeAdapter

from app import config
from app.models import NotificationsConfig

_NOTIFICATIONS_ADAPTER = TypeAdapter(NotificationsConfig)


def _default_notifications() -> NotificationsConfig:
    return NotificationsConfig(enabled=False, endpoints=[])


class NotificationsStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self._lock = Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_unlocked(_default_notifications())

    def _read_unlocked(self) -> NotificationsConfig:
        raw = self.path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        return _NOTIFICATIONS_ADAPTER.validate_python(payload)

    def _write_unlocked(self, cfg: NotificationsConfig) -> None:
        payload = cfg.model_dump(mode="json", exclude_none=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(payload, indent=2) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f"{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.path)

    def get(self) -> NotificationsConfig:
        with self._lock:
            return self._read_unlocked()

    def put(self, cfg: NotificationsConfig) -> NotificationsConfig:
        with self._lock:
            self._write_unlocked(cfg)
            return cfg


notifications_store = NotificationsStore(config.NOTIFICATIONS_CONFIG_PATH)
