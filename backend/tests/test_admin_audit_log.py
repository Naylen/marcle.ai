import asyncio

from fastapi.testclient import TestClient

import app.main as main_module
from app.audit_log import AuditLogStore
from app.main import app
from app.models import ServiceConfig, ServiceGroup
from app.state import state


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

    def bulk_set_enabled(self, service_ids, enabled):
        wanted = set(service_ids)
        updated = []
        for i, existing in enumerate(self._services):
            if existing.id not in wanted:
                continue
            updated_service = existing.model_copy(update={"enabled": enabled})
            self._services[i] = updated_service
            updated.append(updated_service)
        return updated


def _service(service_id: str, enabled: bool = True) -> ServiceConfig:
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


def test_admin_audit_requires_auth(monkeypatch):
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service("svc-a")]))
    monkeypatch.setattr(main_module.config, "ADMIN_TOKEN", "admin-token")
    _reset_state()

    client = TestClient(app)
    response = client.get("/api/admin/audit")
    assert response.status_code == 401


def test_admin_audit_limit_is_capped(monkeypatch):
    class CaptureAuditStore:
        def __init__(self):
            self.received_limit = None

        def append(self, payload):
            return None

        def recent(self, limit):
            self.received_limit = limit
            return []

    capture_store = CaptureAuditStore()

    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service("svc-a")]))
    monkeypatch.setattr(main_module, "audit_log_store", capture_store)
    monkeypatch.setattr(main_module.config, "ADMIN_TOKEN", "admin-token")
    _reset_state()

    client = TestClient(app)
    response = client.get(
        "/api/admin/audit?limit=9999",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert response.status_code == 200
    assert capture_store.received_limit == 500


def test_admin_write_actions_append_audit_entries(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.log"
    audit_store = AuditLogStore(str(audit_path), max_bytes=1024 * 1024)

    monkeypatch.setattr(main_module, "audit_log_store", audit_store)
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service("svc-a"), _service("svc-b")]))
    monkeypatch.setattr(main_module.config, "ADMIN_TOKEN", "admin-token")
    _reset_state()

    client = TestClient(app)
    headers = {
        "Authorization": "Bearer admin-token",
        "X-Marcle-Client-IP": "198.51.100.17",
        "X-Marcle-Forwarded-For-Chain": "198.51.100.17, 203.0.113.8",
        "X-Marcle-Actor-Email": "admin@example.com",
        "User-Agent": "audit-test-agent",
    }

    create_response = client.post(
        "/api/admin/services",
        headers=headers,
        json={
            "id": "svc-c",
            "name": "Service C",
            "group": "core",
            "url": "https://svc-c.example.test",
            "check_type": "generic",
            "enabled": True,
        },
    )
    assert create_response.status_code == 201

    update_response = client.put(
        "/api/admin/services/svc-c",
        headers=headers,
        json={
            "id": "svc-c",
            "name": "Service C Updated",
            "group": "core",
            "url": "https://svc-c.example.test",
            "check_type": "generic",
            "enabled": True,
        },
    )
    assert update_response.status_code == 200

    toggle_response = client.post("/api/admin/services/svc-c/toggle", headers=headers)
    assert toggle_response.status_code == 200
    assert toggle_response.json()["enabled"] is False

    bulk_response = client.post(
        "/api/admin/services/bulk",
        headers=headers,
        json={"ids": ["svc-a", "svc-c"], "enabled": False},
    )
    assert bulk_response.status_code == 200
    assert len(bulk_response.json()["services"]) == 2

    delete_response = client.delete("/api/admin/services/svc-c", headers=headers)
    assert delete_response.status_code == 200

    audit_response = client.get("/api/admin/audit?limit=200", headers=headers)
    assert audit_response.status_code == 200
    entries = audit_response.json()
    assert [entry["action"] for entry in entries] == ["delete", "bulk", "toggle", "update", "create"]

    delete_entry = entries[0]
    assert delete_entry["service_id"] == "svc-c"
    assert delete_entry["ip"] == "198.51.100.17"
    assert delete_entry["forwarded_for_chain"] == "198.51.100.17, 203.0.113.8"
    assert delete_entry["actor_email"] == "admin@example.com"
    assert delete_entry["user_agent"] == "audit-test-agent"

    bulk_entry = entries[1]
    assert bulk_entry["service_id"] is None
    assert bulk_entry["ids"] == ["svc-a", "svc-c"]
    assert bulk_entry["enabled"] is False

    toggle_entry = entries[2]
    assert toggle_entry["service_id"] == "svc-c"
    assert toggle_entry["enabled"] is False

    raw_log = audit_path.read_text(encoding="utf-8")
    assert "admin-token" not in raw_log


def test_audit_write_failure_does_not_break_admin_action(monkeypatch):
    class FailingAuditStore:
        def append(self, payload):
            raise RuntimeError("disk full")

        def recent(self, limit):
            return []

    monkeypatch.setattr(main_module, "audit_log_store", FailingAuditStore())
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service("svc-a")]))
    monkeypatch.setattr(main_module.config, "ADMIN_TOKEN", "admin-token")
    _reset_state()

    client = TestClient(app)
    response = client.post(
        "/api/admin/services",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "id": "svc-b",
            "name": "Service B",
            "group": "core",
            "url": "https://svc-b.example.test",
            "check_type": "generic",
            "enabled": True,
        },
    )

    assert response.status_code == 201
    list_response = client.get(
        "/api/admin/services",
        headers={"Authorization": "Bearer admin-token"},
    )
    assert list_response.status_code == 200
    ids = {service["id"] for service in list_response.json()["services"]}
    assert "svc-b" in ids
