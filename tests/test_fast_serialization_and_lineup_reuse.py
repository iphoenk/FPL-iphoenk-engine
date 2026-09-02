from __future__ import annotations

import json

from src.runtime_v3 import incremental_reuse
from src.utils import atomic_json


def test_lineup_governance_exact_reuse_covers_all_material_inputs():
    registry = incremental_reuse._registry()
    spec = registry["services"]["lineup_governance"]
    inputs = set(spec.get("inputs") or [])

    assert {
        "src/",
        "latest.json",
        "team.json",
        "chips.json",
        "projections.json",
        "package_optimizer.json",
        "config/locked_squad.json",
        "config/intelligence/lineup_governance.json",
    }.issubset(inputs)
    assert spec.get("allow_during_live") is not True
    assert spec.get("record_post_execution_fingerprint") is not True


def test_lineup_governance_reuse_is_disabled_during_live_fixture(tmp_path, monkeypatch):
    official = {
        "phase": {"scoring_gw": 3},
        "fixtures": [
            {
                "event": 3,
                "started": True,
                "finished": False,
                "kickoff_time": "2000-01-01T12:00:00Z",
            }
        ],
    }
    (tmp_path / "official_snapshot.json").write_text(json.dumps(official), encoding="utf-8")
    monkeypatch.setattr(incremental_reuse, "DATA", tmp_path)

    assert incremental_reuse.active("fast_decision", "lineup_governance") is False
    assert incremental_reuse.inactive_reason("fast_decision", "lineup_governance") == (
        "CURRENT_SCORING_FIXTURE_LIVE_SERVICE_NOT_OPTED_IN"
    )


def test_high_volume_fast_artifacts_are_compact_without_value_change(tmp_path):
    payload = {
        "schema_version": 1,
        "rows": [{"element": 1, "name": "Álpha", "score": 7.25}, {"element": 2, "score": None}],
        "nested": {"enabled": True, "values": [1, 2, 3]},
    }
    names = {
        "prices.json",
        "price_trajectory.json",
        "price_alerts.json",
        "price_challenger_context.json",
        "dss_watchlist.json",
        "recent_competitive_load.json",
        "dss_operational_evidence.json",
        "framework_health_preflight.json",
        "framework_health.json",
        "external_consensus.json",
        "user_report.json",
        "technical_appendix.json",
        "deep_review_payload.json",
    }

    for name in names:
        path = tmp_path / name
        atomic_json(path, payload)
        raw = path.read_text(encoding="utf-8")
        assert "\n" not in raw
        assert json.loads(raw) == payload
