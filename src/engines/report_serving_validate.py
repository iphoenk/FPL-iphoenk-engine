from __future__ import annotations

import json
from pathlib import Path

from src.engines.tactical_decision_consumption import apply_report_overlay
from src.utils import DATA, ROOT

REGISTRY = ROOT / "config" / "report_artifact_registry.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _watch_ids(positions: dict) -> list[int]:
    return [int(row["element"]) for rows in positions.values() for row in rows]


def _validate_owned_transparency(name: str, rows: list[dict], expected: int, contract: dict) -> None:
    assert len(rows) == expected, (name, len(rows), expected)
    assert len({int(row["element"]) for row in rows}) == expected
    if contract.get("owned_rows_require_current_gw_xpts"):
        assert all(row.get("xpts_gw") is not None for row in rows), (name, "missing_xpts")
        assert all(row.get("xpts_std") is not None for row in rows), (name, "missing_xpts_std")
    if contract.get("owned_rows_require_selection_score"):
        assert all(row.get("selection_score") is not None for row in rows), (name, "missing_selection_score")
    if contract.get("owned_rows_require_lineup_status"):
        assert all(row.get("lineup_status") in {"START", "BENCH"} for row in rows), (name, "invalid_lineup_status")
    if contract.get("owned_rows_require_choice_state"):
        assert all(row.get("choice_state") in {"OPEN", "CURRENT"} for row in rows), (name, "invalid_choice_state")


def _validate_personal_gameweek_context(payload_name: str, payload: dict) -> None:
    context = payload.get("gameweek_context") or {}
    assert context.get("schema") == "personal_gameweek_context.v1", (payload_name, context.get("schema"))
    planning = context.get("planning") or {}
    assert planning.get("status") == "PROJECTION", (payload_name, planning)
    assert planning.get("estimated_points") is not None, payload_name
    assert planning.get("decision_authority") in {"ENGINE_RECOMMENDATION", "USER_OVERRIDE"}, payload_name
    assert (planning.get("scoring_guardrails") or {}).get("estimate_not_actual") is True, payload_name
    baseline = planning.get("baseline") or {}
    assert baseline.get("default_rule") == "PLANNING_GW_FROM_PREVIOUS_OFFICIAL_SUBMITTED_SQUAD", (payload_name, baseline)
    if planning.get("user_override_active"):
        assert planning.get("decision_authority") == "USER_OVERRIDE", payload_name
        assert (planning.get("comparison") or {}).get("engine_can_warn_but_not_overwrite_user") is True, payload_name
    for row in context.get("historical") or []:
        assert row.get("status") == "FINAL", (payload_name, row)
        assert row.get("authority") == "PUBLIC_OFFICIAL_POST_DEADLINE", (payload_name, row)
        assert row.get("actual_points") is not None, (payload_name, row)
        assert row.get("forecast_capture") == "NOT_RECONSTRUCTED", (payload_name, row)
        assert len(row.get("submitted_squad") or []) == 15, (payload_name, row.get("gw"))
    governance = context.get("governance") or {}
    assert governance.get("historical_truth_never_reconstructed_as_old_forecast") is True, payload_name
    assert governance.get("engine_recommendation_remains_visible_for_comparison") is True, payload_name


def _validate_tactical(payload_name: str, payload: dict, expected_owned: int, expected_watch: int) -> None:
    context = payload.get("tactical_context") or {}
    assert int(context.get("owned_players") or 0) == expected_owned, (payload_name, context)
    assert int(context.get("watchlist_players") or 0) == expected_watch, (payload_name, context)
    usage = context.get("decision_usage") or {}
    assert usage.get("direct_xpts_mutation") is False, (payload_name, usage)
    owned_rows = ((payload.get("owned_squad") or {}).get("facts") or []) if "owned_squad" in payload else (payload.get("owned_15") or [])
    assert all(isinstance(row.get("tactical_matchup"), dict) for row in owned_rows), (payload_name, "owned tactical coverage")
    assert all((row.get("tactical_matchup") or {}).get("evidence_state") in {"CUKUP", "TERBATAS", "TIDAK_TERSEDIA"} for row in owned_rows), (payload_name, "owned tactical state")
    watch_positions = ((payload.get("external_watchlist") or {}).get("positions") or {}) if "external_watchlist" in payload else (payload.get("watchlist_20") or {})
    watch_rows = [row for rows in watch_positions.values() for row in rows]
    assert len(watch_rows) == expected_watch, (payload_name, len(watch_rows))
    assert all(isinstance(row.get("tactical_matchup"), dict) for row in watch_rows), (payload_name, "watch tactical coverage")


