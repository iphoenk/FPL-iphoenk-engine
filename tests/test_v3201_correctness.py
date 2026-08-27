import json
import math
from pathlib import Path

import pytest

from src.engines import lineup_governance
from src.models import package_optimizer_v2, projection_components
from src.runtime_v3.orchestrator import _attempt_promotion, _clear_failed_service_outputs

ROOT = Path(__file__).resolve().parents[1]


def _projection_cfg() -> dict:
    return {
        "appearance_60_probability_transition": {
            "start_minutes_low": 55.0,
            "start_minutes_high": 70.0,
        },
        "attack_multiplier_min": 0.55,
        "attack_multiplier_max": 1.75,
        "uncertainty": {
            "minimum_points_std": 0.0,
            "coefficient_of_variation": 0.0,
            "xmins_std_points_multiplier": 0.0,
            "small_sample_extra_std": 0.0,
        },
    }


def _neutral_matchup() -> dict:
    return {
        "event": 2,
        "team_h": 1,
        "team_a": 2,
        "home_expected_goals": 1.3,
        "away_expected_goals": 1.3,
        "home_clean_sheet_probability": 0.0,
        "away_clean_sheet_probability": 0.0,
    }


def _zero_rates(**overrides) -> dict:
    rates = {"xg90": 0.0, "xa90": 0.0, "bonus90": 0.0, "saves90": 0.0, "dc90": 0.0}
    rates.update(overrides)
    return rates


def test_project_fixture_appearance_uses_unconditional_p60_once(monkeypatch):
    monkeypatch.setattr(projection_components, "load_projection_config", _projection_cfg)
    monkeypatch.setattr(
        projection_components,
        "read_json",
        lambda *_args, **_kwargs: {"baseline": {"home_goals": 1.3, "away_goals": 1.3}},
    )
    xmins = {
        "start_probability": 0.5,
        "bench_probability": 0.2,
        "expected_minutes": 45.0,
        "starter_minutes_if_start": 70.0,
        "minutes_std": 0.0,
    }
    row = projection_components._project_fixture(
        {"element_type": 4},
        xmins,
        _neutral_matchup(),
        True,
        _zero_rates(),
        False,
    )
    # p60 = 0.5 * 1.0 = 0.5, already unconditional.
    # Expected appearance = p_start + p_bench + p60 = 1.2.
    assert row["components"]["appearance"] == pytest.approx(1.2)
    assert row["mean"] == pytest.approx(1.2)


def test_project_fixture_derives_goalkeeper_position_from_element_type(monkeypatch):
    monkeypatch.setattr(projection_components, "load_projection_config", _projection_cfg)
    monkeypatch.setattr(
        projection_components,
        "read_json",
        lambda *_args, **_kwargs: {"baseline": {"home_goals": 1.3, "away_goals": 1.3}},
    )
    xmins = {
        "start_probability": 1.0,
        "bench_probability": 0.0,
        "expected_minutes": 90.0,
        "starter_minutes_if_start": 90.0,
        "minutes_std": 0.0,
    }
    row = projection_components._project_fixture(
        {"element_type": 1},
        xmins,
        _neutral_matchup(),
        True,
        _zero_rates(saves90=6.0),
        False,
    )
    assert row["components"]["saves"] == pytest.approx(2.0)


def _optimizer_player(element: int, position: str, mean: float, std: float, team_id: int) -> dict:
    return {
        "element": element,
        "position": position,
        "team_id": team_id,
        "xpts_by_gw": [{"gw": 2, "mean": mean, "std": std}],
    }


