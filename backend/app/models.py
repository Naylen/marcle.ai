"""Response and configuration models for the status API."""

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Auth reference (env-backed credentials — never stores secret values)
# ---------------------------------------------------------------------------

class AuthRef(BaseModel):
    """Reference to an environment variable holding a secret.

    The *value* of the secret is never stored here — only the env var name.
    """
    scheme: Literal["none", "bearer", "basic", "header"] = "none"
    env: str = ""
    header_name: Optional[str] = None  # required when scheme="header"

    @model_validator(mode="after")
    def _validate_auth_ref(self) -> "AuthRef":
        if self.scheme != "none" and not self.env:
            raise ValueError(
                f"auth_ref with scheme={self.scheme!r} requires a non-empty 'env' field"
            )
        if self.scheme == "header" and not self.header_name:
            raise ValueError(
                "auth_ref with scheme='header' requires 'header_name'"
            )
        return self


# ---------------------------------------------------------------------------
# Service configuration (persisted in services.json — safe to commit)
# ---------------------------------------------------------------------------

class ServiceConfig(BaseModel):
    """Declarative definition of a monitored service."""
    id: str
    name: str
    group: ServiceGroup
    url: str = ""
    path: str = "/"
    icon: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True
    verify_ssl: bool = False
    healthy_status_codes: list[int] = Field(default_factory=lambda: [200])
    auth_ref: Optional[AuthRef] = None
    extra_headers: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Status response models (public API output)
# ---------------------------------------------------------------------------

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