def run() -> dict:
    # Tactical serving decoration is the final consumer overlay. It reuses the
    # projection-owned matchup and never recalculates or mutates xPts.
    tactical_overlay = apply_report_overlay()
    registry = _load(REGISTRY)
    runtime_registry = _load(DATA / "report_artifact_registry.json")
    assert runtime_registry == registry
    contract = registry["consumer_contract"]
    expected_owned = int(contract["owned_count"])
    expected_watch = int(contract["watchlist_total"])
    expected_per = int(contract["watchlist_per_position"])
    positions = list(contract["watchlist_positions"])

    brief = _load(DATA / "decision_brief.json")
    deep = _load(DATA / "deep_review_payload.json")
    user = _load(DATA / "user_report.json")
    summary = _load(DATA / "dss_watchlist_summary.json")
    latest = _load(DATA / "latest.json")

    owned = brief.get("owned_15") or []
    _validate_owned_transparency("brief", owned, expected_owned, contract)
    _validate_owned_transparency("deep", deep.get("owned_15") or [], expected_owned, contract)
    _validate_owned_transparency("user", ((user.get("owned_squad") or {}).get("facts") or []), expected_owned, contract)
    owned_ids = {int(x["element"]) for x in owned}

    for payload_name, watch_positions in (
        ("brief", brief.get("watchlist_20") or {}),
        ("deep", deep.get("watchlist_20") or {}),
        ("user", ((user.get("external_watchlist") or {}).get("positions") or {})),
        ("summary", summary.get("positions") or {}),
    ):
        assert set(watch_positions) == set(positions), (payload_name, sorted(watch_positions))
        for position in positions:
            rows = watch_positions.get(position) or []
            assert len(rows) == expected_per, (payload_name, position, len(rows), expected_per)
            assert all(row.get("position") == position for row in rows), (payload_name, position)
        ids = _watch_ids(watch_positions)
        assert len(ids) == expected_watch and len(set(ids)) == expected_watch, (payload_name, len(ids), len(set(ids)))
        assert not (owned_ids & set(ids)), (payload_name, sorted(owned_ids & set(ids)))

    assert (user.get("serving_contract") or {}).get("owned") == expected_owned
    assert (user.get("serving_contract") or {}).get("watchlist") == expected_watch
    assert (brief.get("serving_contract") or {}).get("owned") == expected_owned
    assert (brief.get("serving_contract") or {}).get("watchlist") == expected_watch

    for payload_name, payload in (("brief", brief), ("deep", deep), ("user", user)):
        _validate_tactical(payload_name, payload, expected_owned, expected_watch)
        if contract.get("report_time_intelligence_required") is True:
            report_time = payload.get("report_time_intelligence") or {}
            assert report_time.get("status") in {"REFRESH_REQUIRED", "READY", "INVALID_EVIDENCE_CONTRACT"}, (payload_name, report_time)
            assert "pundit_consensus_vs_dss" in report_time, payload_name
            assert "fixture_strategy" in report_time, payload_name
            assert "community_signal" in report_time, payload_name
        if contract.get("model_validation_required") is True:
            validation = payload.get("model_validation") or {}
            assert (validation.get("confidence_calibration") or {}).get("state") in {"EARLY_SEASON_CONSERVATIVE", "CALIBRATION_REVIEW_REQUIRED", "CONFIDENCE_RANGE_PRESENT"}, payload_name
            settled = validation.get("settled_prediction") or {}
            assert "sample_size" in settled and "status" in settled, payload_name
        if contract.get("weather_context_required") is True:
            weather = payload.get("weather_context") or {}
            assert weather.get("status") in {"AVAILABLE", "NO_FORECAST_IN_WINDOW"}, (payload_name, weather)
            assert weather.get("advisory_only") is True, payload_name
            assert weather.get("causality_guard"), payload_name
        if contract.get("personal_gameweek_context_required") is True:
            _validate_personal_gameweek_context(payload_name, payload)
    assert deep.get("payload_type") == "DEEP_REVIEW_PAYLOAD_V2"

    files = latest.get("files") or {}
    assert files.get("decision_brief") == "data/decision_brief.json"
    assert files.get("deep_review_payload") == "data/deep_review_payload.json"
    assert files.get("dss_watchlist_summary") == "data/dss_watchlist_summary.json"
    assert files.get("report_artifact_registry") == "data/report_artifact_registry.json"
    assert latest.get("report_serving", {}).get("owned_count") == expected_owned
    assert latest.get("report_serving", {}).get("watchlist_count") == expected_watch
    assert latest.get("report_serving", {}).get("personal_gameweek_context") is True
    assert latest.get("report_serving", {}).get("report_time_intelligence") is True
    assert latest.get("report_serving", {}).get("technical_lazy_load") is True

    sizes = {}
    for name, spec in (registry.get("artifacts") or {}).items():
        path_text = str(spec.get("path") or "")
        if not path_text.startswith("data/"):
            continue
        path = DATA / path_text.removeprefix("data/")
        if not path.exists():
            continue
        sizes[name] = path.stat().st_size
        if spec.get("priority") == "P0" and spec.get("max_bytes") is not None:
            assert sizes[name] <= int(spec["max_bytes"]), (name, sizes[name], spec["max_bytes"])

    result = {
        "status": "PASS",
        "registry": registry.get("registry"),
        "owned": expected_owned,
        "watchlist": expected_watch,
        "per_position": expected_per,
        "owned_transparency": True,
        "tactical_context": True,
        "tactical_overlay": tactical_overlay,
        "tactical_direct_xpts_mutation": False,
        "selection_score": contract.get("owned_rows_require_selection_score"),
        "model_validation": contract.get("model_validation_required"),
        "weather_context": contract.get("weather_context_required"),
        "report_time_intelligence": contract.get("report_time_intelligence_required"),
        "personal_gameweek_context": contract.get("personal_gameweek_context_required"),
        "sizes": sizes,
        "default_fast": latest.get("report_serving", {}).get("default_fast_artifact"),
        "default_deep": latest.get("report_serving", {}).get("default_deep_review_artifact"),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