def test_package_captain_variance_includes_covariance_and_same_captain_row(monkeypatch):
    cfg = {
        "horizons": [1],
        "horizon_weights": {"1": 1.0},
        "max_changes": 0,
        "early_season_change_cap": {"enabled": False, "through_gw": 0, "max_changes": 0},
        "team_cluster_penalty": {"enabled": False, "free_players_per_club": 3, "points_per_extra_player": 0.0},
        "bench_utility_weight": 0.0,
        "captain_bonus_weight": 1.0,
        "risk_aversion": 0.0,
        "change_penalty_points": 0.0,
    }
    monkeypatch.setattr(package_optimizer_v2, "load_config", lambda: cfg)

    players = [
        _optimizer_player(1, "GK", 5.0, 1.0, 1),
        _optimizer_player(2, "GK", 0.0, 1.0, 2),
        _optimizer_player(3, "DEF", 5.0, 1.0, 3),
        _optimizer_player(4, "DEF", 5.0, 1.0, 4),
        _optimizer_player(5, "DEF", 5.0, 1.0, 5),
        _optimizer_player(6, "DEF", 5.0, 1.0, 6),
        _optimizer_player(7, "DEF", 0.0, 1.0, 7),
        _optimizer_player(8, "MID", 5.0, 1.0, 8),
        _optimizer_player(9, "MID", 5.0, 1.0, 9),
        _optimizer_player(10, "MID", 5.0, 1.0, 10),
        _optimizer_player(11, "MID", 5.0, 1.0, 11),
        _optimizer_player(12, "MID", 0.0, 1.0, 12),
        _optimizer_player(13, "FWD", 10.0, 3.0, 13),
        _optimizer_player(14, "FWD", 5.0, 1.0, 14),
        _optimizer_player(15, "FWD", 0.0, 1.0, 15),
    ]
    score = package_optimizer_v2.score_package(players, planning_gw=2)
    assert score["valid"] is True
    # 11 starters: captain variance 9 + ten others variance 1 = 19.
    # Doubling captain means total captain contribution is 2X, so the extra
    # variance beyond the already-counted X is (4 - 1) * 9 = 27. Total = 46.
    assert score["horizons"]["1"]["std"] == pytest.approx(math.sqrt(46.0), abs=1e-3)


def test_lineup_battle_threshold_is_config_owned(monkeypatch):
    pmap = {
        1: {"element": 1, "name": "A", "position": "MID", "selection_score": 1.0},
        2: {"element": 2, "name": "B", "position": "MID", "selection_score": 0.7},
    }
    best = {"score": 1.0, "element_ids": [1], "formation": "3-4-3"}
    second = {"score": 0.7, "element_ids": [2], "formation": "3-5-2"}
    monkeypatch.setattr(lineup_governance, "load_policy", lambda: {"battle": {"close_margin_threshold": 0.2}})
    assert lineup_governance._battle(best, second, pmap)["status"] == "CLEAR"
    monkeypatch.setattr(lineup_governance, "load_policy", lambda: {"battle": {"close_margin_threshold": 0.5}})
    assert lineup_governance._battle(best, second, pmap)["status"] == "CLOSE"


def test_promotion_failure_becomes_service_failure_and_discards_stale_outputs(tmp_path):
    canonical = tmp_path / "canonical"
    service_dir = tmp_path / "service"
    canonical.mkdir()
    service_dir.mkdir()
    (canonical / "optional.json").write_text("{}")
    (canonical / "latest.json").write_text(json.dumps({
        "optional_summary": {"stale": True},
        "files": {"optional": "data/optional.json"},
    }))
    spec = {
        "critical": False,
        "isolated": True,
        "inputs": [],
        "artifacts": ["optional.json"],
        "latest_keys": ["optional_summary"],
        "latest_file_keys": ["optional"],
    }
    success_without_artifact = {
        "service": "optional",
        "status": "SUCCESS",
        "isolated": True,
        "data_dir": str(service_dir),
        "elapsed_ms": 1.0,
        "commands": [],
    }
    failed = _attempt_promotion("optional", success_without_artifact, spec, canonical)
    assert failed["status"] == "FAILED"
    assert failed["failure_stage"] == "promotion"
    removed = _clear_failed_service_outputs(canonical, spec)
    assert removed == ["optional.json"]
    latest = json.loads((canonical / "latest.json").read_text())
    assert "optional_summary" not in latest
    assert "optional" not in latest.get("files", {})


def test_challenger_source_outage_and_scorecard_integrity_are_distinct_contracts():
    registry = json.loads((ROOT / "config" / "v3_service_registry.json").read_text())
    assert registry["policy"]["challenger_source_failure_does_not_block_decisions"] is True
    # Source outages are normalized/fail-soft before this deterministic artifact.
    # A crash of the internal scorecard itself remains an engine-integrity failure.
    assert registry["services"]["challenger"]["critical"] is True


def test_legacy_direct_fetch_projection_path_is_removed():
    decision_source = (ROOT / "src" / "engines" / "decision_intelligence.py").read_text()
    historical_source = (ROOT / "src" / "models" / "historical_projection.py").read_text()
    assert "from src.sources.official_fpl import get_json" not in decision_source
    assert "def build_player_projections(" not in decision_source
    assert "def run()" not in decision_source
    assert "src.models.projection_components" in historical_source
