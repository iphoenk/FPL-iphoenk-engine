from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.engines.official_snapshot_primitives import endpoint_health, load_snapshot, snapshot_picks_for_gw
from src.sources.official_fpl import get_json
from src.utils import DATA, ROOT, atomic_json, iso_now

CONFIG_PATH = ROOT / "config" / "intelligence" / "prediction_evaluation.json"


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _compact_picks(payload: dict[str, Any]) -> dict[str, Any]:
    entry_history = payload.get("entry_history") or {}
    return {
        "active_chip": payload.get("active_chip"),
        "entry_history": {
            key: entry_history.get(key)
            for key in (
                "event",
                "points",
                "total_points",
                "rank",
                "rank_sort",
                "overall_rank",
                "bank",
                "value",
                "event_transfers",
                "event_transfers_cost",
                "points_on_bench",
            )
            if key in entry_history
        },
        "picks": [
            {
                "element": row.get("element"),
                "position": row.get("position"),
                "multiplier": row.get("multiplier"),
                "is_captain": bool(row.get("is_captain")),
                "is_vice_captain": bool(row.get("is_vice_captain")),
            }
            for row in (payload.get("picks") or [])
            if isinstance(row, dict)
        ],
        "automatic_subs": payload.get("automatic_subs") or [],
    }



FULL_SEASON_HISTORY_CONTRACT = "OFFICIAL_FULL_SEASON_PLAYER_HISTORY_V1"
_HISTORY_METRICS = (
    "minutes", "goals_scored", "assists", "clean_sheets", "goals_conceded",
    "saves", "goals_prevented", "defensive_contribution", "bonus", "bps",
    "expected_goals", "expected_assists", "xg", "xa", "xgi", "yellow_cards",
    "red_cards", "penalties_saved", "penalties_missed", "own_goals",
    "total_points", "value",
)
_ADDITIVE_METRICS = set(_HISTORY_METRICS) - {"value"}

