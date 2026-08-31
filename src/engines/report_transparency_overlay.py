from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.engines.official_fact_publication_gate import run as run_official_fact_gate
from src.engines.report_user_presentation import run as run_user_presentation
from src.utils import DATA, ROOT, atomic_json, read_json

EVAL_CONFIG = ROOT / "config" / "intelligence" / "prediction_evaluation.json"
LINEUP_CONFIG = ROOT / "config" / "intelligence" / "lineup_governance.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


@lru_cache(maxsize=1)
def _eval_config() -> dict[str, Any]:
    return json.loads(EVAL_CONFIG.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _lineup_config() -> dict[str, Any]:
    return json.loads(LINEUP_CONFIG.read_text(encoding="utf-8"))


def _gw_row(player: dict[str, Any], gw: int) -> dict[str, Any]:
    return next((dict(row) for row in player.get("xpts_by_gw") or [] if int(row.get("gw") or -1) == gw), {})


def _open_choice_ids(lineup: dict[str, Any]) -> set[int]:
    open_ids: set[int] = set()
    battle = lineup.get("main_starting_xi_battle") or {}
    if battle.get("status") == "CLOSE":
        for side in ("starter_side", "bench_side"):
            open_ids.update(int(row["element"]) for row in battle.get(side) or [] if row.get("element") is not None)

    threshold = _f((_lineup_config().get("battle") or {}).get("close_margin_threshold"))
    if threshold <= 0:
        raise RuntimeError("report transparency requires positive config-owned battle close_margin_threshold")
    goalkeepers = [
        row for row in lineup.get("squad_rows") or []
        if row.get("position") == "GK" and row.get("element") is not None and row.get("selection_score") is not None
    ]
    if len(goalkeepers) == 2:
        margin = abs(_f(goalkeepers[0].get("selection_score")) - _f(goalkeepers[1].get("selection_score")))
        if margin < threshold:
            open_ids.update(int(row["element"]) for row in goalkeepers)
    return open_ids


def _decorate_owned(rows: list[dict[str, Any]], projections: dict[str, Any], lineup: dict[str, Any], gw: int) -> list[dict[str, Any]]:
    pmap = {int(row["element"]): row for row in projections.get("players") or [] if row.get("element") is not None}
    squad_map = {int(row["element"]): row for row in lineup.get("squad_rows") or [] if row.get("element") is not None}
    starter_ids = {int(row["element"]) for row in lineup.get("starting_xi") or [] if row.get("element") is not None}
    open_ids = _open_choice_ids(lineup)
    out = []
    for source in rows:
        row = dict(source)
        element = int(row.get("element") or -1)
        proj = pmap.get(element) or {}
        governed = squad_map.get(element)
        event = _gw_row(proj, gw)
        if not event:
            raise RuntimeError(f"owned report transparency missing GW{gw} projection for element={element}")
        if governed is None or governed.get("selection_score") is None:
            raise RuntimeError(f"owned report transparency missing governed selection_score for element={element}")
        row["xpts_gw"] = round(_f(event.get("mean")), 3)
        row["xpts_std"] = round(_f(event.get("std")), 3)
        row["selection_score"] = round(_f(governed.get("selection_score")), 4)
        row["lineup_status"] = "START" if element in starter_ids else "BENCH"
        row["choice_state"] = "OPEN" if element in open_ids else "CURRENT"
        out.append(row)
    if len(out) != 15:
        raise RuntimeError(f"owned transparency contract requires 15 players, got {len(out)}")
    return out


def _confidence_calibration(rows: list[dict[str, Any]], gw: int) -> dict[str, Any]:
    cfg = (_eval_config().get("projection_confidence_audit") or {})
    review_from = int(cfg.get("review_from_gw") or 5)
    minimum_high = int(cfg.get("minimum_high_count_after_review_gw") or 1)
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for row in rows:
        label = str(row.get("model_confidence") or "UNKNOWN").upper()
        counts[label if label in counts else "UNKNOWN"] += 1
    if gw < review_from and counts["HIGH"] < minimum_high:
        state = "EARLY_SEASON_CONSERVATIVE"
    elif counts["HIGH"] < minimum_high:
        state = "CALIBRATION_REVIEW_REQUIRED"
    else:
        state = "CONFIDENCE_RANGE_PRESENT"
    return {
        "planning_gw": gw,
        "state": state,
        "counts": counts,
        "review_from_gw": review_from,
        "minimum_high_count_after_review_gw": minimum_high,
        "governance": "monitor calibration; do not manufacture HIGH confidence",
    }


def _settled_validation(latest: dict[str, Any]) -> dict[str, Any]:
    row = latest.get("prediction_evaluation") or {}
    return {
        "status": row.get("status") or "NO_SETTLED_SAMPLE",
        "sample_size": int(row.get("sample_size") or 0),
        "confidence": row.get("confidence"),
        "settled_gameweeks": list(row.get("settled_gameweeks") or []),
        "dynamic_weight_eligible": bool(row.get("dynamic_weight_eligible")),
        "claim": "formula correctness is not predictive accuracy; accuracy requires settled frozen forecasts",
    }


def _weather_context(weather: dict[str, Any]) -> dict[str, Any]:
    material = list(weather.get("material_fixtures") or [])
    attribution = []
    for row in weather.get("fixtures") or []:
        closest = row.get("closest_to_kickoff") or {}
        if not row.get("post_match_attribution_ready") or closest.get("severity") not in {"NOTABLE", "ADVERSE", "EXTREME"}:
            continue
        attribution.append({
            "fixture_id": row.get("fixture_id"),
            "home_team": row.get("home_team"),
            "away_team": row.get("away_team"),
            "kickoff_time": row.get("kickoff_time"),
            "severity": closest.get("severity"),
            "signals": closest.get("signals") or [],
            "weather": closest.get("weather") or {},
            "label": "POSSIBLE_CONTRIBUTING_FACTOR",
        })
    return {
        "status": "AVAILABLE" if int(weather.get("available_count") or 0) > 0 else "NO_FORECAST_IN_WINDOW",
        "provider": weather.get("provider"),
        "generated_at": weather.get("generated_at"),
        "advisory_only": bool((weather.get("governance") or {}).get("advisory_only")),
        "material_fixtures": material,
        "post_match_attribution_candidates": attribution,
        "causality_guard": "weather correlation alone never proves causation",
    }


def _sync_current_authority(payload: dict[str, Any], *, compact_captaincy: bool) -> None:
    planning = ((payload.get("gameweek_context") or {}).get("planning") or {})
    if planning.get("status") != "PROJECTION":
        return

    starters = [dict(row) for row in planning.get("starting_xi") or []]
    bench = [dict(row) for row in planning.get("bench") or []]
    captain = dict(planning.get("captain") or {})
    vice = dict(planning.get("vice_captain") or {})
    bench_gk = next((row for row in bench if row.get("position") == "GK"), {})
    outfield_bench = [row for row in bench if row.get("position") != "GK"]
    engine_recommendation = planning.get("engine_recommendation") or {}

    current_team = {
        "decision_authority": planning.get("decision_authority"),
        "source": planning.get("source"),
        "gw": planning.get("gw"),
        "formation": planning.get("formation"),
        "starting_xi": [row.get("name") for row in starters],
        "captain": captain.get("name"),
        "vice_captain": vice.get("name"),
        "bench_order": [row.get("name") for row in outfield_bench],
        "gk_bench": bench_gk.get("name"),
        "active_chip": planning.get("active_chip"),
        "estimated_points": planning.get("estimated_points"),
    }
    payload["current_team"] = current_team

    # Action Board is part of the human-serving contract. When a user override is
    # authoritative, it must not surface the engine captain as though it were the
    # current selection. Keep the challenger in its dedicated comparison field.
    if planning.get("decision_authority") == "USER_OVERRIDE" and captain.get("name"):
        board = []
        for raw in payload.get("action_board") or []:
            item = dict(raw)
            subject = str(item.get("subject") or "")
            if subject.lower().startswith("captain:"):
                item["subject"] = f"Captain: {captain.get('name')}"
                item["trigger"] = "ubah hanya jika ada kabar tim atau bukti baru yang material"
            board.append(item)
        payload["action_board"] = board

    if not compact_captaincy:
        return
    section = dict(payload.get("captaincy") or {})
    engine_captain = section.get("captain")
    engine_vice = section.get("vice")
    engine_reason = section.get("reason")
    section["captain"] = captain.get("name") or engine_captain
    section["vice"] = vice.get("name") or engine_vice
    section["authority"] = planning.get("decision_authority")
    if planning.get("decision_authority") == "USER_OVERRIDE":
        section["reason"] = "pilihan tim saat ini; tinjau ulang hanya jika ada kabar tim atau bukti baru yang material"
    section["engine_challenger"] = {
        "captain": engine_captain or engine_recommendation.get("captain"),
        "vice": engine_vice or engine_recommendation.get("vice_captain"),
        "formation": engine_recommendation.get("formation"),
        "estimated_points": engine_recommendation.get("estimated_points"),
        "reason": engine_reason,
    }
    payload["captaincy"] = section


def run() -> dict[str, Any]:
    latest = read_json(DATA / "latest.json", {})
    projections = read_json(DATA / "projections.json", {})
    lineup = read_json(DATA / "lineup_decision.json", {})
    weather = read_json(DATA / "fixture_weather.json", {})
    gw = int((latest.get("phase") or {}).get("planning_gw") or projections.get("planning_gw") or 0)
    if gw <= 0:
        raise RuntimeError("report transparency cannot determine planning GW")

    paths = [DATA / "user_report.json", DATA / "decision_brief.json", DATA / "deep_review_payload.json"]
    result = {}
    for path in paths:
        payload = read_json(path, {})
        if path.name == "user_report.json":
            owned = ((payload.get("owned_squad") or {}).get("facts") or [])
            decorated = _decorate_owned(owned, projections, lineup, gw)
            payload.setdefault("owned_squad", {})["facts"] = decorated
        else:
            decorated = _decorate_owned(list(payload.get("owned_15") or []), projections, lineup, gw)
            payload["owned_15"] = decorated
        payload["model_validation"] = {
            "confidence_calibration": _confidence_calibration(decorated, gw),
            "settled_prediction": _settled_validation(latest),
        }
        payload["weather_context"] = _weather_context(weather)
        _sync_current_authority(payload, compact_captaincy=path.name != "user_report.json")
        atomic_json(path, payload)
        result[path.name] = {"owned": len(decorated), "weather": payload["weather_context"]["status"]}

    presentation = run_user_presentation()
    result["user_presentation"] = {
        "checkpoint": ((presentation.get("checkpoint") or {}).get("current") or {}).get("id") or "ROUTINE",
        "completeness": (presentation.get("checkpoint") or {}).get("completeness"),
    }
    result["official_fact_integrity"] = run_official_fact_gate()
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
