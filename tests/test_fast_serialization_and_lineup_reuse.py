from __future__ import annotations

import json

from src.utils import atomic_json


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
