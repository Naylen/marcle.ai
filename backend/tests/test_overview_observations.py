import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.models import ServiceConfig, ServiceGroup
from app.observations_store import ObservationsStore
from app.state import state


class FakeConfigStore:
    def __init__(self, services):
        self._services = list(services)

    def list_services(self):
        return list(self._services)


class FakeObservationsStore:
    def __init__(self, snapshot=None):
        self._snapshot = snapshot or {
            "services": {},
            "last_incident": None,
            "incident_history": [],
        }
        self.initialized_with = []
        self.applied_with = []
        self.global_limits = []
        self.service_incident_requests = []

    def initialize_services(self, services, observed_at):
        self.initialized_with.append((services, observed_at))
        for service in services:
            service_id = service.get("id")
            status = service.get("status")
            if not service_id or not status:
                continue
            self._snapshot["services"].setdefault(
                service_id,
                {
                    "last_status": status,
                    "last_changed_at": observed_at.isoformat(),
                    "last_seen_at": observed_at.isoformat(),
                    "change_timestamps": [],
                    "flapping": False,
                },
            )

    def apply_refresh(self, services, observed_at):
        self.applied_with.append((services, observed_at))
        return self._snapshot

    def get_snapshot(self):
        return self._snapshot

    def get_global_incidents(self, limit):
        self.global_limits.append(limit)
        incidents = list(reversed(self._snapshot.get("incident_history", [])))
        return [
            {
                "service_id": incident["service_id"],
                "from": incident["from_status"],
                "to": incident["to_status"],
                "at": incident["at"],
            }
            for incident in incidents[:limit]
        ]

    def get_service_observation(self, service_id):
        return self._snapshot.get("services", {}).get(service_id)

    def get_recent_incidents(self, service_id, limit):
        self.service_incident_requests.append((service_id, limit))
        incidents = [
            incident
            for incident in self._snapshot.get("incident_history", [])
            if incident.get("service_id") == service_id
        ]
        incidents.reverse()
        return [
            {
                "service_id": incident["service_id"],
                "from": incident["from_status"],
                "to": incident["to_status"],
                "at": incident["at"],
            }
            for incident in incidents[:limit]
        ]


def _service(service_id: str) -> ServiceConfig:
    return ServiceConfig(
        id=service_id,
        name=f"Service {service_id}",
        group=ServiceGroup.CORE,
        url="https://example.test",
        check_type="generic",
        enabled=True,
    )


def _reset_state() -> None:
    asyncio.run(state.clear_cached_payload())


def test_observations_store_tracks_incidents_and_last_change(tmp_path):
    store = ObservationsStore(str(tmp_path / "observations.json"), history_limit=2)
    t0 = datetime(2026, 2, 8, 1, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=1)
    t2 = t0 + timedelta(minutes=2)
    t3 = t0 + timedelta(minutes=3)
    t4 = t0 + timedelta(minutes=4)

    store.apply_refresh([{"id": "svc-a", "status": "healthy"}], t0)
    stable_snapshot = store.apply_refresh([{"id": "svc-a", "status": "healthy"}], t1)
    service_entry = stable_snapshot["services"]["svc-a"]
    assert service_entry["last_status"] == "healthy"
    assert service_entry["last_changed_at"].startswith("2026-02-08T01:00:00")
    assert service_entry["last_seen_at"].startswith("2026-02-08T01:01:00")

    changed_snapshot = store.apply_refresh([{"id": "svc-a", "status": "down"}], t2)
    assert changed_snapshot["last_incident"]["service_id"] == "svc-a"
    assert changed_snapshot["last_incident"]["from_status"] == "healthy"
    assert changed_snapshot["last_incident"]["to_status"] == "down"
    assert changed_snapshot["services"]["svc-a"]["last_changed_at"].startswith("2026-02-08T01:02:00")

    store.apply_refresh([{"id": "svc-a", "status": "unknown"}], t3)
    capped = store.apply_refresh([{"id": "svc-a", "status": "healthy"}], t4)
    assert len(capped["incident_history"]) == 2
    assert capped["incident_history"][0]["from_status"] == "down"
    assert capped["incident_history"][1]["to_status"] == "healthy"


def test_observations_store_detects_flapping(tmp_path):
    store = ObservationsStore(
        str(tmp_path / "observations.json"),
        flap_window_seconds=600,
        flap_threshold=3,
        flap_timestamps_limit=20,
    )
    base = datetime(2026, 2, 8, 1, 0, tzinfo=timezone.utc)
    transitions = [
        ("healthy", base),
        ("down", base + timedelta(minutes=1)),
        ("healthy", base + timedelta(minutes=2)),
        ("down", base + timedelta(minutes=3)),
    ]
    for status_value, at in transitions:
        store.apply_refresh([{"id": "svc-a", "status": status_value}], at)

    flapping = store.get_service_observation("svc-a")
    assert flapping is not None
    assert flapping["flapping"] is True
    assert len(flapping["change_timestamps"]) >= 3

    later = base + timedelta(minutes=20)
    store.apply_refresh([{"id": "svc-a", "status": "down"}], later)
    stable_again = store.get_service_observation("svc-a")
    assert stable_again is not None
    assert stable_again["flapping"] is False


def test_set_startup_payload_initializes_observations(monkeypatch):
    fake_observations = FakeObservationsStore()
    monkeypatch.setattr(main_module, "config_store", FakeConfigStore([_service("svc-a")]))
    monkeypatch.setattr(main_module, "observations_store", fake_observations)
    _reset_state()

    payload = asyncio.run(main_module._set_startup_payload())

    assert payload["services"][0]["status"] == "unknown"
    assert len(fake_observations.initialized_with) == 1
    initialized_services, _ = fake_observations.initialized_with[0]
    assert initialized_services[0]["id"] == "svc-a"


