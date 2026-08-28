from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"refusing blind edit; block not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Canonical fixture-run summary belongs to prediction model, not health/reporting.
model = ROOT / "src/models/v4_prediction.py"
old = '''def project_horizon(player, fixtures, ctx=None, advanced=None, n=15):\n    rows = [project_fixture(player, fixture, ctx, advanced) for fixture in fixtures[:n]]\n    expected_points = [row["xpts"] for row in rows]\n    return {\n        "element": player.get("id"),\n        "name": player.get("web_name"),\n        "position": POS.get(player.get("element_type")),\n        "fixtures": rows,\n        "xpts_3": round(sum(expected_points[:3]), 2),\n        "xpts_5": round(sum(expected_points[:5]), 2),\n        "xpts_10": round(sum(expected_points[:10]), 2),\n        "xpts_15": round(sum(expected_points[:15]), 2),\n        "mean_xpts": round(mean(expected_points), 3) if expected_points else 0,\n        "uncertainty": round(pstdev(expected_points), 3) if len(expected_points) > 1 else None,\n        "model": "v4.9.2-truthful-health",\n    }\n'''
new = '''def fixture_run_summary(rows, window=5):\n    """Summarize the canonical fixture-adjustment path without re-scoring fixtures."""\n    adjustments = [f((row.get("calibration") or {}).get("fixture_adjustment"), 1.0) for row in rows]\n    windows = []\n    for start in range(0, len(adjustments), window):\n        chunk = adjustments[start:start + window]\n        if not chunk:\n            continue\n        windows.append({\n            "start_offset": start + 1,\n            "end_offset": start + len(chunk),\n            "average_adjustment": round(mean(chunk), 4),\n        })\n    first = windows[0]["average_adjustment"] if windows else None\n    second = windows[1]["average_adjustment"] if len(windows) > 1 else None\n    final = windows[2]["average_adjustment"] if len(windows) > 2 else (windows[-1]["average_adjustment"] if windows else None)\n    delta = round(second - first, 4) if first is not None and second is not None else None\n    if delta is None:\n        direction = "UNKNOWN"\n    elif delta >= 0.03:\n        direction = "IMPROVING"\n    elif delta <= -0.03:\n        direction = "WORSENING"\n    else:\n        direction = "STABLE"\n    best = max(windows, key=lambda row: row["average_adjustment"]) if windows else None\n    worst = min(windows, key=lambda row: row["average_adjustment"]) if windows else None\n    return {\n        "source": "official_fpl_fixture_adjustment",\n        "window_size": window,\n        "windows": windows,\n        "first5_average_adjustment": first,\n        "next5_average_adjustment": second,\n        "final5_average_adjustment": final,\n        "swing_next5_vs_first5": delta,\n        "direction": direction,\n        "best_window": best,\n        "worst_window": worst,\n        "decision_usage": "multi_horizon_projection_context",\n    }\n\n\ndef project_horizon(player, fixtures, ctx=None, advanced=None, n=15):\n    rows = [project_fixture(player, fixture, ctx, advanced) for fixture in fixtures[:n]]\n    expected_points = [row["xpts"] for row in rows]\n    return {\n        "element": player.get("id"),\n        "name": player.get("web_name"),\n        "position": POS.get(player.get("element_type")),\n        "fixtures": rows,\n        "fixture_run": fixture_run_summary(rows),\n        "xpts_3": round(sum(expected_points[:3]), 2),\n        "xpts_5": round(sum(expected_points[:5]), 2),\n        "xpts_10": round(sum(expected_points[:10]), 2),\n        "xpts_15": round(sum(expected_points[:15]), 2),\n        "mean_xpts": round(mean(expected_points), 3) if expected_points else 0,\n        "uncertainty": round(pstdev(expected_points), 3) if len(expected_points) > 1 else None,\n        "model": "v4.9.2-truthful-health",\n    }\n'''
replace_once(model, old, new)

