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


def _job(name, conclusion, failed_step=None):
    steps = []
    if failed_step:
        steps.append({"name": failed_step, "conclusion": "failure"})
    return {"name": name, "conclusion": conclusion, "steps": steps}


def test_auth_refresh_failure_allows_public_report_continuation_but_not_private_fallback():
    from src.runtime_v6.domains.report_plane.report_prefetch import (
        personal_refresh_fallback_eligible,
        public_report_continuation_eligible,
    )

    jobs = [
        _job("collect", "success"),
        _job("publish", "success"),
        _job(
            "private_personal_publish",
            "failure",
            "Refresh authenticated current-team state in isolated private plane",
        ),
        _job("orchestration-fulfillment", "success"),
        _job("route-visible-report", "skipped"),
    ]

    assert personal_refresh_fallback_eligible(jobs) is False
    assert public_report_continuation_eligible(jobs) is True


def test_artifact_retry_failure_can_use_saved_private_snapshot_only():
    from src.runtime_v6.domains.report_plane.report_prefetch import (
        personal_refresh_fallback_eligible,
    )

    jobs = [
        _job("collect", "success"),
        _job("publish", "success"),
        _job(
            "private_personal_publish",
            "failure",
            "Download verified public runtime snapshot",
        ),
        _job("orchestration-fulfillment", "success"),
        _job("route-visible-report", "skipped"),
    ]

    assert personal_refresh_fallback_eligible(jobs) is True


def test_personal_fallback_rejects_publication_or_unrelated_job_failure():
    from src.runtime_v6.domains.report_plane.report_prefetch import (
        personal_refresh_fallback_eligible,
    )

    auth_failure = _job(
        "private_personal_publish",
        "failure",
        "Refresh authenticated current-team state in isolated private plane",
    )
    assert personal_refresh_fallback_eligible(
        [_job("collect", "success"), _job("publish", "failure"), auth_failure]
    ) is False
    assert personal_refresh_fallback_eligible(
        [
            _job("collect", "success"),
            _job("publish", "success"),
            auth_failure,
            _job("v12-integrated-report-runner", "failure"),
        ]
    ) is False


def test_personal_fallback_rejects_unrecognized_private_publisher_failure():
    from src.runtime_v6.domains.report_plane.report_prefetch import (
        personal_refresh_fallback_eligible,
    )

    jobs = [
        _job("collect", "success"),
        _job("publish", "success"),
        _job("private_personal_publish", "failure", "Persist private personal snapshot"),
    ]

    assert personal_refresh_fallback_eligible(jobs) is False
