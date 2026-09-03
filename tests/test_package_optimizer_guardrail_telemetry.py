from __future__ import annotations

import pytest

from src.runtime_v3.package_optimizer_shards import _canonical_guardrail_telemetry


def test_canonical_guardrail_telemetry_preserves_scorer_booleans_without_hardcoding():
    score = {
        "guardrails": {
            "team_cluster_penalty_enabled": False,
            "early_season_change_cap_enabled": True,
            "cluster_penalty_points": 0.0,
        }
    }

    telemetry = _canonical_guardrail_telemetry(score)

    assert telemetry == {
        "team_cluster_penalty_enabled": False,
        "early_season_change_cap_enabled": True,
    }


def test_canonical_guardrail_telemetry_fails_closed_when_scorer_evidence_is_missing():
    with pytest.raises(RuntimeError, match="canonical package scorer did not emit required guardrail telemetry"):
        _canonical_guardrail_telemetry({"guardrails": {"team_cluster_penalty_enabled": True}})


def test_canonical_guardrail_telemetry_rejects_non_boolean_claims():
    with pytest.raises(RuntimeError, match="canonical package scorer did not emit required guardrail telemetry"):
        _canonical_guardrail_telemetry({
            "guardrails": {
                "team_cluster_penalty_enabled": "true",
                "early_season_change_cap_enabled": True,
            }
        })
