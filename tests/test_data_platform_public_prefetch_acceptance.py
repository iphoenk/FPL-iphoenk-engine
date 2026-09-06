from __future__ import annotations

import json
from datetime import datetime, timezone

from src.runtime_v6.report_prefetch import PrefetchService


def test_report_prefetch_health_can_be_public_green_while_auth_remains_truthfully_degraded(tmp_path):
    service = PrefetchService(
        config={},
        output_root=tmp_path,
        now=datetime(2026, 9, 6, 22, 0, tzinfo=timezone.utc),
    )
    manifest = {
        "generated_at": "2026-09-06T22:00:00+00:00",
        "complete": False,
        "strict_complete": False,
        "public_core_complete": True,
        "fresh_for_target_report": True,
        "source_failures": [{"domain": "official_fpl_personal", "endpoint_class": "me", "status": "FAILED"}],
        "control_failures": [],
        "public_control_failures": [],
        "personal_requested": True,
        "personal_status": "DEGRADED",
        "public_personal_status": "AVAILABLE",
        "auth_state": "AUTH_EXPIRED",
        "auth_action_required": True,
        "auth_action": "RENEW_CREDENTIALS",
        "authenticated_personal_required_for_public_green": False,
        "authenticated_personal_deferred": True,
        "mini_league_status": "AVAILABLE",
        "live_status": "NOT_REQUESTED",
        "expected_manager_count": 20,
        "collected_manager_count": 20,
        "telemetry": {"request_count": 4, "failed_requests": 1},
        "idempotency": {"reused": False},
    }

    service._publish_health(manifest)
    health = json.loads((tmp_path / "health/report_prefetch.json").read_text(encoding="utf-8"))

    assert health["strict_prefetch_status"] == "AMBER"
    assert health["prefetch_status"] == "AMBER"
    assert health["public_core_status"] == "GREEN"
    assert health["public_core_complete"] is True
    assert health["authenticated_personal_deferred"] is True
    assert health["auth_state"] == "AUTH_EXPIRED"
    assert health["auth_action_required"] is True
    assert health["auth_action"] == "RENEW_CREDENTIALS"
