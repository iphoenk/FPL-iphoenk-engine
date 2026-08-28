from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_service():
    path = ROOT / "src/services/challenger_comparator_service.py"
    text = path.read_text(encoding="utf-8")
    old = '''    if f(universe_row.get("points")) >= f(cfg.get("points_signal"), 8):\n        signals.append("RECENT_POINTS_RETURN")\n    if f(universe_row.get("expected_goal_involvements")) >= f(cfg.get("xgi_signal"), 0.55):\n        signals.append("UNDERLYING_XGI")\n'''
    new = '''    # Recent-match discovery must use Official FPL event_points from the\n    # immutable raw snapshot. Season total_points is never a recent-haul proxy.\n    if universe_row.get("event_points") is not None and f(universe_row.get("event_points")) >= f(cfg.get("points_signal"), 8):\n        signals.append("RECENT_EVENT_POINTS_RETURN")\n    if f(universe_row.get("expected_goal_involvements")) >= f(cfg.get("xgi_signal"), 0.55):\n        signals.append("SEASON_UNDERLYING_XGI")\n'''
    if old not in text:
        raise RuntimeError("trigger source anchor missing")
    text = text.replace(old, new, 1)

    anchor = '''    if raw.get("schema") != "snapshot.v1":\n        raise RuntimeError("immutable raw snapshot contract is required for fixture identity")\n'''
    replacement = '''    if raw.get("schema") != "snapshot.v1":\n        raise RuntimeError("immutable raw snapshot contract is required for fixture identity")\n    event_points_coverage = 0\n    for player in (((raw.get("official") or {}).get("bootstrap") or {}).get("elements") or []):\n        element = int(player.get("id") or 0)\n        if element in umap:\n            # Local comparator evidence only: do not mutate canonical universe.\n            umap[element]["event_points"] = player.get("event_points")\n            event_points_coverage += player.get("event_points") is not None\n'''
    if anchor not in text:
        raise RuntimeError("raw snapshot anchor missing")
    text = text.replace(anchor, replacement, 1)

    anchor2 = '''            "emerging_trigger_is_not_transfer": True,\n        },\n'''
    replacement2 = '''            "emerging_trigger_is_not_transfer": True,\n            "recent_event_points_source": "raw_snapshot.official.bootstrap.elements.event_points",\n            "recent_event_points_coverage": event_points_coverage,\n            "season_total_points_never_used_as_recent_haul": True,\n        },\n'''
    if anchor2 not in text:
        raise RuntimeError("challenger universe output anchor missing")
    text = text.replace(anchor2, replacement2, 1)
    path.write_text(text, encoding="utf-8")


def patch_tests():
    path = ROOT / "tests/test_v497_challenger_comparator.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace('        "points": points,\n', '        "points": points,\n        "event_points": points,\n', 1)
    text = text.replace('    assert "RECENT_POINTS_RETURN" in signals\n', '    assert "RECENT_EVENT_POINTS_RETURN" in signals\n', 1)

    bad = '''    tactical = {"teams": {"1": {"events": {str(gw): {"rest_days": 3, competition_field: {"verified": True}, "matchup_edge": "NEUTRAL", "matchup_risk": "MEDIUM", "confidence": .8, "source": "test_verified"} for gw in range(2, 7)}}}, "2": {"events": {str(gw): {"rest_days": 3, competition_field: {"verified": True}, "matchup_edge": "POSITIVE", "matchup_risk": "LOW", "confidence": .8, "source": "test_verified"} for gw in range(2, 7)}}}}}\n'''
    good = '''    tactical = {\n        "teams": {\n            "1": {\n                "events": {\n                    str(gw): {\n                        "rest_days": 3,\n                        competition_field: {"verified": True},\n                        "matchup_edge": "NEUTRAL",\n                        "matchup_risk": "MEDIUM",\n                        "confidence": .8,\n                        "source": "test_verified",\n                    }\n                    for gw in range(2, 7)\n                }\n            },\n            "2": {\n                "events": {\n                    str(gw): {\n                        "rest_days": 3,\n                        competition_field: {"verified": True},\n                        "matchup_edge": "POSITIVE",\n                        "matchup_risk": "LOW",\n                        "confidence": .8,\n                        "source": "test_verified",\n                    }\n                    for gw in range(2, 7)\n                }\n            },\n        }\n    }\n'''
    if bad not in text:
        raise RuntimeError("syntax-error test anchor missing")
    text = text.replace(bad, good, 1)

    marker = "def test_season_total_points_never_masquerades_as_recent_haul():"
    if marker not in text:
        text += '''\n\ndef test_season_total_points_never_masquerades_as_recent_haul():\n    row = universe(99, "SeasonTotalOnly", 9, points=15, xgi=0.0, starts=0, minutes=0, tin=0, tout=0)\n    row["points"] = 99\n    row["event_points"] = 2\n    pred = prediction(99, "SeasonTotalOnly", value=0.5)\n    signals = _trigger_signals(row, pred, policy())\n    assert "RECENT_EVENT_POINTS_RETURN" not in signals\n\n\ndef test_missing_event_points_does_not_fabricate_recent_haul():\n    row = universe(100, "NoEventPoints", 10, points=15, xgi=0.0, starts=0, minutes=0, tin=0, tout=0)\n    row["points"] = 99\n    row.pop("event_points", None)\n    pred = prediction(100, "NoEventPoints", value=0.5)\n    signals = _trigger_signals(row, pred, policy())\n    assert "RECENT_EVENT_POINTS_RETURN" not in signals\n'''
    path.write_text(text, encoding="utf-8")


def patch_registries():
    service_path = ROOT / "config/service_registry.json"
    service = json.loads(service_path.read_text(encoding="utf-8"))
    service["schema_version"] = 11
    service["registry"] = "fpl_v4_9_6_microservice_registry_v11"
    service_path.write_text(json.dumps(service, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    contract_path = ROOT / "config/service_contract_registry.json"
    contracts = json.loads(contract_path.read_text(encoding="utf-8"))
    contracts["schema_version"] = 9
    contracts["registry"] = "fpl_v4_9_6_service_contracts_v9"
    comparator = contracts["contracts"]["challenger_comparator"]
    required = comparator.setdefault("required_paths", [])
    for field in (
        "challenger_universe.recent_event_points_source",
        "challenger_universe.recent_event_points_coverage",
        "challenger_universe.season_total_points_never_used_as_recent_haul",
    ):
        if field not in required:
            required.append(field)
    comparator.setdefault("equals", {})["challenger_universe.recent_event_points_source"] = "raw_snapshot.official.bootstrap.elements.event_points"
    comparator["equals"]["challenger_universe.season_total_points_never_used_as_recent_haul"] = True
    contract_path.write_text(json.dumps(contracts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    patch_service()
    patch_tests()
    patch_registries()
    print("V4 comparator truth + syntax + registry metadata fix applied")


if __name__ == "__main__":
    main()
