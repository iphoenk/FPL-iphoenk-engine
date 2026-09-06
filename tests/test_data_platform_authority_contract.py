from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.runtime_v6.authority_contract import (
    AuthorityContractError,
    validate_artifact_descriptor,
    validate_schedule_policy,
)
from src.runtime_v6.identity import IDENTITY_EXACT, IDENTITY_UNMAPPED, build_player_identity_map


ROOT = Path(__file__).resolve().parents[1]


def test_schedule_policy_zero_authority_schema_is_fail_closed() -> None:
    policy = json.loads((ROOT / "config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    validate_schedule_policy(policy)


def test_forbidden_v6_analytical_artifact_is_rejected() -> None:
    with pytest.raises(AuthorityContractError):
        validate_artifact_descriptor(
            {
                "canonical": True,
                "semantic_class": "MINI_LEAGUE_ANALYTICS",
                "authority": "V6",
            }
        )


def test_noncanonical_retired_artifact_has_no_authority() -> None:
    validate_artifact_descriptor(
        {
            "canonical": False,
            "semantic_class": "MINI_LEAGUE_ANALYTICS",
            "authority": "NONE",
        }
    )


def test_source_native_model_signal_is_legal_only_when_v6_does_not_author_it() -> None:
    validate_artifact_descriptor(
        {
            "canonical": True,
            "semantic_class": "UPSTREAM_MODEL_SIGNAL",
            "authority": "SOURCE_NATIVE",
            "model_author": "OFFICIAL_FPL_PRICE_PREDICTOR",
            "v6_computation": "NONE",
        }
    )
    with pytest.raises(AuthorityContractError):
        validate_artifact_descriptor(
            {
                "canonical": True,
                "semantic_class": "UPSTREAM_MODEL_SIGNAL",
                "authority": "V6",
                "model_author": "V6",
                "v6_computation": "AUTHORED",
            }
        )


def test_identity_bridge_exposes_player_team_fixture_without_fuzzy_join() -> None:
    official = {
        "official": {
            "bootstrap": {
                "elements": [{"id": 10, "code": 1010, "web_name": "Example", "team": 1}],
                "teams": [{"id": 1, "name": "Example FC", "short_name": "EXA"}],
            },
            "fixtures": [
                {
                    "id": 99,
                    "event": 3,
                    "kickoff_time": "2026-09-12T14:00:00Z",
                    "team_h": 1,
                    "team_a": 2,
                }
            ],
        }
    }
    predictor = {"data": {"players": [{"id": 10, "team": 1}]}}

    bridge = build_player_identity_map(
        official,
        {"official_price_predictor": predictor},
        ["official_fpl", "official_price_predictor", "understat"],
    )

    assert bridge["bridge_scope"] == ["PLAYER", "TEAM", "FIXTURE"]
    player = bridge["mappings"]["10"]
    assert player["verification_status"] == IDENTITY_EXACT
    assert player["source_native_player_id"] == 10
    assert player["unresolved"]["understat"] == IDENTITY_UNMAPPED

    team_bridge = bridge["entity_bridges"]["team"]
    assert team_bridge["mappings"]["1"]["verification_status"] == IDENTITY_EXACT
    assert team_bridge["coverage"]["official_price_predictor"]["join_allowed"] is True
    assert team_bridge["coverage"]["understat"]["mapped_status"] == IDENTITY_UNMAPPED

    fixture_bridge = bridge["entity_bridges"]["fixture"]
    assert fixture_bridge["mappings"]["99"]["verification_status"] == IDENTITY_EXACT
    assert fixture_bridge["coverage"]["understat"]["mapped_status"] == IDENTITY_UNMAPPED
    assert bridge["governance"]["silent_fuzzy_runtime_join_allowed"] is False
