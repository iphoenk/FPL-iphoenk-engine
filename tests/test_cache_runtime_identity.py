from __future__ import annotations

from copy import deepcopy

from src.engines import v12_lineup_optimizer as lineup
from src.engines import v12_monte_carlo as mc
from src.engines import v12_stage2_derived_cache as stage2


IDENTITY_A = {
    "python_major_minor": "3.12",
    "numpy_version": "2.4.4",
    "openblas_coretype": "Haswell",
    "numpy_simd_active": (
        "X86_V2",
        "X86_V3",
    ),
    "openblas_num_threads": 1,
}


def _changed(**updates):
    identity = deepcopy(IDENTITY_A)
    for key, value in updates.items():
        identity[key] = value
    return identity


IDENTITY_PYTHON_CHANGED = _changed(python_major_minor="3.13")
IDENTITY_NUMPY_CHANGED = _changed(numpy_version="2.5.0")
IDENTITY_SIMD_CHANGED = _changed(
    numpy_simd_active=("X86_V2",),
)
IDENTITY_OPENBLAS_CORE_CHANGED = _changed(
    openblas_coretype="SkylakeX",
)
IDENTITY_THREAD_CHANGED = _changed(openblas_num_threads=2)


def _stage2_key(monkeypatch, identity):
    monkeypatch.setattr(
        stage2,
        "_runtime_cache_identity",
        lambda: deepcopy(identity),
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
        lambda: deepcopy(identity),
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
        lambda: deepcopy(identity),
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
    variants = (
        IDENTITY_PYTHON_CHANGED,
        IDENTITY_NUMPY_CHANGED,
        IDENTITY_SIMD_CHANGED,
        IDENTITY_OPENBLAS_CORE_CHANGED,
        IDENTITY_THREAD_CHANGED,
    )

    assert key_a == key_a_repeat
    changed_keys = [key_builder(monkeypatch, value) for value in variants]
    assert all(key != key_a for key in changed_keys)
    assert len(set(changed_keys)) == len(changed_keys)


def test_stage2_cache_key_binds_normalized_numeric_runtime_class(monkeypatch):
    _assert_runtime_identity_changes_key(monkeypatch, _stage2_key)


def test_p17_cache_key_binds_normalized_numeric_runtime_class(monkeypatch):
    _assert_runtime_identity_changes_key(monkeypatch, _p17_key)


def test_mc_cache_key_binds_normalized_numeric_runtime_class(monkeypatch):
    _assert_runtime_identity_changes_key(monkeypatch, _mc_key)


def test_runtime_key_excludes_physical_cpu_and_host_core_count():
    assert set(IDENTITY_A) == {
        "python_major_minor",
        "numpy_version",
        "openblas_coretype",
        "numpy_simd_active",
        "openblas_num_threads",
    }
    assert "cpu_model" not in IDENTITY_A
    assert "cpu_count" not in IDENTITY_A
    assert "platform_machine" not in IDENTITY_A


def test_cache_schema_bump_rejects_pre_lineage_runtime_generation():
    assert stage2.STAGE2_DERIVED_CACHE_SCHEMA == 3
    assert lineup.P17_DECISION_CACHE_SCHEMA == 3
    assert mc.MC_SIM_CACHE_SCHEMA == 3
