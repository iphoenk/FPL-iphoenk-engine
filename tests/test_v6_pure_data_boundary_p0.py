from __future__ import annotations

import json
from pathlib import Path

from src.runtime_v6.identity import (
    CANONICAL_JOINABLE_STATUSES,
    IDENTITY_EXACT,
    IDENTITY_VERIFIED_MANUAL,
)
from src.runtime_v6.league_prefetch import add_manager_live_totals, exposure_artifact


ROOT = Path(__file__).resolve().parents[1]


def test_v6_zero_downstream_authority_contract() -> None:
    policy = json.loads((ROOT / "config/v6/schedule_policy.json").read_text())
    authorities = policy["authorities"]

    assert authorities["data_acquisition"] == "V6"
    assert authorities["normalization"] == "V6"
    assert authorities["deterministic_identity"] == "V6"
    assert authorities["publication"] == "V6"

    forbidden = {
        "decision",
        "prediction_authored_by_v6",
        "optimizer",
        "tactical",
        "transfer",
        "captain",
        "vice_captain",
        "chip",
        "formation",
        "xpts",
        "xmins",
        "p_start",
        "bayesian",
        "monte_carlo",
        "mini_league_analytics",
        "rank_probability",
    }
    assert {name for name in forbidden if authorities.get(name) != "NONE"} == set()
    assert policy["governance"]["v6_is_fresh_data_only"] is True
    assert policy["governance"]["v6_may_publish_mini_league_analytics"] is False


def test_identity_join_policy_is_fail_closed() -> None:
    policy = json.loads((ROOT / "config/v6/schedule_policy.json").read_text())
    join_policy = policy["governance"]["identity_join_policy"]

    assert join_policy["silent_fuzzy_runtime_join_allowed"] is False
    assert set(join_policy["allowed_statuses_for_canonical_join"]) == {
        IDENTITY_EXACT,
        IDENTITY_VERIFIED_MANUAL,
    }
    assert CANONICAL_JOINABLE_STATUSES == {IDENTITY_EXACT, IDENTITY_VERIFIED_MANUAL}


def test_v6_exposure_artifact_is_noncanonical_tombstone_only() -> None:
    picks = {
        "season": "2026-2027",
        "gw": 3,
        "league_id": 9477,
        "expected_manager_count": 2,
        "submitted_picks_available_count": 2,
        "submitted_picks_missing_count": 0,
        "coverage_percent": 100.0,
        "complete": True,
        "entries": {
            "1": {
                "status": "AVAILABLE",
                "picks": [
                    {"element_id": 10, "squad_position": 1, "captain": True, "vice_captain": False, "multiplier": 2}
                ],
            },
            "2": {
                "status": "AVAILABLE",
                "picks": [
                    {"element_id": 10, "squad_position": 12, "captain": False, "vice_captain": True, "multiplier": 0}
                ],
            },
        },
        "lineage": {"authority": "OFFICIAL_FPL"},
    }

    artifact = exposure_artifact(
        picks,
        {10: {"web_name": "Example", "club": "AAA", "position": "MID"}},
        bootstrap_lineage={"authority": "OFFICIAL_FPL"},
        live_points={10: 12},
        live_lineage={"authority": "OFFICIAL_FPL"},
    )

    assert artifact["deprecated"] is True
    assert artifact["canonical"] is False
    assert artifact["analytics_removed"] is True
    assert artifact["authority"] == "NONE"
    assert artifact["players"] == []
    assert "ownership_percent" not in json.dumps(artifact)
    assert "effective_ownership" not in json.dumps(artifact)


def test_v6_live_artifact_does_not_add_manager_analytics() -> None:
    live = {"schema_version": 1, "elements": [{"element_id": 10, "total_points": 12}]}
    picks = {
        "entries": {
            "1": {
                "status": "AVAILABLE",
                "entry_id": 1,
                "picks": [{"element_id": 10, "multiplier": 2}],
            }
        }
    }

    result = add_manager_live_totals(live, picks, {10: 12})

    assert "manager_multiplier_points" not in result
    assert result["governance"]["manager_live_aggregation_authority"] == "NONE"
    assert result["governance"]["manager_live_aggregation"] == "DOWNSTREAM_ONLY"