# 2) Health proves existing canonical prediction evidence; it does not recalculate prediction.
health = ROOT / "src/engines/framework_health_audit.py"
anchor = '''def _probe_uncertainty() -> tuple[bool, dict]:\n    fixtures = [fixture for player in _predictions()[:50] for fixture in (player.get("fixtures") or [])[:3]]\n    good = sum(\n        fixture.get("lower80") is not None\n        and fixture.get("upper80") is not None\n        and fixture["lower80"] <= fixture.get("xpts", 0) <= fixture["upper80"]\n        for fixture in fixtures\n    )\n    return bool(fixtures) and good == len(fixtures), {"fixtures": len(fixtures), "valid_intervals": good}\n\n\n'''
probes = '''def _probe_sustainability(players=None) -> tuple[bool, dict]:\n    players = list(players if players is not None else _predictions())\n    fixtures = [(player.get("fixtures") or [None])[0] for player in players]\n    fixtures = [fixture for fixture in fixtures if fixture]\n    covered = 0\n    material_shrinkage = 0\n    valid_weights = 0\n    for fixture in fixtures:\n        rate = fixture.get("rates") or {}\n        calibration = fixture.get("calibration") or {}\n        provenance = fixture.get("provenance") or {}\n        required = ("xg90", "xa90", "raw_xg90", "raw_xa90", "current_season_weight")\n        if all(key in rate for key in required) and "last_season_weight" in calibration and provenance.get("attacking_rate_shrinkage") is True:\n            covered += 1\n        current_weight = float(rate.get("current_season_weight") or 0)\n        last_weight = float(calibration.get("last_season_weight") or 0)\n        valid_weights += int(0 <= current_weight <= 1 and 0 <= last_weight <= 1)\n        material_shrinkage += int(\n            abs(float(rate.get("raw_xg90") or 0) - float(rate.get("xg90") or 0)) > 0.01\n            or abs(float(rate.get("raw_xa90") or 0) - float(rate.get("xa90") or 0)) > 0.01\n        )\n    ok = bool(fixtures) and covered == len(fixtures) and valid_weights == len(fixtures) and material_shrinkage > 0\n    return ok, {\n        "players": len(players),\n        "fixtures_checked": len(fixtures),\n        "shrinkage_evidence_covered": covered,\n        "valid_weight_rows": valid_weights,\n        "material_shrinkage_players": material_shrinkage,\n        "canonical_owner": "src.models.v4_prediction.rates",\n    }\n\n\ndef _probe_fixture_swing(players=None) -> tuple[bool, dict]:\n    players = list(players if players is not None else _predictions())\n    summaries = [player.get("fixture_run") or {} for player in players]\n    complete = 0\n    swings = []\n    directions = Counter()\n    for summary in summaries:\n        windows = list(summary.get("windows") or [])\n        swing = summary.get("swing_next5_vs_first5")\n        valid = (\n            summary.get("source") == "official_fpl_fixture_adjustment"\n            and summary.get("decision_usage") == "multi_horizon_projection_context"\n            and len(windows) >= 3\n            and summary.get("best_window") is not None\n            and summary.get("worst_window") is not None\n            and swing is not None\n        )\n        complete += int(valid)\n        if swing is not None:\n            swings.append(round(float(swing), 4))\n        directions[str(summary.get("direction"))] += 1\n    distinct_swings = len(set(swings))\n    ok = bool(players) and complete == len(players) and distinct_swings > 1\n    return ok, {\n        "players": len(players),\n        "fixture_run_covered": complete,\n        "distinct_swing_values": distinct_swings,\n        "directions": dict(directions),\n        "canonical_owner": "src.models.v4_prediction.fixture_run_summary",\n    }\n\n\n'''
replace_once(health, anchor, anchor + probes)
replace_once(
    health,
    '''        "advanced_stats_sync": _probe_advanced_sync,\n        "opponent_defence_dynamic": _probe_opponent_defence,\n''',
    '''        "advanced_stats_sync": _probe_advanced_sync,\n        "sustainability": _probe_sustainability,\n        "fixture_swing": _probe_fixture_swing,\n        "opponent_defence_dynamic": _probe_opponent_defence,\n''',
)
replace_once(
    health,
    '''        "system_fit",\n        "sustainability", "bonus_route", "team_defensive_risk", "team_attacking_strength",\n        "team_defensive_strength", "fixture_context", "fixture_swing",\n''',
    '''        "system_fit",\n        "bonus_route", "team_defensive_risk", "team_attacking_strength",\n        "team_defensive_strength", "fixture_context",\n''',
)

# 3) Central quality gate makes the promotions mandatory and auditable.
quality = ROOT / "src/engines/v4_quality_gate.py"
replace_once(
    quality,
    '''    eligible = lifecycle.get("eligibility", {}).get("eligible_samples")\n    if eligible is not None:\n        core = {row["id"]: row for row in health["dss_core"]["items"]}\n        extensions = {row["id"]: row for row in health["dss_extensions"]["items"]}\n''',
    '''    core = {row["id"]: row for row in health["dss_core"]["items"]}\n    extensions = {row["id"]: row for row in health["dss_extensions"]["items"]}\n    assert core["DSS-16"]["status"] == "ACTIVE", core["DSS-16"]\n    assert core["DSS-29"]["status"] == "ACTIVE", core["DSS-29"]\n    eligible = lifecycle.get("eligibility", {}).get("eligible_samples")\n    if eligible is not None:\n''',
)
replace_once(
    quality,
    '''    assert evidence.get("role_competition_factor_variants", 0) > 1\n    all_x = [fx["xpts"] for row in players for fx in row.get("fixtures", [])]\n''',
    '''    assert evidence.get("role_competition_factor_variants", 0) > 1\n    fixture_run_complete = sum(\n        (row.get("fixture_run") or {}).get("source") == "official_fpl_fixture_adjustment"\n        and (row.get("fixture_run") or {}).get("decision_usage") == "multi_horizon_projection_context"\n        for row in players\n    )\n    assert fixture_run_complete == len(players)\n    all_x = [fx["xpts"] for row in players for fx in row.get("fixtures", [])]\n''',
)

