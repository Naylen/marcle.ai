"""Response models for the status API."""

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


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


class AuthRef(BaseModel):
    scheme: Literal["none", "bearer", "basic", "header"] = "none"
    env: Optional[str] = None
    header_name: Optional[str] = None

    @model_validator(mode="after")
    def validate_auth_ref(self):
        if self.scheme == "header" and not (self.header_name or "").strip():
            raise ValueError("header_name is required when scheme='header'")
        if self.scheme != "none" and not (self.env or "").strip():
            raise ValueError("env is required when scheme is not 'none'")
        return self


class ServiceConfig(BaseModel):
    id: str
    name: str
    group: ServiceGroup
    url: str
    check_type: str
    enabled: bool = True
    icon: Optional[str] = None
    description: Optional[str] = None
    path: Optional[str] = None
    verify_ssl: bool = False
    healthy_status_codes: Optional[list[int]] = None
    auth_ref: Optional[AuthRef] = None


class ServicesConfigResponse(BaseModel):
    services: list[ServiceConfig]
