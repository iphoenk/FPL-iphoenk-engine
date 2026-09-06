from __future__ import annotations

import json
from datetime import datetime, timezone

from src.runtime_v6.personal_prefetch import normalise_team
from src.runtime_v6.report_prefetch import PrefetchService, _auth_observability


def _manifest(**overrides):
    manifest = {
        "generated_at": "2026-09-06T21:30:00+00:00",
        "complete": False,
        "fresh_for_target_report": False,
        "source_failures": [{"endpoint_class": "me", "status": "FAILED"}],
        "personal_requested": True,
        "personal_status": "DEGRADED",
        "mini_league_status": "NOT_REQUESTED",
        "live_status": "NOT_REQUESTED",
        "expected_manager_count": None,
        "collected_manager_count": None,
        "telemetry": {"request_count": 1, "failed_requests": 1},
        "idempotency": {"reused": False},
    }
    manifest.update(overrides)
    return manifest


def test_auth_observability_actions_are_stable_and_fail_closed():
    assert _auth_observability("AUTH_AVAILABLE", personal_requested=True) == (
        "AUTH_AVAILABLE", False, "NONE"
    )
    assert _auth_observability("AUTH_EXPIRED", personal_requested=True) == (
        "AUTH_EXPIRED", True, "RENEW_CREDENTIALS"
    )
    assert _auth_observability("AUTH_INVALID", personal_requested=True) == (
        "AUTH_INVALID", True, "REVIEW_AUTH_CONFIGURATION"
    )
    assert _auth_observability("AUTH_ENTRY_MISMATCH", personal_requested=True) == (
        "AUTH_ENTRY_MISMATCH", True, "VERIFY_ENTRY_CONFIGURATION"
    )
    assert _auth_observability("AUTH_UNAVAILABLE", personal_requested=True) == (
        "AUTH_UNAVAILABLE", True, "CONFIGURE_CREDENTIALS"
    )
    assert _auth_observability("unexpected", personal_requested=True) == (
        "UNEXPECTED", True, "REVIEW_AUTH_STATE"
    )
    assert _auth_observability("AUTH_EXPIRED", personal_requested=False) == (
        "NOT_REQUESTED", False, "NONE"
    )


def test_http_401_normalises_to_expired_and_health_requests_credential_renewal(tmp_path):
    team = normalise_team(
        entry_id=3462711,
        gw=3,
        element_index={},
        bootstrap_lineage=None,
        submitted={"picks": [], "lineage": None},
        auth_state="DEGRADED",
        my_team_payload=None,
        auth_lineage=[{"http_status": 401}],
        generated_at="2026-09-06T21:30:00+00:00",
    )
    assert team["auth_state"] == "AUTH_EXPIRED"

    service = PrefetchService(
        config={}, output_root=tmp_path, now=datetime(2026, 9, 6, 21, 30, tzinfo=timezone.utc)
    )
    service._publish_health(_manifest(auth_state=team["auth_state"]))
    health = json.loads((tmp_path / "health/report_prefetch.json").read_text(encoding="utf-8"))

    assert health["auth_state"] == "AUTH_EXPIRED"
    assert health["auth_action_required"] is True
    assert health["auth_action"] == "RENEW_CREDENTIALS"
    assert health["prefetch_status"] == "AMBER"


def test_health_backfills_auth_state_from_current_team_for_legacy_reused_manifest(tmp_path):
    personal = tmp_path / "personal"
    personal.mkdir(parents=True)
    (personal / "current_team.json").write_text(
        json.dumps({"auth_state": "AUTH_EXPIRED"}), encoding="utf-8"
    )

    service = PrefetchService(
        config={}, output_root=tmp_path, now=datetime(2026, 9, 6, 21, 30, tzinfo=timezone.utc)
    )
    service._publish_health(_manifest())
    health = json.loads((tmp_path / "health/report_prefetch.json").read_text(encoding="utf-8"))

    assert health["auth_state"] == "AUTH_EXPIRED"
    assert health["auth_action_required"] is True
    assert health["auth_action"] == "RENEW_CREDENTIALS"


def test_auth_health_contains_only_non_secret_operational_enums(tmp_path):
    service = PrefetchService(
        config={}, output_root=tmp_path, now=datetime(2026, 9, 6, 21, 30, tzinfo=timezone.utc)
    )
    service._publish_health(_manifest(auth_state="AUTH_EXPIRED"))
    raw = (tmp_path / "health/report_prefetch.json").read_text(encoding="utf-8")

    assert "AUTH_EXPIRED" in raw
    assert "RENEW_CREDENTIALS" in raw
    for forbidden in ("sessionid", "authorization", "csrf", "bearer "):
        assert forbidden not in raw.lower()
