from __future__ import annotations

from pathlib import Path

from src.v5.config_cache import load_json_config
from src.v5.reporting import build_report
from src.v5.sources.season import season_authority


def _player(element: int, position: str = "MID") -> dict:
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "captain_score": 5.0 - element / 1000.0,
        "start_probability": 0.9,
        "expected_minutes": 80.0,
        "dnp_probability": 0.05,
    }


def test_reporting_uses_native_owned_and_starters_contract():
    squad = [_player(i) for i in range(1, 16)]
    starters = [_player(i, "GK" if i == 1 else "MID") for i in range(1, 12)]
    lineup = {
        "formation": "3-5-2",
        "starters": starters,
        "bench": squad[11:],
        "captain": starters[0],
        "vice_captain": starters[1],
        "captain_safe_pool": starters[:2],
        "main_starting_xi_battle": {"status": "CLEAR", "margin": 1.0},
    }
    watchlist = {"status": "READY", "candidate_count": 20, "positions": {"GK": [{"name": "WGK"}]}}
    report = build_report({
        "truth": {"team": {"authority": "user_lock", "squad": squad, "owned_ids": list(range(1, 16))}},
        "decision": {"selected_package_id": "HOLD", "decision_trace": {"confidence": "HIGH"}, "lineup": lineup},
        "prediction": {},
        "price": {"alerts": {"alerts": []}},
        "governance": {"overall": "GREEN", "go_allowed": True},
        "watchlist": watchlist,
        "previous_report_state": {},
    })
    user = report["user_report"]
    assert user["owned_squad"]["count"] == 15
    assert user["report_mode"] == "FULL_DECISION"
    assert len(user["starting_xi"]["starting_xi"]) == 11
    assert user["external_watchlist"]["candidate_count"] == 20


def test_source_season_is_derived_from_rules_registry_not_source_config():
    cfg = load_json_config("config/intelligence/source_fusion.json")
    assert "season" not in cfg["understat"]
    assert "season" not in cfg["api_football"]
    authority = season_authority()
    rules = load_json_config(cfg["season_authority"]["registry_path"])
    assert authority["start_year"] == int(str(rules["season"]).split("/", 1)[0])
    assert authority["season"] == rules["season"]


def test_api_football_has_no_hardcoded_league_ids_and_prediction_has_no_hidden_ingestion_call():
    cfg = load_json_config("config/intelligence/source_fusion.json")
    api = cfg["api_football"]
    assert api["resolve_league_ids_dynamically"] is True
    assert all(isinstance(alias, str) for aliases in api["competitions"].values() for alias in aliases)
    prediction_source = Path("src/v5/services/prediction.py").read_text(encoding="utf-8")
    assert "invoke_envelope" not in prediction_source
    assert "collect_enrichment" not in prediction_source