def _gw(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None

def _event_catalog(snapshot: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    events = ((snapshot.get("bootstrap") or {}).get("events") or [])
    catalog = {}
    for row in events:
        if not isinstance(row, Mapping):
            continue
        gw = _gw(row.get("id"))
        if gw is not None:
            catalog[gw] = {"finished": row.get("finished") is True, "is_current": row.get("is_current") is True, "deadline_time": row.get("deadline_time")}
    return catalog

def _numeric(value: Any) -> int | float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number

def _aggregate_history_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    aggregate: dict[str, Any] = {}
    for key in _HISTORY_METRICS:
        values = [_numeric(row.get(key)) for row in rows]
        values = [value for value in values if value is not None]
        if values:
            aggregate[key] = sum(values) if key in _ADDITIVE_METRICS else values[-1]
    return aggregate

def _classify_slot(*, gw: int, rows: Sequence[Mapping[str, Any]], fixture_rows: Sequence[Mapping[str, Any]], catalog: Mapping[int, Mapping[str, Any]]) -> str:
    event = dict(catalog.get(gw) or {})
    if event.get("finished") is not True:
        return "PENDING"
    if rows:
        minutes = sum(float(row.get("minutes") or 0) for row in rows)
        return "DNP" if minutes <= 0 else "FINAL"
    return "DNP" if fixture_rows else "BLANK"

def build_full_season_history(*, snapshot: Mapping[str, Any], detail: Mapping[str, Any]) -> dict[str, Any]:
    """Build a full GW1..N-1, full-universe Official FPL history gate."""
    bootstrap = snapshot.get("bootstrap") or {}
    elements = [row for row in bootstrap.get("elements") or [] if isinstance(row, Mapping) and _gw(row.get("id")) is not None]
    element_ids = sorted({_gw(row.get("id")) for row in elements})
    phase = snapshot.get("phase") or {}
    planning_gw = _gw(phase.get("current_gw")) or (max((_gw(row.get("event")) or 0 for row in (snapshot.get("history") or {}).get("current") or []), default=0) + 1)
    historical_gws = list(range(1, max(1, planning_gw)))
    catalog = _event_catalog(snapshot)
    # Fixture-level identity must be checked against the same Official FPL
    # occurrence as the element-summary rows. A populated slot alone is not
    # sufficient evidence of a valid player-match record.
    fixture_catalog = {
        int(row["id"]): _gw(row.get("event"))
        for row in (snapshot.get("fixtures") or [])
        if isinstance(row, Mapping) and _gw(row.get("id")) is not None
    }
    summaries = detail.get("element_summaries") or {}
    players: dict[str, Any] = {}
    missing_slots: list[dict[str, int]] = []
    identity_anomalies: list[dict[str, Any]] = []
    verified_fixture_rows = 0
    for element in elements:
        element_id = _gw(element.get("id"))
        if element_id is None:
            continue
        summary = summaries.get(str(element_id))
        history_rows = [dict(row) for row in (summary or {}).get("history") or [] if isinstance(row, Mapping)]
        fixture_rows = [dict(row) for row in (summary or {}).get("fixtures") or [] if isinstance(row, Mapping)]
        history_by_gw: dict[int, list[dict[str, Any]]] = defaultdict(list)
        fixtures_by_gw: dict[int, list[dict[str, Any]]] = defaultdict(list)
        seen_player_fixtures: set[int] = set()
        for row in history_rows:
            row_gw = _gw(row.get("round") or row.get("event"))
            fixture_id = _gw(row.get("fixture"))
            anomaly = None
            if row_gw is None or fixture_id is None:
                anomaly = "MISSING_GW_OR_FIXTURE_ID"
            elif fixture_id in seen_player_fixtures:
                anomaly = "DUPLICATE_PLAYER_FIXTURE_ID"
            elif fixture_catalog and fixture_id not in fixture_catalog:
                anomaly = "UNKNOWN_OFFICIAL_FIXTURE_ID"
            elif fixture_catalog and fixture_catalog[fixture_id] != row_gw:
                anomaly = "OFFICIAL_FIXTURE_GW_MISMATCH"
            if anomaly:
                identity_anomalies.append({
                    "element": element_id, "gw": row_gw,
                    "fixture_id": fixture_id, "reason": anomaly,
                })
            elif fixture_catalog:
                verified_fixture_rows += 1
            if fixture_id is not None:
                seen_player_fixtures.add(fixture_id)
            if row_gw is not None:
                history_by_gw[row_gw].append(row)
        for row in fixture_rows:
            row_gw = _gw(row.get("event") or row.get("round"))
            if row_gw is not None:
                fixtures_by_gw[row_gw].append(row)
        records: dict[str, Any] = {}
        if summary is None:
            missing_slots.extend({"element": element_id, "gw": gameweek} for gameweek in historical_gws)
        else:
            for gameweek in historical_gws:
                rows = history_by_gw.get(gameweek, [])
                fixture_set = fixtures_by_gw.get(gameweek, [])
                records[str(gameweek)] = {"gw": gameweek, "status": _classify_slot(gw=gameweek, rows=rows, fixture_rows=fixture_set, catalog=catalog), "fixtures": rows, "fixture_context": fixture_set, "aggregate": _aggregate_history_rows(rows), "fixture_count": len(rows) if rows else len(fixture_set), "source": f"Official FPL element-summary/{element_id}/"}
        players[str(element_id)] = {"element_id": element_id, "position": element.get("element_type"), "team": element.get("team"), "history": records, "coverage": {"expected_gw_slots": len(historical_gws), "available_gw_slots": len(records), "missing_gw_slots": len(historical_gws) - len(records)}}
    expected_slots = len(element_ids) * len(historical_gws)
    available_slots = sum(int((row.get("coverage") or {}).get("available_gw_slots") or 0) for row in players.values())
    identity_complete = bool(fixture_catalog) and not identity_anomalies
    status = "PASS" if len(players) == len(element_ids) and available_slots == expected_slots and not missing_slots and identity_complete else "PARTIAL"
    return {"contract": FULL_SEASON_HISTORY_CONTRACT, "generated_at": iso_now(), "as_of": {"canonical_timestamp": snapshot.get("generated_at"), "planning_gw": planning_gw, "historical_gws": historical_gws, "source": "OFFICIAL_FPL_ELEMENT_SUMMARY"}, "universe": {"expected_players": len(element_ids), "covered_players": len(players), "coverage_ratio": round(len(players) / len(element_ids), 6) if element_ids else 0.0}, "coverage_gate": {"status": status, "expected_gw_slots": len(historical_gws), "available_gw_slots": available_slots, "expected_player_slots": expected_slots, "missing_records": missing_slots, "fixture_identity_status": "PASS" if identity_complete else "PARTIAL", "verified_fixture_rows": verified_fixture_rows, "fixture_catalog_count": len(fixture_catalog), "fixture_identity_anomalies": identity_anomalies, "pending_never_coerced_to_zero": True, "dnp_and_blank_distinguished": True, "double_gameweeks_aggregate_fixture_rows": True}, "provenance": {"authority": "Official FPL", "endpoint_template": "element-summary/{element_id}/", "fixture_level_rows_preserved": True, "single_snapshot": True, "fallback_used": False}, "players": players}


def run() -> dict[str, Any]:
    cfg = _load(CONFIG_PATH, {})
    proxy_cfg = cfg.get("retrospective_proxy_baseline") or {}
    detail = _load(DATA / "official_detail.json", {})
    latest = _load(DATA / "latest.json", {})
    team = _load(DATA / "team.json", {})
    team_id = _i(team.get("team_id"), 0)
    if team_id <= 0:
        raise RuntimeError("Official historical reconciliation requires authoritative team_id")
    snapshot = load_snapshot(DATA)

    history_payload = snapshot.get("history") or {}
    history_health = endpoint_health(snapshot, "history")
    current_rows = history_payload.get("current") or []
    finished_gws = sorted({_i(row.get("event")) for row in current_rows if _i(row.get("event")) > 0})
    # Full-season history is permanent: GW1..planning_gw-1.
    wanted = finished_gws

    rows: dict[str, Any] = {}
    health: dict[str, Any] = {"entry_history": history_health}
    reused_picks = 0
    fetched_picks = 0
    for gw in wanted:
        picks, picks_health = snapshot_picks_for_gw(snapshot, gw)
        if picks is not None:
            reused_picks += 1
            health[f"picks_gw_{gw}"] = {**picks_health, "reuse": "CORE_SNAPSHOT"}
        else:
            picks, picks_health = get_json(f"entry/{team_id}/event/{gw}/picks/", retries=1)
            fetched_picks += 1
            health[f"picks_gw_{gw}"] = picks_health
        history_row = next((row for row in current_rows if _i(row.get("event")) == gw), {})
        if not picks:
            rows[str(gw)] = {
                "gw": gw,
                "status": "OFFICIAL_PICKS_UNAVAILABLE",
                "history": history_row,
            }
            continue
        rows[str(gw)] = {
            "gw": gw,
            "status": "PUBLIC_OFFICIAL_SUBMITTED_TEAM",
            "authority": "PUBLIC_OFFICIAL_POST_DEADLINE",
            "history": history_row,
            "submitted": _compact_picks(picks),
        }

    proxy_gws = sorted({_i(x) for x in (proxy_cfg.get("gameweeks") or []) if _i(x) > 0})
    available_proxy = [gw for gw in proxy_gws if (rows.get(str(gw)) or {}).get("status") == "PUBLIC_OFFICIAL_SUBMITTED_TEAM"]
    full_season = build_full_season_history(snapshot=snapshot, detail=detail)
    detail["full_season_history"] = full_season
    historical = {
        "generated_at": iso_now(),
        "team_id": team_id,
        "status": "READY" if rows else "NO_FINISHED_GAMEWEEK_HISTORY",
        "authority": "PUBLIC_OFFICIAL_POST_DEADLINE",
        "gameweeks": rows,
        "full_season_history": {"contract": full_season["contract"], "planning_gw": full_season["as_of"]["planning_gw"], "historical_gws": full_season["as_of"]["historical_gws"], "coverage_gate": full_season["coverage_gate"], "universe": full_season["universe"]},
        "retrospective_proxy_baseline": {
            "label": proxy_cfg.get("label", "RETROSPECTIVE_PROXY_BASELINE"),
            "gameweeks": available_proxy,
            "forecast_capture": "NOT_VERIFIED_PRE_DEADLINE",
            "use_for_predictive_accuracy": False,
            "use_for_dynamic_weight": False,
            "purpose": "historical submitted-team and actual-outcome reconciliation only",
        },
        "authority_split": {
            "historical_submitted_team": "GREEN_PUBLIC_OFFICIAL",
            "current_private_pre_deadline_draft": "OPTIONAL_AUTHENTICATED_MONITOR",
        },
        "snapshot_reuse": {
            "entry_history": True,
            "picks_reused": reused_picks,
            "picks_fetched": fetched_picks,
        },
        "source_health": health,
    }
    detail["historical_entry"] = historical
    atomic_json(DATA / "official_detail.json", detail)

    summary = latest.setdefault("official_detail_summary", {})
    summary.update({
        "historical_submitted_team_authority": "GREEN_PUBLIC_OFFICIAL",
        "historical_gameweeks_available": len(rows),
        "retrospective_proxy_gameweeks": available_proxy,
        "private_pre_deadline_draft_authority": "OPTIONAL_AUTHENTICATED_MONITOR",
        "history_core_snapshot_reused": True,
        "historical_picks_snapshot_reused": reused_picks,
        "historical_picks_network_fetched": fetched_picks,
    })
    latest["official_historical_authority"] = historical["authority_split"]
    atomic_json(DATA / "latest.json", latest)
    return historical


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