# 4) Explicit ownership prevents future semantic overlap.
ownership_path = ROOT / "config/architecture_ownership_registry.json"
ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
shared = ownership.setdefault("shared_primitives", [])
for row in (
    {
        "id": "RATE_SHRINKAGE_SUSTAINABILITY",
        "owner": "prediction_model",
        "implementation": "src.models.v4_prediction.rates",
        "consumers": ["DSS-16", "DSS-38"],
    },
    {
        "id": "FIXTURE_RUN_SUMMARY",
        "owner": "prediction_model",
        "implementation": "src.models.v4_prediction.fixture_run_summary",
        "consumers": ["DSS-25", "DSS-26", "DSS-27", "DSS-28", "DSS-29"],
    },
):
    if not any(existing.get("id") == row["id"] for existing in shared):
        shared.append(row)
ownership_path.write_text(json.dumps(ownership, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# 5) Focused regression tests.
test_path = ROOT / "tests/test_v4962_internal_evidence_closeout.py"
test_path.write_text('''from src.engines.framework_health_audit import _probe_fixture_swing, _probe_sustainability\nfrom src.models.v4_prediction import fixture_run_summary\n\n\ndef _fixture(adj):\n    return {\n        "xpts": 4.0,\n        "calibration": {"fixture_adjustment": adj, "last_season_weight": 0.4},\n        "rates": {\n            "xg90": 0.4, "xa90": 0.2, "raw_xg90": 0.8, "raw_xa90": 0.3,\n            "current_season_weight": 0.2,\n        },\n        "provenance": {"attacking_rate_shrinkage": True},\n    }\n\n\ndef test_fixture_run_summary_uses_canonical_adjustments_only():\n    rows = [_fixture(x) for x in ([0.8] * 5 + [1.1] * 5 + [0.95] * 5)]\n    out = fixture_run_summary(rows)\n    assert out["source"] == "official_fpl_fixture_adjustment"\n    assert out["direction"] == "IMPROVING"\n    assert out["swing_next5_vs_first5"] == 0.3\n    assert len(out["windows"]) == 3\n    assert out["decision_usage"] == "multi_horizon_projection_context"\n\n\ndef test_sustainability_probe_proves_shrinkage_is_consumed():\n    players = [{"fixtures": [_fixture(1.0)]}, {"fixtures": [_fixture(0.9)]}]\n    ok, detail = _probe_sustainability(players)\n    assert ok is True\n    assert detail["shrinkage_evidence_covered"] == 2\n    assert detail["material_shrinkage_players"] == 2\n    assert detail["canonical_owner"] == "src.models.v4_prediction.rates"\n\n\ndef test_fixture_swing_probe_requires_explicit_prediction_owned_summary():\n    a = fixture_run_summary([_fixture(x) for x in ([0.8] * 5 + [1.1] * 5 + [0.95] * 5)])\n    b = fixture_run_summary([_fixture(x) for x in ([1.1] * 5 + [0.85] * 5 + [1.0] * 5)])\n    ok, detail = _probe_fixture_swing([{"fixture_run": a}, {"fixture_run": b}])\n    assert ok is True\n    assert detail["fixture_run_covered"] == 2\n    assert detail["distinct_swing_values"] == 2\n    assert detail["canonical_owner"] == "src.models.v4_prediction.fixture_run_summary"\n''', encoding="utf-8")

readme = ROOT / "README.md"
text = readme.read_text(encoding="utf-8")
heading = "## V4.9.6 internal evidence closeout"
if heading not in text:
    text += f'''\n\n{heading}\n\n- DSS-16 Goal Involvement Sustainability is ACTIVE only when production prediction proves raw-vs-shrunk attacking rates, bounded current/last-season weights, and canonical attacking-rate shrinkage provenance.\n- DSS-29 Fixture Swing is ACTIVE through a prediction-owned `fixture_run` summary derived from the already canonical Official-FPL fixture-adjustment path; health/reporting do not rescore fixtures.\n- Ownership registry explicitly assigns rate-shrinkage sustainability and fixture-run summarization to the prediction model so future services must reuse rather than reimplement them.\n- DSS-08 System/Formation Fit and DSS-36 Multi-Season Prior remain PARTIAL until genuinely stronger evidence exists; they are not promoted by proxy.\n'''
    readme.write_text(text, encoding="utf-8")

print(json.dumps({"status": "staged", "promotions": ["DSS-16", "DSS-29"]}))
