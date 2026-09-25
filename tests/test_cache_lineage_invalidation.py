from __future__ import annotations

from src.engines import v12_lineup_optimizer as lineup
from src.engines import v12_monte_carlo as mc
from src.engines import v12_stage2_derived_cache as stage2


RUNTIME = {
    "python_major_minor": "3.12",
    "numpy_version": "2.4.4",
    "platform_machine": "x86_64",
    "cpu_model": "TEST_CPU",
    "cpu_count": 4,
    "numpy_simd_active": ("AVX2",),
    "blas": {
        "name": "openblas",
        "version": "0.3.test",
        "openblas_configuration": "TEST",
        "openblas_coretype": "",
        "openblas_num_threads": "4",
        "omp_num_threads": "",
    },
}


def _stage2_kwargs(builder):
    return {
        "bootstrap": {"elements": [{"id": 1, "now_cost": 50}]},
        "strength": {"teams": {}},
        "planning_gw": 6,
        "historical_prior": {"1": {"start_probability": 0.8}},
        "player_features_payload": {"players": {"1": {}}},
        "player_match_rows": [
            {"player_id": 1, "gw": 5, "minutes": 90, "xgi": 0.2}
        ],
        "opponent_history_rows": [],
        "opponent_history_scope": {"latest_completed_gw": 5},
        "builder": builder,
    }


def _p17_players():
    return [
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


def _mc_key():
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
        horizons=(1, 3, 5),
        selected_route_id="HOLD",
        canonical=True,
    )


def test_stage2_foundation_code_change_forces_persistent_cache_miss(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(stage2.STAGE2_DERIVED_CACHE_ENV, str(tmp_path))
    monkeypatch.setattr(stage2, "_runtime_cache_identity", lambda: dict(RUNTIME))
    dependency_state = {
        "src/models/v12_analytics_foundation.py": "foundation-A",
        "src/models/historical_projection.py": "stage2-A",
    }
    monkeypatch.setattr(
        stage2,
        "_dependency_fingerprints",
        lambda: dict(dependency_state),
    )
    builds = {"count": 0}

    def builder():
        builds["count"] += 1
        return {"players": [{"element": 1, "sentinel": builds["count"]}]}

    first, first_proof = stage2.load_or_build_stage2_projections(
        **_stage2_kwargs(builder)
    )
    second, second_proof = stage2.load_or_build_stage2_projections(
        **_stage2_kwargs(builder)
    )
    dependency_state["src/models/v12_analytics_foundation.py"] = (
        "foundation-B"
    )
    third, third_proof = stage2.load_or_build_stage2_projections(
        **_stage2_kwargs(builder)
    )

    assert first_proof["status"] == "MISS"
    assert second_proof["status"] == "HIT"
    assert third_proof["status"] == "MISS"
    assert first == second
    assert third != second
    assert builds["count"] == 2


def test_p17_stage2_code_change_forces_persistent_cache_miss(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(lineup.P17_DECISION_CACHE_ENV, str(tmp_path))
    monkeypatch.setattr(lineup, "_runtime_cache_identity", lambda: dict(RUNTIME))
    upstream = {"value": "stage2-A"}
    monkeypatch.setattr(
        lineup,
        "_upstream_stage2_code_fingerprint",
        lambda: upstream["value"],
    )
    calls = {"count": 0}

    def decision_core(_players):
        calls["count"] += 1
        return {
            "legal_xi_count": 1,
            "sentinel": calls["count"],
        }

    monkeypatch.setattr(lineup, "_decision_core", decision_core)
    lineup.reset_p17_execution_observability()
    first = lineup._decision_core_cached(_p17_players())
    second = lineup._decision_core_cached(_p17_players())
    upstream["value"] = "stage2-B"
    third = lineup._decision_core_cached(_p17_players())

    assert first == second
    assert third != second
    assert calls["count"] == 2
    stats = lineup.p17_execution_observability()
    assert stats["p17_cache_hits"] == 1
    assert stats["p17_cache_misses"] == 2


def test_mc_p17_code_change_forces_summary_cache_miss(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(mc.MC_SIM_CACHE_ENV, str(tmp_path))
    monkeypatch.setattr(mc, "_runtime_cache_identity", lambda: dict(RUNTIME))
    upstream = {"value": "p17-A"}
    monkeypatch.setattr(
        mc,
        "_upstream_p17_code_fingerprint",
        lambda: upstream["value"],
    )

    key_a = _mc_key()
    mc._save_mc_summary_cache(key_a, {"sentinel": "A"})
    assert mc._load_mc_summary_cache(key_a) == {"sentinel": "A"}

    upstream["value"] = "p17-B"
    key_b = _mc_key()
    assert key_b != key_a
    assert mc._load_mc_summary_cache(key_b) is None