def test_overview_returns_counts_cache_age_and_incident(monkeypatch):
    fake_snapshot = {
        "services": {
            "svc-a": {
                "last_status": "healthy",
                "last_changed_at": "2026-02-08T00:00:00+00:00",
                "last_seen_at": "2026-02-08T00:10:00+00:00",
            },
            "svc-b": {
                "last_status": "down",
                "last_changed_at": "2026-02-08T00:20:00+00:00",
                "last_seen_at": "2026-02-08T00:20:00+00:00",
            },
        },
        "last_incident": {
            "service_id": "svc-b",
            "from_status": "healthy",
            "to_status": "down",
            "at": "2026-02-08T00:20:00+00:00",
        },
        "incident_history": [],
    }
    monkeypatch.setattr(main_module, "observations_store", FakeObservationsStore(snapshot=fake_snapshot))
    _reset_state()

    refreshed_at = datetime.now(timezone.utc) - timedelta(seconds=12)
    asyncio.run(
        state.set_cached_payload(
            {
                "generated_at": "2026-02-08T00:21:00+00:00",
                "overall_status": "degraded",
                "services": [
                    {"id": "svc-a", "status": "healthy"},
                    {"id": "svc-b", "status": "down"},
                    {"id": "svc-c", "status": "unknown"},
                ],
            },
            refreshed_at=refreshed_at,
            refresh_duration_ms=9,
        )
    )

    overview = asyncio.run(main_module.get_overview())

    assert overview["counts"]["healthy"] == 1
    assert overview["counts"]["down"] == 1
    assert overview["counts"]["unknown"] == 1
    assert overview["counts"]["total"] == 3
    assert isinstance(overview["cache_age_seconds"], int)
    assert overview["cache_age_seconds"] >= 0
    assert overview["last_incident"]["service_id"] == "svc-b"
    assert overview["last_incident"]["from"] == "healthy"
    assert overview["last_incident"]["to"] == "down"
    services = {service["id"]: service for service in overview["services"]}
    assert services["svc-a"]["last_changed_at"] == "2026-02-08T00:00:00+00:00"
    assert services["svc-b"]["last_status"] == "down"
    assert services["svc-c"]["last_changed_at"] is None


def test_incidents_endpoint_limits_and_returns_recent_first(monkeypatch):
    fake_snapshot = {
        "services": {},
        "last_incident": None,
        "incident_history": [
            {"service_id": "svc-a", "from_status": "healthy", "to_status": "down", "at": "2026-02-08T00:01:00+00:00"},
            {"service_id": "svc-b", "from_status": "healthy", "to_status": "down", "at": "2026-02-08T00:02:00+00:00"},
            {"service_id": "svc-c", "from_status": "healthy", "to_status": "down", "at": "2026-02-08T00:03:00+00:00"},
        ],
    }
    fake_store = FakeObservationsStore(snapshot=fake_snapshot)
    monkeypatch.setattr(main_module, "observations_store", fake_store)
    _reset_state()

    client = TestClient(app)
    response = client.get("/api/incidents?limit=500")

    assert response.status_code == 200
    payload = response.json()
    assert fake_store.global_limits[-1] == 200
    assert payload[0]["service_id"] == "svc-c"
    assert payload[1]["service_id"] == "svc-b"
    assert payload[2]["service_id"] == "svc-a"


def test_service_details_endpoint_omits_url_unless_enabled(monkeypatch):
    fake_snapshot = {
        "services": {
            "svc-a": {
                "last_status": "healthy",
                "last_changed_at": "2026-02-08T00:00:00+00:00",
                "last_seen_at": "2026-02-08T00:01:00+00:00",
                "change_timestamps": [],
                "flapping": False,
            },
        },
        "last_incident": None,
        "incident_history": [],
    }
    fake_store = FakeObservationsStore(snapshot=fake_snapshot)
    monkeypatch.setattr(main_module, "observations_store", fake_store)
    monkeypatch.setattr(main_module.config, "EXPOSE_SERVICE_URLS", False)
    _reset_state()
    asyncio.run(
        state.set_cached_payload(
            {
                "generated_at": "2026-02-08T00:21:00+00:00",
                "overall_status": "healthy",
                "services": [
                    {
                        "id": "svc-a",
                        "name": "Service A",
                        "group": "core",
                        "status": "healthy",
                        "latency_ms": 42,
                        "url": "https://internal.example.test",
                        "description": "test",
                        "icon": "svc-a.svg",
                        "last_checked": "2026-02-08T00:21:00+00:00",
                    }
                ],
            },
            refreshed_at=datetime.now(timezone.utc),
            refresh_duration_ms=5,
        )
    )

    client = TestClient(app)
    response = client.get("/api/services/svc-a")
    assert response.status_code == 200
    service = response.json()["service"]
    assert service["id"] == "svc-a"
    assert service["last_changed_at"] == "2026-02-08T00:00:00+00:00"
    assert service["flapping"] is False
    assert "url" not in service

    monkeypatch.setattr(main_module.config, "EXPOSE_SERVICE_URLS", True)
    response_with_url = client.get("/api/services/svc-a")
    assert response_with_url.status_code == 200
    assert response_with_url.json()["service"]["url"] == "https://internal.example.test"

    not_found = client.get("/api/services/unknown")
    assert not_found.status_code == 404
