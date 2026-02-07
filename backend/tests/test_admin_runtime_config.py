from fastapi.testclient import TestClient

from app.cache import cache
from app.main import app
from app.models import ServiceConfig, ServiceGroup
import app.main as main_module


class FakeConfigStore:
    def __init__(self, services):
        self._services = list(services)

    def list_services(self):
        return list(self._services)

    def create_service(self, service):
        if any(existing.id == service.id for existing in self._services):
            raise ValueError(f"Service '{service.id}' already exists")
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


def _service(service_id: str, enabled: bool = True) -> ServiceConfig:
    return ServiceConfig(
        id=service_id,
        name=f"Service {service_id}",
        group=ServiceGroup.CORE,
        url="https://example.test",
        check_type="generic",
        enabled=enabled,
    )


def test_admin_requires_auth_header(monkeypatch):
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service("svc-a")]))
    monkeypatch.setattr(main_module.config, "ADMIN_TOKEN", "admin-token")
    cache.clear()

    client = TestClient(app)
    response = client.get("/api/admin/services")

    assert response.status_code == 401


def test_admin_delete_and_toggle(monkeypatch):
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service("svc-a"), _service("svc-b")]))
    monkeypatch.setattr(main_module.config, "ADMIN_TOKEN", "admin-token")
    cache.clear()

    client = TestClient(app)
    headers = {"Authorization": "Bearer admin-token"}

    toggle_response = client.post("/api/admin/services/svc-a/toggle", headers=headers)
    assert toggle_response.status_code == 200
    assert toggle_response.json()["enabled"] is False

    delete_response = client.delete("/api/admin/services/svc-b", headers=headers)
    assert delete_response.status_code == 200
    assert delete_response.json()["id"] == "svc-b"

    list_response = client.get("/api/admin/services", headers=headers)
    assert list_response.status_code == 200
    services = list_response.json()["services"]
    assert len(services) == 1
    assert services[0]["id"] == "svc-a"
    assert services[0]["enabled"] is False
