from fastapi.testclient import TestClient

from app.cache import cache
from app.main import app
from app.models import AuthRef, ServiceConfig, ServiceGroup
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


def test_admin_create_and_update_service_with_auth_ref(monkeypatch):
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service("svc-a")]))
    monkeypatch.setattr(main_module.config, "ADMIN_TOKEN", "admin-token")
    cache.clear()

    client = TestClient(app)
    headers = {"Authorization": "Bearer admin-token"}

    create_payload = {
        "id": "svc-auth",
        "name": "Service Auth",
        "group": "core",
        "url": "https://svc-auth.example.test",
        "check_type": "generic",
        "enabled": True,
        "auth_ref": {
            "scheme": "header",
            "env": "SVC_API_KEY",
            "header_name": "X-Api-Key",
        },
    }
    create_response = client.post("/api/admin/services", headers=headers, json=create_payload)
    assert create_response.status_code == 201
    assert create_response.json()["auth_ref"]["scheme"] == "header"
    assert create_response.json()["auth_ref"]["env"] == "SVC_API_KEY"
    assert create_response.json()["auth_ref"]["header_name"] == "X-Api-Key"

    update_payload = {
        "id": "svc-auth",
        "name": "Service Auth",
        "group": "core",
        "url": "https://svc-auth.example.test",
        "check_type": "generic",
        "enabled": True,
        "auth_ref": {
            "scheme": "basic",
            "env": "UNIFI_BASIC_AUTH",
        },
    }
    update_response = client.put("/api/admin/services/svc-auth", headers=headers, json=update_payload)
    assert update_response.status_code == 200
    assert update_response.json()["auth_ref"]["scheme"] == "basic"
    assert update_response.json()["auth_ref"]["env"] == "UNIFI_BASIC_AUTH"


def test_admin_credential_present_computed(monkeypatch):
    with_auth = ServiceConfig(
        id="svc-auth",
        name="Service Auth",
        group=ServiceGroup.CORE,
        url="https://svc-auth.example.test",
        check_type="generic",
        enabled=True,
        auth_ref=AuthRef(scheme="bearer", env="MISSING_ENV"),
    )
    no_auth = ServiceConfig(
        id="svc-no-auth",
        name="Service No Auth",
        group=ServiceGroup.CORE,
        url="https://svc-no-auth.example.test",
        check_type="generic",
        enabled=True,
    )
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([with_auth, no_auth]))
    monkeypatch.setattr(main_module.config, "ADMIN_TOKEN", "admin-token")
    monkeypatch.delenv("MISSING_ENV", raising=False)
    cache.clear()

    client = TestClient(app)
    headers = {"Authorization": "Bearer admin-token"}
    response = client.get("/api/admin/services", headers=headers)

    assert response.status_code == 200
    services = {service["id"]: service for service in response.json()["services"]}
    assert services["svc-auth"]["credential_present"] is False
    assert services["svc-no-auth"]["credential_present"] is None

    monkeypatch.setenv("MISSING_ENV", "present-now")
    response_after_env = client.get("/api/admin/services", headers=headers)
    assert response_after_env.status_code == 200
    services_after = {service["id"]: service for service in response_after_env.json()["services"]}
    assert services_after["svc-auth"]["credential_present"] is True


def test_status_response_does_not_include_credential_present(monkeypatch):
    service = ServiceConfig(
        id="svc-status",
        name="Service Status",
        group=ServiceGroup.CORE,
        url="",
        check_type="generic",
        enabled=True,
        auth_ref=AuthRef(scheme="bearer", env="SOME_ENV"),
    )
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([service]))
    cache.clear()

    client = TestClient(app)
    response = client.get("/api/status")

    assert response.status_code == 200
    service_payload = response.json()["services"][0]
    assert "credential_present" not in service_payload
