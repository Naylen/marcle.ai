from types import SimpleNamespace

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
        self._services.append(service)

    def upsert_service(self, service):
        for i, existing in enumerate(self._services):
            if existing.id == service.id:
                self._services[i] = service
                return
        self._services.append(service)


def _service_with_auth(auth_ref: AuthRef | None) -> ServiceConfig:
    return ServiceConfig(
        id="auth-test",
        name="Auth Test",
        group=ServiceGroup.CORE,
        url="https://example.test",
        check_type="generic",
        enabled=True,
        auth_ref=auth_ref,
    )


def test_status_is_unknown_when_auth_env_is_missing(monkeypatch):
    service = _service_with_auth(AuthRef(scheme="bearer", env="AUTH_TEST_TOKEN"))
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([service]))
    monkeypatch.delenv("AUTH_TEST_TOKEN", raising=False)

    class FailingAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            raise AssertionError("Upstream request should not run when credential env is missing")

    monkeypatch.setattr("app.services.httpx.AsyncClient", FailingAsyncClient)

    cache.clear()
    client = TestClient(app)
    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["services"][0]["status"] == "unknown"


def test_status_sends_bearer_header_when_auth_env_exists(monkeypatch):
    service = _service_with_auth(AuthRef(scheme="bearer", env="AUTH_TEST_TOKEN"))
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([service]))
    monkeypatch.setenv("AUTH_TEST_TOKEN", "super-secret-token")

    captured_headers = {}

    class CaptureAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            captured_headers.update(kwargs.get("headers") or {})
            return SimpleNamespace(status_code=200)

    monkeypatch.setattr("app.services.httpx.AsyncClient", CaptureAsyncClient)

    cache.clear()
    client = TestClient(app)
    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["services"][0]["status"] == "healthy"
    assert captured_headers["Authorization"] == "Bearer super-secret-token"


def test_admin_services_returns_auth_ref_metadata_without_secret_values(monkeypatch):
    service = _service_with_auth(AuthRef(scheme="bearer", env="AUTH_TEST_TOKEN"))
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([service]))
    monkeypatch.setattr(main_module.config, "ADMIN_TOKEN", "admin-test-token")
    monkeypatch.setenv("AUTH_TEST_TOKEN", "do-not-leak-this")

    client = TestClient(app)
    response = client.get(
        "/api/admin/services",
        headers={"Authorization": "Bearer admin-test-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["services"][0]["auth_ref"]["scheme"] == "bearer"
    assert payload["services"][0]["auth_ref"]["env"] == "AUTH_TEST_TOKEN"
    assert "do-not-leak-this" not in response.text
