"""Simple in-memory TTL cache for the aggregated status response."""

import time
from typing import Optional

from app.models import StatusResponse


class StatusCache:
    def __init__(self, ttl_seconds: int = 45):
        self._ttl = ttl_seconds
        self._data: Optional[StatusResponse] = None
        self._timestamp: float = 0.0

    def get(self) -> Optional[StatusResponse]:
        if self._data is None:
            return None
        if (time.monotonic() - self._timestamp) > self._ttl:
            return None
        return self._data

    def set(self, data: StatusResponse) -> None:
        self._data = data
        self._timestamp = time.monotonic()


cache = StatusCache()
