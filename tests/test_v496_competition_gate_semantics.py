from __future__ import annotations

import pytest

from src.engines.v4_quality_gate import _assert_competition_evidence


def _player(*, factor: float, competition: float, depth: float) -> dict:
    return {
        "priors": {
            "competition_factor": factor,
            "competition_pressure": competition,
            "squad_depth_pressure": depth,
        }
    }


def test_all_players_may_be_adjusted_when_all_have_governed_pressure() -> None:
    players = [
        _player(factor=0.98, competition=0.20, depth=0.10),
        _player(factor=0.96, competition=0.35, depth=0.10),
    ]
    _assert_competition_evidence(
        players,
        {
            "role_competition_adjustments": 2,
            "role_competition_factor_variants": 2,
        },
    )


def test_zero_adjustments_are_valid_only_without_competition_pressure() -> None:
    players = [
        _player(factor=1.0, competition=0.0, depth=0.0),
        _player(factor=1.0, competition=0.0, depth=0.0),
    ]
    _assert_competition_evidence(
        players,
        {
            "role_competition_adjustments": 0,
            "role_competition_factor_variants": 1,
        },
    )

    with pytest.raises(AssertionError):
        _assert_competition_evidence(
            [_player(factor=1.0, competition=0.25, depth=0.0)],
            {
                "role_competition_adjustments": 0,
                "role_competition_factor_variants": 1,
            },
        )
