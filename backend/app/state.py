"""In-memory runtime state for cached status payloads and refresh signaling."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


class StatusState:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_full_payload: dict[str, Any] | None = None
        self._per_service: dict[str, dict[str, Any]] = {}
        self._last_refresh_at: datetime | None = None
        self._last_refresh_duration_ms: int | None = None
        self._needs_refresh = asyncio.Event()

    async def get_cached_payload(self) -> dict[str, Any] | None:
        async with self._lock:
            if self._last_full_payload is None:
                return None
            return deepcopy(self._last_full_payload)

    async def set_cached_payload(
        self,
        payload: Mapping[str, Any],
        *,
        refreshed_at: datetime | None = None,
        refresh_duration_ms: int | None = None,
    ) -> None:
        per_service: dict[str, dict[str, Any]] = {}
        services = payload.get("services", [])
        if isinstance(services, list):
            for service in services:
                if not isinstance(service, Mapping):
                    continue
                service_id = service.get("id")
                if not service_id:
                    continue
                per_service[str(service_id)] = {
                    "status": service.get("status"),
                    "last_checked": service.get("last_checked"),
                }

        payload_copy = deepcopy(dict(payload))
        async with self._lock:
            self._last_full_payload = payload_copy
            self._per_service = per_service
            self._last_refresh_at = refreshed_at or datetime.now(timezone.utc)
            self._last_refresh_duration_ms = refresh_duration_ms

    async def clear_cached_payload(self) -> None:
        async with self._lock:
            self._last_full_payload = None
            self._per_service = {}
            self._last_refresh_at = None
            self._last_refresh_duration_ms = None
        self._needs_refresh.clear()

    async def mark_needs_refresh(self) -> None:
        self._needs_refresh.set()

    async def consume_needs_refresh(self) -> bool:
        if not self._needs_refresh.is_set():
            return False
        self._needs_refresh.clear()
        return True

    async def wait_for_refresh_signal(self, timeout_seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._needs_refresh.wait(), timeout=timeout_seconds)
            self._needs_refresh.clear()
            return True
        except asyncio.TimeoutError:
            return False


state = StatusState()


async def get_cached_payload() -> dict[str, Any] | None:
    return await state.get_cached_payload()


async def set_cached_payload(
    payload: Mapping[str, Any],
    *,
    refreshed_at: datetime | None = None,
    refresh_duration_ms: int | None = None,
) -> None:
    await state.set_cached_payload(
        payload,
        refreshed_at=refreshed_at,
        refresh_duration_ms=refresh_duration_ms,
    )


async def mark_needs_refresh() -> None:
    await state.mark_needs_refresh()


async def clear_cached_payload() -> None:
    await state.clear_cached_payload()
