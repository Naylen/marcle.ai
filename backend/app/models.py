"""Response models for the status API."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ServiceGroup(str, Enum):
    CORE = "core"
    MEDIA = "media"
    AUTOMATION = "automation"


class Status(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class OverallStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class ServiceStatus(BaseModel):
    id: str
    name: str
    group: ServiceGroup
    status: Status = Status.UNKNOWN
    latency_ms: Optional[int] = None
    url: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    last_checked: datetime = Field(default_factory=datetime.utcnow)


class StatusResponse(BaseModel):
    generated_at: datetime
    overall_status: OverallStatus
    services: list[ServiceStatus]
