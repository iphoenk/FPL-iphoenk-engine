from __future__ import annotations

import json
from pathlib import Path

from src.models.package_optimizer_v2 import legal_squad, score_package
from src.models.team_strength import build_team_strength
from src.models.xmins_v2 import estimate_xmins

ROOT = Path(__file__).resolve().parents[1]


def test_p02_xmins_distribution_is_normalized_and_uncertain():
    player = {"status": "a", "starts": 1, "minutes": 90, "chance_of_playing_next_round": 100}
    out = estimate_xmins(player, {"team_matches_played": 1})
    total = out["start_probability"] + out["bench_probability"] + out["dnp_probability"]
    assert abs(total - 1.0) < 0.002
    assert 0 <= out["expected_minutes"] <= 90
    assert out["small_sample_guard"] is True
    assert len(out["expected_minutes_interval"]) == 2


def test_p02_unavailable_player_fails_closed_to_zero_minutes():
    player = {"status": "u", "starts": 1, "minutes": 90}
    out = estimate_xmins(player, {"team_matches_played": 1})
    assert out["start_probability"] == 0
    assert out["bench_probability"] == 0
    assert out["dnp_probability"] == 1
    assert out["expected_minutes"] == 0


def test_p03_team_strength_generates_probabilities():
    bootstrap = {
        "teams": [
            {"id": 1, "name": "A", "strength_attack_home": 1200, "strength_attack_away": 1150, "strength_defence_home": 1200, "strength_defence_away": 1150},
            {"id": 2, "name": "B", "strength_attack_home": 900, "strength_attack_away": 950, "strength_defence_home": 900, "strength_defence_away": 950},
        ]
    }
    fixtures = [
        {"team_h": 1, "team_a": 2, "team_h_score": 2, "team_a_score": 0, "finished": True, "kickoff_time": "2026-08-01T12:00:00Z", "event": 1},
        {"team_h": 1, "team_a": 2, "finished": False, "kickoff_time": "2026-08-08T12:00:00Z", "event": 2},
    ]
    out = build_team_strength(bootstrap, fixtures)
    assert len(out["teams"]) == 2
    assert len(out["matchups"]) == 1
    m = out["matchups"][0]
    assert 0 < m["home_clean_sheet_probability"] < 1
    assert 0 < m["away_clean_sheet_probability"] < 1
    assert abs(m["home_win_probability"] + m["draw_probability"] + m["away_win_probability"] - 1) < 0.02


def _synthetic_squad():
    rows = []
    element = 1
    for position, count in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for i in range(count):
            rows.append({
                "element": element,
                "name": f"P{element}",
                "position": position,
                "team_id": (element % 10) + 1,
                "now_cost": 50,
                "sell_cost": 50,
                "status": "a",
                "xpts_by_gw": [{"gw": gw, "mean": 4 + i * 0.1, "std": 1.5} for gw in range(2, 17)],
            })
            element += 1
    return rows


def test_p04_multi_horizon_package_scoring_is_legal():
    squad = _synthetic_squad()
    assert legal_squad(squad)
    out = score_package(squad, planning_gw=2)
    assert out["valid"] is True
    assert set(out["horizons"]) == {"3", "5", "10", "15"}
    assert out["objective_mean"] > 0
    assert out["objective_std"] > 0


def test_p05_challenger_registry_never_auto_scrapes_or_reputation_weights():
    registry = json.loads((ROOT / "config" / "intelligence" / "challenger_registry.json").read_text())
    ids = {p["id"] for p in registry["providers"]}
    assert ids == {"internal", "fffix", "ffhub"}
    assert "livefpl" not in ids
    assert "onefpl" not in ids
    assert registry["auto_scrape"] is False
    assert registry["governance"]["missing_provider_data_is_not_fabricated"] is True
    assert registry["governance"]["provider_reputation_is_not_accuracy_evidence"] is True
    assert registry["governance"]["report_time_only_providers_are_excluded_from_machine_scorecard"] is True


def test_p05_source_lifecycle_is_consistent_across_registries():
    source_registry = json.loads((ROOT / "config" / "sources" / "registry.json").read_text())
    report_registry = json.loads((ROOT / "config" / "sources" / "report_time_registry.json").read_text())
    challenger_registry = json.loads((ROOT / "config" / "intelligence" / "challenger_registry.json").read_text())
    collector_policy = json.loads((ROOT / "config" / "runtime" / "collector_policy.json").read_text())

    machine_ids = {row["id"] for row in source_registry["sources"]}
    report_ids = {row["id"] for row in report_registry["sources"]}
    challenger_ids = {row["id"] for row in challenger_registry["providers"]}
    sweep_ids = {
        source_id
        for tier in (collector_policy.get("deadline_source_sweep") or {}).get("tiers", {}).values()
        for source_id in tier
    }
    retired = set((source_registry.get("policy") or {}).get("retired_source_ids") or [])

    assert retired
    assert retired.isdisjoint(machine_ids)
    assert retired.isdisjoint(report_ids)
    assert retired.isdisjoint(challenger_ids)
    assert retired.isdisjoint(sweep_ids)

    onefpl = next(row for row in source_registry["sources"] if row["id"] == "onefpl")
    assert onefpl["enabled"] is False
    assert onefpl["adapter"] == "disabled"
    assert onefpl["delegated_to"] == report_registry["registry"]
    assert "onefpl" in report_ids
    assert "onefpl" not in challenger_ids

    official = next(row for row in source_registry["sources"] if row["id"] == "official_fpl")
    assert official["health_endpoints"] == ["bootstrap", "fixtures", "entry", "history", "transfers"]
    weather = next(row for row in source_registry["sources"] if row["id"] == "open_meteo")
    assert weather["artifact_paths"] == ["fixture_weather.json"]


def test_p01_prediction_evaluation_registry_freezes_predeadline():
    cfg = json.loads((ROOT / "config" / "intelligence" / "prediction_evaluation.json").read_text())
    assert cfg["freeze_policy"] == "last_pre_deadline_snapshot"
    assert cfg["minimum_sample_for_dynamic_weight"] >= 1
