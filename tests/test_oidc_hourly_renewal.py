"""No live credentials or network calls: bounded hourly OIDC maintenance tests."""
from dataclasses import dataclass
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.runtime_v6.domains.acquisition.rotating_oidc import Credential, RotationBlocked
from src.runtime_v6.domains.report_plane import oidc_hourly_renewal as hourly


class Store:
    def __init__(self, *, expiry=2000, phase="READY", token="dummy-original-access"):
        self.state = Credential(1, phase, "dummy-original-refresh", token, expiry)
        self.reads = 0

    def load(self):
        self.reads += 1
        return self.state


class Manager:
    def __init__(self, store):
        self.store = store
        self.calls = 0
        self.windows = []

    def get_access_token(self, *, refresh_before_seconds=90):
        self.calls += 1
        self.windows.append(refresh_before_seconds)
        self.store.state = replace(
            self.store.state, phase="READY", version=self.store.state.version + 2,
            refresh_token="dummy-replacement-refresh", access_token="dummy-new-access",
            expires_at=5000,
        )
        return self.store.state.access_token


class Client:
    calls = []

    def __init__(self, *, auth_material):
        assert auth_material.mode == "bearer_token"
        assert auth_material.headers["X-API-Authorization"] == "Bearer dummy-new-access"
        self.auth_configuration_state = "CONFIGURED"
        self.auth_material = auth_material
        self.auth_available = True

    def me(self):
        type(self).calls.append("me")
        return {"status": "LIVE", "http_status": 200,
                "payload": {"player": {"entry": 3462711}}}

    def my_team(self, entry_id):
        type(self).calls.append("my_team")
        assert entry_id == 3462711
        return {
            "status": "LIVE", "http_status": 200,
            "payload": {
                "picks": [{"element": i, "purchase_price": 40, "selling_price": 45}
                          for i in range(1, 16)],
                "transfers": {"bank": 2, "free_transfers": 1},
            },
        }


def test_hourly_reuses_healthy_access_without_rotating_or_http():
    store = Store(expiry=2000)
    manager = Manager(store)
    Client.calls = []
    result = hourly.check_hourly(store=store, manager=manager, entry_id=3462711,
                                 client_factory=Client, clock=lambda: 1000)
    assert result == {"state": "REUSED_FRESH", "credential_version": 1, "grant_sent": False}
    assert manager.calls == 0
    assert Client.calls == []


def test_hourly_near_expiry_invokes_bounded_rotation_once_and_validates():
    store = Store(expiry=1500)
    manager = Manager(store)
    Client.calls = []
    result = hourly.check_hourly(store=store, manager=manager, entry_id=3462711,
                                 client_factory=Client, clock=lambda: 1000)
    assert result["state"] == "VALIDATED_AFTER_RENEWAL_CHECK"
    assert result["credential_version"] == 3
    assert manager.calls == 1
    assert manager.windows == [900]
    assert Client.calls == ["me", "my_team"]
    assert "dummy-new-access" not in str(result)
    assert "dummy-replacement-refresh" not in str(result)


def test_hourly_wrong_team_fails_before_reading_secrets():
    store = Store()
    with pytest.raises(RotationBlocked, match="ENTRY_NOT_APPROVED"):
        hourly.check_hourly(store=store, manager=Manager(store), entry_id=123)
    assert store.reads == 0


def test_hourly_inflight_never_replays_refresh():
    store = Store(expiry=1, phase="IN_FLIGHT")
    manager = Manager(store)
    with pytest.raises(RotationBlocked, match="REENROLLMENT"):
        hourly.check_hourly(store=store, manager=manager, entry_id=3462711)
    assert manager.calls == 0


def test_hourly_failed_private_validation_does_not_retry():
    store = Store(expiry=1500)
    manager = Manager(store)

    class FailedClient(Client):
        def me(self):
            return {"status": "ERROR", "http_status": 401}

    with pytest.raises(RotationBlocked, match="PRIVATE_VALIDATION_FAILED"):
        hourly.check_hourly(store=store, manager=manager, entry_id=3462711,
                            client_factory=FailedClient, clock=lambda: 1000)
    assert manager.calls == 1


def test_main_ignores_non_natural_invocation_and_pause(monkeypatch, capsys):
    monkeypatch.setenv("FPL_HOURLY_SCHEDULER_KIND", "report_prefetch")
    assert hourly.main() == 0
    assert "SKIPPED_NOT_NATURAL" in capsys.readouterr().out
    monkeypatch.setenv("FPL_HOURLY_SCHEDULER_KIND", "chatgpt_scheduler")
    monkeypatch.setenv("FPL_PRIVATE_AUTO_REFRESH_PAUSED", "true")
    assert hourly.main() == 0
    assert "PAUSED" in capsys.readouterr().out


def test_hourly_workflow_is_protected_downstream_only():
    from pathlib import Path
    workflow = Path(".github/workflows/v6-natural-data-ingestion.yml").read_text()
    collector = workflow.split("  private_personal_publish:", 1)[0]
    maintenance = workflow.split("  private_hourly_oidc_maintenance:", 1)[1]
    assert "needs: collect" in maintenance
    assert "needs.collect.outputs.schedule_kind == 'chatgpt_scheduler'" in maintenance
    assert "github.event_name == 'issues'" in maintenance
    assert "github.actor == github.repository_owner" in maintenance
    assert "environment: v12-private-reports-publisher" in maintenance
    assert "continue-on-error: true" in maintenance
    assert "vars.FPL_PRIVATE_AUTO_REFRESH_PAUSED" in maintenance
    assert "src.runtime_v6.domains.report_plane.oidc_hourly_renewal" in maintenance
    assert "schedule:\\n" not in maintenance
    assert "workflow_dispatch:" not in maintenance
    assert "issue_comment:" not in maintenance
    assert "FPL_OIDC_STORE_KEY" not in collector
