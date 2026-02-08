import asyncio
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.models import ServiceConfig, ServiceGroup
from app.state import state
import app.main as main_module


class FakeConfigStore:
    def __init__(self, services):
        self._services = list(services)

    def list_services(self):
        return list(self._services)

    def create_service(self, service):
        self._services.append(service)

    def upsert_service(self, service):
        for i, existing in enumerate(self._services):
            if existing.id == service.id:
                self._services[i] = service
                return
        self._services.append(service)

    def delete_service(self, service_id):
        for i, existing in enumerate(self._services):
            if existing.id == service_id:
                return self._services.pop(i)
        return None

    def toggle_service(self, service_id):
        for i, existing in enumerate(self._services):
            if existing.id != service_id:
                continue
            updated = existing.model_copy(update={"enabled": not existing.enabled})
            self._services[i] = updated
            return updated
        return None


def _service(service_id: str = "svc-a", enabled: bool = True) -> ServiceConfig:
    return ServiceConfig(
        id=service_id,
        name=f"Service {service_id}",
        group=ServiceGroup.CORE,
        url="https://example.test",
        check_type="generic",
        enabled=enabled,
    )


def _reset_state() -> None:
    asyncio.run(state.clear_cached_payload())


def test_status_empty_cache_returns_unknown_payload(monkeypatch):
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service()]))
    _reset_state()

    client = TestClient(app)
    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "degraded"
    assert payload["services"][0]["status"] == "unknown"
    assert payload["services"][0]["latency_ms"] is None
    datetime.fromisoformat(payload["generated_at"])
    datetime.fromisoformat(payload["services"][0]["last_checked"])


def test_status_serves_cached_payload_without_rebuilding(monkeypatch):
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service()]))
    _reset_state()

    cached_payload = {
        "generated_at": "2026-02-07T00:00:00+00:00",
        "overall_status": "healthy",
        "services": [],
    }
    asyncio.run(state.set_cached_payload(cached_payload))

    async def _fail_if_called():
        raise AssertionError("_set_startup_payload should not be called when cache is populated")

    monkeypatch.setattr(main_module, "_set_startup_payload", _fail_if_called)

    client = TestClient(app)
    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == cached_payload["overall_status"]
    assert payload["services"] == cached_payload["services"]
    assert payload["generated_at"].startswith("2026-02-07T00:00:00")


def test_status_hides_service_urls_when_not_exposed(monkeypatch):
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service()]))
    monkeypatch.setattr(main_module.config, "EXPOSE_SERVICE_URLS", False)
    _reset_state()

    cached_payload = {
        "generated_at": "2026-02-07T00:00:00+00:00",
        "overall_status": "healthy",
        "services": [
            {
                "id": "svc-a",
                "name": "Service svc-a",
                "group": "core",
                "status": "healthy",
                "latency_ms": 12,
                "url": "https://internal.example.test",
                "description": "test",
                "icon": "svc-a.svg",
                "last_checked": "2026-02-07T00:00:00+00:00",
            }
        ],
    }
    asyncio.run(state.set_cached_payload(cached_payload))

    client = TestClient(app)
    hidden_response = client.get("/api/status")
    assert hidden_response.status_code == 200
    hidden_service = hidden_response.json()["services"][0]
    assert hidden_service["url"] is None

    monkeypatch.setattr(main_module.config, "EXPOSE_SERVICE_URLS", True)
    visible_response = client.get("/api/status")
    assert visible_response.status_code == 200
    visible_service = visible_response.json()["services"][0]
    assert visible_service["url"] == "https://internal.example.test"


def test_status_no_wildcard_cors_header_by_default(monkeypatch):
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service()]))
    _reset_state()

    client = TestClient(app)
    response = client.get("/api/status", headers={"Origin": "https://example.com"})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") != "*"


def test_admin_create_marks_refresh(monkeypatch):
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service("existing")]))
    monkeypatch.setattr(main_module.config, "ADMIN_TOKEN", "admin-token")
    _reset_state()

    client = TestClient(app)
    response = client.post(
        "/api/admin/services",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "id": "new-service",
            "name": "New Service",
            "group": "core",
            "url": "https://new.example.test",
            "check_type": "generic",
            "enabled": True,
        },
    )

    assert response.status_code == 201
    assert asyncio.run(state.consume_needs_refresh()) is True
