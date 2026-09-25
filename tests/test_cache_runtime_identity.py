from __future__ import annotations

from src.engines import v12_lineup_optimizer as lineup
from src.engines import v12_monte_carlo as mc
from src.engines import v12_stage2_derived_cache as stage2


IDENTITY_A = {
    "python_major_minor": "3.12",
    "numpy_version": "2.4.4",
}
IDENTITY_PYTHON_CHANGED = {
    "python_major_minor": "3.13",
    "numpy_version": "2.4.4",
}
IDENTITY_NUMPY_CHANGED = {
    "python_major_minor": "3.12",
    "numpy_version": "2.5.0",
}


def _stage2_key(monkeypatch, identity):
    monkeypatch.setattr(
        stage2,
        "_runtime_cache_identity",
        lambda: dict(identity),
    )
    return stage2.stage2_derived_input_fingerprint(
        bootstrap={"elements": [{"id": 1, "now_cost": 50}]},
        strength={"teams": {}},
        planning_gw=6,
        historical_prior={"1": {"start_probability": 0.8}},
        player_features_payload={"players": {"1": {}}},
        player_match_rows=[
            {"player_id": 1, "gw": 5, "minutes": 90, "xgi": 0.2}
        ],
        opponent_history_rows=[],
        opponent_history_scope={"latest_completed_gw": 5},
    )


def _p17_key(monkeypatch, identity):
    monkeypatch.setattr(
        lineup,
        "_runtime_cache_identity",
        lambda: dict(identity),
    )
    players = [
        {
            "element": 1,
            "position": "GK",
            "selection_score": 4.0,
            "states": {
                "START": 1.0,
                "REGULAR_CAMEO": 0.0,
                "LATE_CAMEO": 0.0,
                "DNP": 0.0,
            },
        }
    ]
    return lineup._decision_core_cache_key(players)


def _mc_key(monkeypatch, identity):
    monkeypatch.setattr(
        mc,
        "_runtime_cache_identity",
        lambda: dict(identity),
    )
    return mc._simulation_cache_key(
        projection_fp="projection-fingerprint",
        route_defs=[
            {
                "route_id": "HOLD",
                "per_gw": [],
                "execution_cost_points": 0,
                "execution_cost_status": "KNOWN",
                "decision_net_supported": True,
            }
        ],
        actual_paths=500_000,
        seed=123456,
        horizons=(6, 7, 8, 9, 10),
        selected_route_id="HOLD",
        canonical=True,
    )


def _assert_runtime_identity_changes_key(monkeypatch, key_builder):
    key_a = key_builder(monkeypatch, IDENTITY_A)
    key_a_repeat = key_builder(monkeypatch, IDENTITY_A)
    key_python = key_builder(
        monkeypatch,
        IDENTITY_PYTHON_CHANGED,
    )
    key_numpy = key_builder(
        monkeypatch,
        IDENTITY_NUMPY_CHANGED,
    )

    assert key_a == key_a_repeat
    assert key_a != key_python
    assert key_a != key_numpy
    assert key_python != key_numpy


def test_stage2_cache_key_binds_python_minor_and_numpy(monkeypatch):
    _assert_runtime_identity_changes_key(monkeypatch, _stage2_key)


def test_p17_cache_key_binds_python_minor_and_numpy(monkeypatch):
    _assert_runtime_identity_changes_key(monkeypatch, _p17_key)


def test_mc_cache_key_binds_python_minor_and_numpy(monkeypatch):
    _assert_runtime_identity_changes_key(monkeypatch, _mc_key)


def test_cache_schema_bump_rejects_pre_runtime_identity_cache_generation():
    assert stage2.STAGE2_DERIVED_CACHE_SCHEMA == 2
    assert lineup.P17_DECISION_CACHE_SCHEMA == 2
    assert mc.MC_SIM_CACHE_SCHEMA == 2
