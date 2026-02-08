"""Append-only admin audit log with bounded on-disk size."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Any

from app import config

logger = logging.getLogger("marcle.audit_log")


class AuditLogStore:
    def __init__(self, path: str, max_bytes: int):
        self.path = Path(path)
        self.max_bytes = max(1024, int(max_bytes))
        self._lock = Lock()

    def append(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
        encoded = line.encode("utf-8")

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY)
            try:
                os.write(fd, encoded)
                os.fsync(fd)
            finally:
                os.close(fd)

            self._enforce_max_size_unlocked()

    def recent(self, limit: int) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 500))
        with self._lock:
            if not self.path.exists():
                return []

            entries: deque[dict[str, Any]] = deque(maxlen=bounded_limit)
            with self.path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed audit log line")
                        continue
                    if isinstance(parsed, dict):
                        entries.append(parsed)

        output = list(entries)
        output.reverse()
        return output

    def _enforce_max_size_unlocked(self) -> None:
        try:
            size_bytes = self.path.stat().st_size
        except FileNotFoundError:
            return

        if size_bytes <= self.max_bytes:
            return

        with self.path.open("rb") as handle:
            handle.seek(max(0, size_bytes - self.max_bytes))
            tail = handle.read()

        if tail:
            first_newline = tail.find(b"\n")
            trimmed = tail if first_newline < 0 else tail[first_newline + 1 :]
        else:
            trimmed = b""

        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=self.path.parent,
            prefix=f"{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(trimmed)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.path)


audit_log_store = AuditLogStore(config.AUDIT_LOG_PATH, config.AUDIT_LOG_MAX_BYTES)
