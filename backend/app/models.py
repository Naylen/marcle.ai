"""Response models for the status API."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


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
    extra: Optional[dict[str, Any]] = None
    last_checked: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusResponse(BaseModel):
    generated_at: datetime
    overall_status: OverallStatus
    services: list[ServiceStatus]


class AuthRef(BaseModel):
    scheme: Literal["none", "bearer", "basic", "header", "query_param"] = "none"
    env: Optional[str] = None
    header_name: Optional[str] = None
    param_name: Optional[str] = None

    @field_validator("env", "header_name", "param_name", mode="before")
    @classmethod
    def normalize_optional_string(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def validate_auth_ref(self):
        scheme = (self.scheme or "none").strip()

        if scheme == "none":
            self.scheme = "none"
            self.env = None
            self.header_name = None
            self.param_name = None
            return self

        if not self.env:
            raise ValueError("env is required when scheme is not 'none'")

        if scheme == "header":
            self.param_name = None
            if not self.header_name:
                raise ValueError("header_name is required when scheme='header'")
            return self

        if scheme == "query_param":
            self.header_name = None
            if not self.param_name:
                raise ValueError("param_name is required when scheme='query_param'")
            return self

        self.header_name = None
        self.param_name = None
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


class AdminServiceConfig(ServiceConfig):
    credential_present: Optional[bool] = None


class AdminServicesConfigResponse(BaseModel):
    services: list[AdminServiceConfig]


class AdminBulkServicesRequest(BaseModel):
    ids: list[str] = Field(min_length=1)
    enabled: bool

    @field_validator("ids", mode="before")
    @classmethod
    def normalize_ids(cls, value):
        if not isinstance(value, list):
            return value

        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            service_id = item.strip()
            if not service_id or service_id in seen:
                continue
            normalized.append(service_id)
            seen.add(service_id)
        return normalized


class NotificationEndpointFilters(BaseModel):
    groups: list[ServiceGroup] = Field(default_factory=list)
    service_ids: list[str] = Field(default_factory=list)
    min_severity: Literal["any", "degraded", "down"] = "any"
    cooldown_seconds: int = Field(default=0, ge=0)

    @field_validator("service_ids", mode="before")
    @classmethod
    def normalize_service_ids(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",")]
        if not isinstance(value, list):
            return value

        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            service_id = item.strip()
            if not service_id or service_id in seen:
                continue
            normalized.append(service_id)
            seen.add(service_id)
        return normalized


class NotificationEndpoint(BaseModel):
    id: str
    url: str
    events: list[Literal["incident", "recovery", "flapping"]] = Field(default_factory=lambda: ["incident"])
    filters: NotificationEndpointFilters = Field(default_factory=NotificationEndpointFilters)
    auth_ref: AuthRef | None = None

    @field_validator("id", "url", mode="before")
    @classmethod
    def normalize_required_string(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("events", mode="before")
    @classmethod
    def normalize_events(cls, value):
        if value is None:
            return ["incident"]
        if not isinstance(value, list):
            return value
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            event_name = item.strip().lower()
            if event_name not in {"incident", "recovery", "flapping"}:
                continue
            if event_name in seen:
                continue
            normalized.append(event_name)
            seen.add(event_name)
        return normalized

    @model_validator(mode="after")
    def validate_endpoint(self):
        if not self.id:
            raise ValueError("id is required")
        if not self.url:
            raise ValueError("url is required")
        if not self.events:
            raise ValueError("at least one event is required")
        return self


class NotificationsConfig(BaseModel):
    enabled: bool = False
    endpoints: list[NotificationEndpoint] = Field(default_factory=list)

    @field_validator("endpoints", mode="after")
    @classmethod
    def validate_unique_endpoint_ids(cls, endpoints: list[NotificationEndpoint]):
        seen: set[str] = set()
        for endpoint in endpoints:
            if endpoint.id in seen:
                raise ValueError(f"Duplicate endpoint id '{endpoint.id}'")
            seen.add(endpoint.id)
        return endpoints


class AdminNotificationEndpoint(NotificationEndpoint):
    credential_present: bool | None = None


class AdminNotificationsConfigResponse(BaseModel):
    enabled: bool = False
    endpoints: list[AdminNotificationEndpoint] = Field(default_factory=list)


class AdminAuditEntry(BaseModel):
    ts: datetime
    action: Literal["create", "update", "delete", "toggle", "bulk", "notifications_update", "notifications_test"]
    service_id: Optional[str] = None
    ids: Optional[list[str]] = None
    enabled: Optional[bool] = None
    ip: Optional[str] = None
    forwarded_for_chain: Optional[str] = None
    actor_email: Optional[str] = None
    user_agent: Optional[str] = None
