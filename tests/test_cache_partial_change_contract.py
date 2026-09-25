from __future__ import annotations

from pathlib import Path

from src.engines import v12_stage2_derived_cache as stage2


def _stage2_key(monkeypatch, now_cost: int) -> str:
    monkeypatch.setattr(
        stage2,
        "_runtime_cache_identity",
        lambda: {
            "python_major_minor": "3.12",
            "numpy_version": "2.4.4",
            "openblas_coretype": "Haswell",
            "numpy_simd_active": ("AVX", "AVX2", "FMA3"),
            "openblas_num_threads": 1,
        },
    )
    monkeypatch.setattr(
        stage2,
        "_dependency_fingerprints",
        lambda: {"stage2": "same-code"},
    )
    return stage2.stage2_derived_input_fingerprint(
        bootstrap={
            "elements": [
                {
                    "id": 1,
                    "web_name": "PriceOnly",
                    "now_cost": int(now_cost),
                    "status": "a",
                }
            ],
            "teams": [],
            "events": [],
        },
        strength={"teams": {}},
        planning_gw=6,
        historical_prior={},
        player_features_payload={"players": {}},
        player_match_rows=[],
        opponent_history_rows=[],
        opponent_history_scope={"latest_completed_gw": 5},
    )


def test_price_only_now_cost_change_forces_stage2_key_miss(monkeypatch):
    assert _stage2_key(monkeypatch, 50) != _stage2_key(monkeypatch, 51)


def test_stage2_price_path_is_explicit_in_cache_and_projection_source():
    root = Path(__file__).resolve().parents[1]
    cache_source = (
        root / "src/engines/v12_stage2_derived_cache.py"
    ).read_text(encoding="utf-8")
    projection_source = (
        root / "src/models/historical_projection.py"
    ).read_text(encoding="utf-8")
    runner_source = (
        root / "src/engines/v12_integrated_report_runner.py"
    ).read_text(encoding="utf-8")

    assert '"bootstrap": bootstrap' in cache_source
    assert '"now_cost": int(player.get("now_cost") or 0)' in projection_source
    assert "bootstrap=bootstrap" in runner_source
    assert "build_player_projections(" in runner_source
