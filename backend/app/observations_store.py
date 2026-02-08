"""Persistent operational observations used by the dashboard overview."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app import config

logger = logging.getLogger("marcle.observations")


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_incident(entry: Any) -> dict[str, str] | None:
    if not isinstance(entry, dict):
        return None
    service_id = entry.get("service_id")
    from_status = entry.get("from_status", entry.get("from"))
    to_status = entry.get("to_status", entry.get("to"))
    at = entry.get("at")
    if not (
        isinstance(service_id, str)
        and isinstance(from_status, str)
        and isinstance(to_status, str)
        and isinstance(at, str)
    ):
        return None
    return {
        "service_id": service_id,
        "from_status": from_status,
        "to_status": to_status,
        "at": at,
    }


def _normalize_service_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        entry = {}

    timestamps: list[str] = []
    raw_timestamps = entry.get("change_timestamps")
    if isinstance(raw_timestamps, list):
        timestamps = [timestamp for timestamp in raw_timestamps if isinstance(timestamp, str)]

    return {
        "last_status": entry.get("last_status") if isinstance(entry.get("last_status"), str) else None,
        "last_changed_at": entry.get("last_changed_at") if isinstance(entry.get("last_changed_at"), str) else None,
        "last_seen_at": entry.get("last_seen_at") if isinstance(entry.get("last_seen_at"), str) else None,
        "change_timestamps": timestamps,
        "flapping": bool(entry.get("flapping")) if isinstance(entry.get("flapping"), bool) else False,
    }


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw_services = payload.get("services")
    services: dict[str, dict[str, Any]] = {}
    if isinstance(raw_services, dict):
        for service_id, entry in raw_services.items():
            if not isinstance(service_id, str):
                continue
            services[service_id] = _normalize_service_entry(entry)

    last_incident = _normalize_incident(payload.get("last_incident"))

    history: list[dict[str, str]] = []
    raw_history = payload.get("incident_history")
    if isinstance(raw_history, list):
        for entry in raw_history:
            normalized = _normalize_incident(entry)
            if normalized is not None:
                history.append(normalized)

    return {
        "services": services,
        "last_incident": last_incident,
        "incident_history": history,
    }


class ObservationsStore:
    def __init__(
        self,
        path: str,
        history_limit: int = 200,
        flap_window_seconds: int = 600,
        flap_threshold: int = 3,
        flap_timestamps_limit: int = 20,
    ):
        self.path = Path(path)
        self.history_limit = max(history_limit, 1)
        self.flap_window_seconds = max(flap_window_seconds, 1)
        self.flap_threshold = max(flap_threshold, 1)
        self.flap_timestamps_limit = max(flap_timestamps_limit, 1)
        self._lock = Lock()
        self._ensure_file()

    def _default_payload(self) -> dict[str, Any]:
        return {
            "services": {},
            "last_incident": None,
            "incident_history": [],
        }

    def _ensure_file(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_unlocked(self._default_payload())
        logger.info("Created observations store at %s", self.path)

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
            if not isinstance(loaded, dict):
                raise ValueError("Observations file must be a JSON object")
            normalized = _normalize_payload(loaded)
            history = normalized["incident_history"]
            if len(history) > self.history_limit:
                normalized["incident_history"] = history[-self.history_limit:]
            return normalized
        except FileNotFoundError:
            payload = self._default_payload()
            self._write_unlocked(payload)
            return payload
        except Exception:
            logger.exception("Failed to read observations file %s; resetting", self.path)
            payload = self._default_payload()
            self._write_unlocked(payload)
            return payload

    def _write_unlocked(self, payload: dict[str, Any]) -> None:
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

    def get_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._read_unlocked())

    def get_service_observation(self, service_id: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._read_unlocked()
            entry = payload["services"].get(service_id)
            if not isinstance(entry, dict):
                return None
            return deepcopy(entry)

    def _public_incident(self, incident: dict[str, str]) -> dict[str, str]:
        return {
            "service_id": incident["service_id"],
            "from": incident["from_status"],
            "to": incident["to_status"],
            "at": incident["at"],
        }

    def get_recent_incidents(self, service_id: str, limit: int = 20) -> list[dict[str, str]]:
        requested_limit = max(limit, 1)
        with self._lock:
            payload = self._read_unlocked()
            history = payload["incident_history"]
            filtered = [incident for incident in history if incident.get("service_id") == service_id]
            selected = list(reversed(filtered))[: min(requested_limit, self.history_limit)]
            return [self._public_incident(incident) for incident in selected]

    def get_global_incidents(self, limit: int = 50) -> list[dict[str, str]]:
        requested_limit = max(limit, 1)
        with self._lock:
            payload = self._read_unlocked()
            history = payload["incident_history"]
            selected = list(reversed(history))[: min(requested_limit, self.history_limit)]
            return [self._public_incident(incident) for incident in selected]

    def _prune_change_timestamps(self, timestamps: list[str], observed_at: datetime) -> list[str]:
        cutoff = observed_at - timedelta(seconds=self.flap_window_seconds)
        normalized: list[str] = []
        for timestamp in timestamps:
            parsed = _parse_iso(timestamp)
            if parsed is None:
                continue
            if parsed >= cutoff:
                normalized.append(_iso(parsed))

        normalized.sort()
        if len(normalized) > self.flap_timestamps_limit:
            normalized = normalized[-self.flap_timestamps_limit :]
        return normalized

    def initialize_services(self, services: list[dict[str, Any]], observed_at: datetime) -> None:
        observed_at_iso = _iso(observed_at)
        with self._lock:
            payload = self._read_unlocked()
            existing = payload["services"]
            changed = False

            for service in services:
                service_id = service.get("id")
                status = service.get("status")
                if not service_id or not isinstance(status, str):
                    continue
                if service_id in existing:
                    continue
                existing[service_id] = {
                    "last_status": status,
                    "last_changed_at": observed_at_iso,
                    "last_seen_at": observed_at_iso,
                    "change_timestamps": [],
                    "flapping": False,
                }
                changed = True

            if changed:
                self._write_unlocked(payload)

    def apply_refresh(self, services: list[dict[str, Any]], observed_at: datetime) -> dict[str, Any]:
        observed_at_iso = _iso(observed_at)
        with self._lock:
            payload = self._read_unlocked()
            service_map: dict[str, dict[str, Any]] = payload["services"]
            history: list[dict[str, Any]] = payload["incident_history"]

            for service in services:
                service_id = service.get("id")
                new_status = service.get("status")
                if not service_id or not isinstance(new_status, str):
                    continue

                existing = service_map.get(service_id)
                if existing is None:
                    service_map[service_id] = {
                        "last_status": new_status,
                        "last_changed_at": observed_at_iso,
                        "last_seen_at": observed_at_iso,
                        "change_timestamps": [],
                        "flapping": False,
                    }
                    continue

                existing = _normalize_service_entry(existing)
                service_map[service_id] = existing
                previous_status = existing.get("last_status")
                if previous_status != new_status and isinstance(previous_status, str):
                    incident = {
                        "service_id": service_id,
                        "from_status": previous_status,
                        "to_status": new_status,
                        "at": observed_at_iso,
                    }
                    payload["last_incident"] = incident
                    history.append(incident)
                    if len(history) > self.history_limit:
                        del history[:-self.history_limit]
                    existing["last_changed_at"] = observed_at_iso
                    existing["change_timestamps"].append(observed_at_iso)

                if not existing.get("last_changed_at"):
                    existing["last_changed_at"] = observed_at_iso

                existing["change_timestamps"] = self._prune_change_timestamps(
                    existing.get("change_timestamps", []),
                    observed_at=observed_at,
                )
                existing["flapping"] = len(existing["change_timestamps"]) >= self.flap_threshold
                existing["last_status"] = new_status
                existing["last_seen_at"] = observed_at_iso

            self._write_unlocked(payload)
            return deepcopy(payload)


observations_store = ObservationsStore(
    path=config.OBSERVATIONS_PATH,
    history_limit=config.OBSERVATIONS_HISTORY_LIMIT,
    flap_window_seconds=config.FLAP_WINDOW_SECONDS,
    flap_threshold=config.FLAP_THRESHOLD,
)
