from __future__ import annotations

import json
from pathlib import Path

from src.runtime_v6.identity import (
    CANONICAL_JOINABLE_STATUSES,
    IDENTITY_EXACT,
    IDENTITY_VERIFIED_MANUAL,
)
from src.runtime_v6.league_prefetch import (
    add_manager_live_totals,
    standings_artifact,
)


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


def test_v6_standings_artifact_preserves_official_facts_without_derived_gap() -> None:
    artifact = standings_artifact(
        league={
            "league_id": 9477,
            "league_name": "ICON+ League",
            "league_kind": "classic",
        },
        state={
            "rows": [
                {
                    "entry_id": 1,
                    "manager_name": "Leader",
                    "team_name": "Leader XI",
                    "league_rank": 1,
                    "league_total": 200,
                    "gw_score": 60,
                    "last_rank": 1,
                },
                {
                    "entry_id": 2,
                    "manager_name": "User",
                    "team_name": "User XI",
                    "league_rank": 2,
                    "league_total": 190,
                    "gw_score": 55,
                    "last_rank": 2,
                },
            ],
            "complete": True,
            "pages_collected": 1,
            "failed_pages": [],
            "lineage": [{"authority": "OFFICIAL_FPL"}],
        },
        entry_id=2,
        generated_at="2026-09-06T15:00:00+00:00",
    )

    assert artifact["user_summary"] == {"entry_id": 2, "rank": 2, "total": 190}
    assert "gap_to_first" not in json.dumps(artifact)
    assert artifact["managers"][0]["league_total"] == 200
    assert artifact["authority"] == "OFFICIAL_FPL"


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
