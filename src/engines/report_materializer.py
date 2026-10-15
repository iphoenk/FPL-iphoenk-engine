from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.engines.gameweek_lifecycle_intelligence import build_gameweek_lifecycle
from src.engines.personal_gameweek_context import build_personal_gameweek_context
from src.engines.post_deadline_locked_team import (
    build_post_deadline_locked_team_view,
    deadline_passed_for_gw,
    reconcile_owned_match_events,
)
from src.utils import DATA, ROOT, atomic_json, read_json

REGISTRY_PATH = ROOT / "config" / "report_artifact_registry.json"
REGISTRY_RUNTIME_OUT = DATA / "report_artifact_registry.json"
BRIEF_OUT = DATA / "decision_brief.json"
DEEP_OUT = DATA / "deep_review_payload.json"
WATCH_OUT = DATA / "dss_watchlist_summary.json"
OWNED_DETAIL_OUT = DATA / "official_detail_owned.json"
WATCH_DETAIL_OUT = DATA / "official_detail_watchlist.json"
USER_OUT = DATA / "user_report.json"

_V6_HISTORY_CONTRACT = "OFFICIAL_DETAIL_FULL_SEASON_HISTORY_V1"


def _normalise_occurrence_slot(value: Any) -> str | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _read_json_or_gzip(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return {}
    gzip_path = Path(str(path) + ".gz")
    if gzip_path.is_file():
        try:
            return json.loads(gzip.decompress(gzip_path.read_bytes()).decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError, gzip.BadGzipFile):
            return {}
    return {}


def _load_occurrence_bound_official_detail(
    *, report_kind: str, logical_slot: str | None,
) -> dict[str, Any]:
    """Load V6 full-history only when it belongs to this exact report occurrence."""
    if report_kind != "full_master" or not logical_slot:
        return {}
    latest = read_json(DATA / "v6" / "report_prefetch" / "latest.json", {}) or {}
    if str(latest.get("report_kind") or "").strip() != "full_master":
        return {}
    requested_slot = _normalise_occurrence_slot(logical_slot)
    target_slot = _normalise_occurrence_slot(
        latest.get("target_logical_report_slot") or latest.get("logical_slot")
    )
    if not requested_slot or requested_slot != target_slot:
        return {}
    generated = _normalise_occurrence_slot(latest.get("generated_at"))
    if not generated:
        return {}
    root = DATA / "v6" / "history" / "official_detail.json"
    detail = _read_json_or_gzip(root)
    if str(detail.get("contract") or "") != _V6_HISTORY_CONTRACT:
        return {}
    if _normalise_occurrence_slot(detail.get("generated_at")) != generated:
        return {}
    full_history = detail.get("full_season_history")
    if not isinstance(full_history, dict):
        return {}
    return detail



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _contract() -> dict[str, Any]:
    return load_registry().get("consumer_contract") or {}


def _owned_rows(user: dict[str, Any], team: dict[str, Any], projections: dict[str, Any]) -> list[dict[str, Any]]:
    pmap = {int(x.get("element")): x for x in projections.get("players") or [] if x.get("element") is not None}
    user_map = {int(x.get("element")): x for x in ((user.get("owned_squad") or {}).get("facts") or []) if x.get("element") is not None}
    rows: list[dict[str, Any]] = []
    ledger = team.get("team_value_ledger") or []
    for owned in ledger:
        eid = int(owned.get("element") or -1)
        source = user_map.get(eid) or {}
        proj = pmap.get(eid) or {}
        xmins = proj.get("xmins") or {}
        now_cost = owned.get("now_cost")
        price = source.get("price")
        if price is None and now_cost is not None:
            price = round(_f(now_cost) / 10.0, 1)
        rows.append({
            "element": eid,
            "name": source.get("name") or owned.get("name") or proj.get("name"),
            "position": source.get("position") or owned.get("position") or proj.get("position"),
            "price": price,
            "status": source.get("status") or owned.get("status") or proj.get("status"),
            "xmins": source.get("xmins") if source.get("xmins") is not None else xmins.get("expected_minutes"),
            "start_probability": source.get("start_probability") if source.get("start_probability") is not None else xmins.get("start_probability"),
            "model_confidence": source.get("model_confidence") or proj.get("projection_confidence"),
        })
    expected = int(_contract().get("owned_count") or 15)
    if len(rows) != expected:
        raise RuntimeError(f"report materializer owned contract failed: {len(rows)} != {expected}")
    return rows


def _watch_row(row: dict[str, Any], *, deep: bool = False) -> dict[str, Any]:
    xmins = row.get("xmins") or {}
    horizons = row.get("horizons") or {}
    price_risk = row.get("price_risk") or {}
    base = {
        "element": row.get("element"),
        "rank": row.get("rank"),
        "lifecycle": row.get("lifecycle"),
        "name": row.get("name"),
        "team": row.get("team"),
        "position": row.get("position"),
        "price": row.get("price") if row.get("price") is not None else (round(_f(row.get("now_cost")) / 10.0, 1) if row.get("now_cost") is not None else None),
        "xmins": xmins.get("expected_minutes"),
        "start_probability": xmins.get("start_probability"),
        "xpts_5": (horizons.get("5") or {}).get("mean"),
        "confidence": row.get("projection_confidence"),
        "action": row.get("action") or "WATCH",
        "main_reason": ((row.get("reasons") or [None])[0]),
        "main_risk": ((row.get("risks") or [None])[0]),
        "price_risk": {
            "direction": price_risk.get("risk_direction"),
            "urgency": price_risk.get("urgency"),
            "progress_pct": price_risk.get("official_progress_pct"),
        },
    }
    if deep:
        base["horizons"] = {key: (horizons.get(key) or {}).get("mean") for key in ("3", "5", "10", "15")}
        base["reasons"] = list(row.get("reasons") or [])[:3]
        base["risks"] = list(row.get("risks") or [])[:3]
        replacement = row.get("direct_replacement_context") or {}
        base["direct_replacement"] = {"owned_name": replacement.get("owned_name"), "candidate_h5_delta": replacement.get("candidate_h5_delta")}
        base["dss_score"] = row.get("dss_score")
        base["evidence_coverage"] = row.get("evidence_coverage")
    return base


def _watchlist_summary(watchlist: dict[str, Any], *, deep: bool = False) -> dict[str, Any]:
    contract = _contract()
    positions = list(contract.get("watchlist_positions") or ["GK", "DEF", "MID", "FWD"])
    target_per = int(contract.get("watchlist_per_position") or 5)
    target_total = int(contract.get("watchlist_total") or 20)
    team = read_json(DATA / "team.json", {})
    owned_ids = {int(row["element"]) for row in team.get("team_value_ledger") or [] if row.get("element") is not None}
    result: dict[str, list[dict[str, Any]]] = {}
    published: list[int] = []
    for position in positions:
        rows = list((watchlist.get("positions") or {}).get(position) or [])
        if len(rows) != target_per:
            raise RuntimeError(f"report materializer watchlist {position} contract failed: {len(rows)} != {target_per}")
        compact = [_watch_row(row, deep=deep) for row in rows]
        for row in compact:
            eid = int(row.get("element") or -1)
            if eid in owned_ids:
                raise RuntimeError(f"owned player leaked into watchlist: {eid}")
            published.append(eid)
        result[position] = compact
    if len(published) != target_total or len(set(published)) != target_total:
        raise RuntimeError(f"report materializer watchlist total contract failed: {len(published)} != {target_total}")
    return {"status": watchlist.get("status"), "screening_contract": watchlist.get("screening_contract"), "count": len(published), "per_position": target_per, "positions": result}


def _finance(team: dict[str, Any]) -> dict[str, Any]:
    totals = team.get("totals") if isinstance(team.get("totals"), dict) else {}
    market = totals.get("market_value", team.get("market_value"))
    sell = totals.get("sell_value", team.get("sell_value"))
    itb = totals.get("itb", team.get("itb"))
    if market is None:
        market = sum(int(x.get("now_cost") or 0) for x in team.get("team_value_ledger") or [])
    if sell is None:
        sell = sum(int(x.get("sell_cost") or 0) for x in team.get("team_value_ledger") or [])
    if itb is None:
        itb = 0
    return {
        "squad_market_value": round(_f(market) / 10.0, 1),
        "itb": round(_f(itb) / 10.0, 1),
        "total_team_value": round((_f(market) + _f(itb)) / 10.0, 1),
        "squad_sell_value": round(_f(sell) / 10.0, 1),
        "spendable_value": round((_f(sell) + _f(itb)) / 10.0, 1),
    }


def _compact_battle(user: dict[str, Any]) -> dict[str, Any]:
    section = user.get("starting_xi") or {}
    battle = ((section.get("model") or {}).get("battle") or {})
    return {
        "formation": (section.get("facts") or {}).get("formation"),
        "decision": section.get("decision"),
        "confidence": (section.get("model") or {}).get("confidence"),
        "starter": battle.get("starter"),
        "challenger": battle.get("challenger"),
        "margin": battle.get("margin"),
        "main_reasons": battle.get("main_reasons") or [],
        "leader_metrics": battle.get("leader_metrics") or {},
        "challenger_metrics": battle.get("challenger_metrics") or {},
    }


def _captain(user: dict[str, Any], *, deep: bool = False) -> dict[str, Any]:
    section = user.get("captaincy") or {}
    model = section.get("model") or {}
    captain = model.get("captain") or {}
    vice = model.get("vice") or {}
    out = {
        "decision": section.get("decision"),
        "confidence": section.get("confidence"),
        "captain": captain.get("name") or (section.get("facts") or {}).get("model_candidate"),
        "vice": vice.get("name") or (section.get("facts") or {}).get("vice_candidate"),
        "reason": section.get("reason"),
    }
    if deep:
        out["captain_model"] = captain
        out["vice_model"] = vice
        out["checks"] = model.get("checks") or {}
        out["candidate_margin"] = model.get("candidate_margin")
    return out


def _price(user: dict[str, Any]) -> dict[str, Any]:
    section = user.get("price_radar") or {}
    keys = ("element", "name", "price", "official_price", "official_ownership", "direction", "urgency", "progress_pct", "predicted_change_at", "eta_human", "confidence", "action")

    def compact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{key: row.get(key) for key in keys if row.get(key) is not None} for row in rows]

    return {
        "decision": section.get("decision"),
        "owned": compact(list(section.get("owned") or [])),
        "mandatory_high_value_challengers": compact(list(section.get("mandatory_high_value_challengers") or [])),
        "external_watchlist": compact(list(section.get("external_watchlist") or [])),
    }


def _player_ref(raw: Any) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    return {
        key: row.get(key)
        for key in ("element", "name", "team", "position", "xpts", "pick_position", "multiplier")
        if row.get(key) is not None
    }


def _compact_planning(raw: Any) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    recommendation = dict(row.get("engine_recommendation") or {})
    comparison = dict(row.get("comparison") or {})
    return {
        "status": row.get("status"),
        "gw": row.get("gw"),
        "decision_authority": row.get("decision_authority"),
        "source": row.get("source"),
        "formation": row.get("formation"),
        "active_chip": row.get("active_chip"),
        "starting_xi": [_player_ref(item) for item in row.get("starting_xi") or []],
        "bench": [_player_ref(item) for item in row.get("bench") or []],
        "captain": _player_ref(row.get("captain")),
        "vice_captain": _player_ref(row.get("vice_captain")),
        "xi_xpts": row.get("xi_xpts"),
        "bench_xpts": row.get("bench_xpts"),
        "estimated_points": row.get("estimated_points"),
        "user_override_active": bool(row.get("user_override_active")),
        "engine_recommendation": {
            key: recommendation.get(key)
            for key in ("formation", "captain", "vice_captain", "active_chip", "estimated_points")
            if recommendation.get(key) is not None
        },
        "comparison": {
            key: comparison.get(key)
            for key in ("user_minus_engine_estimated_points", "formation_changed", "captain_changed", "vice_changed", "chip_changed")
            if comparison.get(key) is not None
        },
    }


def _compact_historical(raw: Any) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    return {
        "gw": row.get("gw"),
        "status": row.get("status"),
        "authority": row.get("authority"),
        "actual_points": row.get("actual_points"),
        "transfer_cost": row.get("transfer_cost"),
        "points_on_bench": row.get("points_on_bench"),
        "overall_rank": row.get("overall_rank"),
        "event_rank": row.get("event_rank"),
        "chip": row.get("chip"),
        "formation": row.get("formation"),
        "captain": _player_ref(row.get("captain")),
        "vice_captain": _player_ref(row.get("vice_captain")),
    }


def _compact_gameweek_context(payload: dict[str, Any]) -> dict[str, Any]:
    historical = list(payload.get("historical") or [])
    return {
        "schema": payload.get("schema"),
        "historical": [_compact_historical(row) for row in historical[-2:]],
        "planning": _compact_planning(payload.get("planning")),
        "detail_ref": "data/deep_review_payload.json#gameweek_context",
        "fast_surface_compacted": True,
    }


def _compact_transition(raw: Any) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    ins = [_player_ref(item) for item in row.get("ins") or []]
    outs = [_player_ref(item) for item in row.get("outs") or []]
    return {
        "from_gw": row.get("from_gw"),
        "to_gw": row.get("to_gw"),
        "kept_count": len(row.get("kept") or []),
        "ins": ins,
        "outs": outs,
    }


def _compact_current_gw(raw: Any) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    return {
        key: row.get(key)
        for key in ("gw", "status", "gross_points", "hit", "net_points")
        if row.get(key) is not None
    }


def _compact_counterfactual(raw: Any) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    current = dict(row.get("current_squad") or {})
    old = dict(row.get("old_squad_counterfactual") or {})
    return {
        "status": row.get("status"),
        "policy": row.get("policy"),
        "current_squad": {key: current.get(key) for key in ("gw", "status", "gross_points", "hit", "net_points") if current.get(key) is not None},
        "old_squad_counterfactual": {key: old.get(key) for key in ("status", "points", "hit", "net_points") if old.get(key) is not None},
        "realized_or_live_pnl": row.get("realized_or_live_pnl"),
        "verdict": row.get("verdict"),
    }


def _compact_learning(raw: Any) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    validation = dict(row.get("decision_validation") or {})
    return {
        "status": row.get("status"),
        "sample_size": row.get("sample_size"),
        "points_mae": row.get("points_mae"),
        "xmins_mae": row.get("xmins_mae"),
        "decision_validation": {
            key: {
                "status": (value or {}).get("status"),
                "sample_size": (value or {}).get("sample_size"),
                "mean": (value or {}).get("mean"),
            }
            for key, value in validation.items()
            if isinstance(value, dict)
        },
    }


def _compact_gameweek_lifecycle(payload: dict[str, Any]) -> dict[str, Any]:
    previous = dict(payload.get("previous_gw") or {})
    authenticated = dict(payload.get("authenticated_official") or {})
    calibration = dict(payload.get("price_calibration") or {})
    return {
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "previous_gw": _compact_historical(previous),
        "transition": _compact_transition(payload.get("transition")),
        "current_gw": _compact_current_gw(payload.get("current_gw")),
        "counterfactual_pnl": _compact_counterfactual(payload.get("counterfactual_pnl")),
        "learning": _compact_learning(payload.get("learning")),
        "authenticated_official": {
            key: authenticated.get(key)
            for key in ("health", "state", "verified_entry", "chip_state_available", "transfers_latest_available", "exact_finance_coverage_complete", "authority_upgrade_allowed")
            if authenticated.get(key) is not None
        },
        "price_calibration": {
            key: calibration.get(key)
            for key in ("status", "actionability", "direction_samples", "direction_accuracy", "timing_samples", "price_alone_can_trigger_transfer")
            if calibration.get(key) is not None
        },
        "next_gw": _compact_planning(payload.get("next_gw")),
        "detail_ref": "data/deep_review_payload.json#gameweek_lifecycle",
        "fast_surface_compacted": True,
    }


def _official_partition(full: dict[str, Any], ids: set[int]) -> dict[str, Any]:
    summaries = full.get("element_summaries") or {}
    selected = {}
    for eid in sorted(ids):
        source = summaries.get(str(eid))
        if not isinstance(source, dict):
            continue
        selected[str(eid)] = {
            "fixtures": list(source.get("fixtures") or [])[:5],
            "history": list(source.get("history") or [])[-5:],
            "history_past": source.get("history_past") or [],
        }
    return {
        "generated_at": full.get("generated_at"),
        "requested_ids": sorted(ids),
        "available_count": len(selected),
        "element_summaries": selected,
        "set_piece_notes": full.get("set_piece_notes"),
        "source": "data/official_detail.json",
        "lazy_load": True,
    }


def _post_deadline_personal_match_context(
    current_team: dict[str, Any],
    official_snapshot: dict[str, Any],
    live: dict[str, Any],
) -> dict[str, Any]:
    target_gw = int(current_team.get("gw") or live.get("scoring_gw") or 0)
    if not current_team or target_gw <= 0:
        return {"status": "UNAVAILABLE", "reason": "authenticated_current_team_missing"}
    if not deadline_passed_for_gw(official_snapshot, target_gw):
        return {"status": "PRE_DEADLINE", "gw": target_gw}
    volatile_status = str(
        live.get("freshness_status")
        or live.get("status")
        or "UNKNOWN"
    )
    try:
        locked = build_post_deadline_locked_team_view(
            current_team,
            target_gw=target_gw,
            deadline_passed=True,
            volatile_scope_status=volatile_status,
        )
        reconciliation = reconcile_owned_match_events(
            locked,
            list(live.get("players") or []),
        )
    except RuntimeError as exc:
        return {
            "status": "PARTIAL",
            "gw": target_gw,
            "reason": str(exc),
            "fail_operational": True,
        }
    return {
        "status": "PASS" if reconciliation.get("status") == "PASS" else "PARTIAL",
        "gw": target_gw,
        "locked_team": locked,
        "owned_match_reconciliation": reconciliation,
        "fail_operational": True,
    }


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _enforce_sizes() -> dict[str, int]:
    artifacts = load_registry().get("artifacts") or {}
    sizes = {}
    for name, spec in artifacts.items():
        raw_path = str(spec.get("path") or "")
        if not raw_path.startswith("data/"):
            continue
        path = DATA / raw_path.removeprefix("data/")
        if not path.exists():
            continue
        size = _size(path)
        sizes[name] = size
        limit = spec.get("max_bytes")
        if limit is not None and spec.get("priority") == "P0" and size > int(limit):
            raise RuntimeError(f"P0 report serving artifact too large: {name} {size}>{limit}")
    return sizes


def _full_season_history_acceptance(official: dict[str, Any], planning_gw: Any) -> dict[str, Any]:
    """Expose the canonical full-history gate without copying player rows."""
    raw = official.get("full_season_history") or {}
    if not raw:
        historical = official.get("historical_entry") or {}
        raw = historical.get("full_season_history") or {}
    gate = dict(raw.get("coverage_gate") or {})
    as_of = dict(raw.get("as_of") or {})
    universe = dict(raw.get("universe") or {})
    expected_gw = as_of.get("historical_gws")
    status = str(gate.get("status") or "UNAVAILABLE").upper()
    if status not in {"PASS", "PARTIAL"}:
        status = "UNAVAILABLE"
    # V12 planning GW7 requires finalized GW1..GW6, not a nominally complete
    # V6 GW1..GW5 artifact with source planning GW6. Preserve source identity.
    try:
        required_planning_gw = int(planning_gw)
        source_planning_gw = int(as_of.get("planning_gw"))
    except (TypeError, ValueError):
        required_planning_gw = source_planning_gw = 0
    historical_slots_match = (
        required_planning_gw >= 2
        and source_planning_gw == required_planning_gw
        and isinstance(expected_gw, list)
        and expected_gw == list(range(1, required_planning_gw))
    )
    fixture_identity_status = str(gate.get("fixture_identity_status") or "UNVERIFIED")
    historical_finality = gate.get("all_historical_gws_finalized") is True
    rejection_reasons = []
    if not historical_slots_match:
        rejection_reasons.append("PLANNING_GW_HISTORY_RANGE_MISMATCH")
    if not historical_finality:
        rejection_reasons.append("HISTORICAL_GW_NOT_FINALIZED")
    if fixture_identity_status != "PASS":
        rejection_reasons.append("OFFICIAL_FIXTURE_IDENTITY_UNVERIFIED")
    if status == "PASS" and rejection_reasons:
        status = "PARTIAL"
    return {
        "contract": raw.get("contract") or "OFFICIAL_FULL_SEASON_PLAYER_HISTORY_V1",
        "status": status,
        "planning_gw": as_of.get("planning_gw", planning_gw),
        "required_planning_gw": required_planning_gw,
        "source_planning_gw": source_planning_gw,
        "historical_range_matches_target": historical_slots_match,
        "fixture_identity_status": fixture_identity_status,
        "all_historical_gws_finalized": historical_finality,
        "coverage_rejection_reasons": rejection_reasons,
        "historical_gws": expected_gw or [],
        "historical_range": (
            f"GW1-GW{max(expected_gw)}" if isinstance(expected_gw, list) and expected_gw
            else "UNAVAILABLE"
        ),
        "expected_gw_slots": len(expected_gw) if isinstance(expected_gw, list) else gate.get("expected_gw_slots"),
        "available_gw_slots": gate.get("available_gw_slots"),
        "expected_player_slots": gate.get("expected_player_slots"),
        "missing_records": gate.get("missing_records") or [],
        "expected_players": universe.get("expected_players"),
        "covered_players": universe.get("covered_players"),
        "coverage_ratio": universe.get("coverage_ratio"),
        "pending_never_coerced_to_zero": gate.get("pending_never_coerced_to_zero") is True,
        "dnp_and_blank_distinguished": gate.get("dnp_and_blank_distinguished") is True,
        "double_gameweeks_aggregate_fixture_rows": gate.get("double_gameweeks_aggregate_fixture_rows") is True,
        "provenance": dict(raw.get("provenance") or {}),
        "production_evidence": "OFFICIAL_DETAIL_FULL_SEASON_HISTORY",
    }


def _bound_retrospective_context(
    *, original_official: dict[str, Any], logical_slot: str | None,
    report_kind: str,
) -> dict[str, Any]:
    """Read-only V6 source-to-DEEP bridge, never a P(start) mathematical owner.

    Accept the original lossless player-history archive only when it matches
    the same original prefetch occurrence already verified by the sidecar.
    External normalized sources remain strictly cutoff-gated by the existing
    GW1-GW6 context builder. Return no contextual rows on identity mismatch.
    """
    if report_kind != "full_master" or not _normalise_occurrence_slot(logical_slot):
        return {}
    if original_official.get("contract") != _V6_HISTORY_CONTRACT:
        return {}
    archive_path = DATA / "v6/history/official_detail.json.gz"
    if not archive_path.is_file():
        return {}
    try:
        archive = json.loads(gzip.decompress(archive_path.read_bytes()).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, gzip.BadGzipFile):
        return {}
    expected_slot = _normalise_occurrence_slot(logical_slot)
    if (archive.get("contract") != _V6_HISTORY_CONTRACT
            or archive.get("generated_at") != original_official.get("generated_at")
            or _normalise_occurrence_slot(archive.get("target_logical_report_slot")) != expected_slot
            or _normalise_occurrence_slot(original_official.get("target_logical_report_slot")) != expected_slot
            or archive.get("report_prefetch_run_id") != original_official.get("report_prefetch_run_id")):
        return {}
    raw_history = archive.get("full_season_history") or {}
    players = raw_history.get("players") or {}
    if (raw_history.get("contract") != "OFFICIAL_FULL_SEASON_PLAYER_HISTORY_V1"
            or not isinstance(players, dict) or not players):
        return {}

    from src.engines.v12_gw1_gw6_history_context import build_retrospective_context

    # Use archived player identity/team/position as official authority. Names
    # from a newer canonical roster may only be used when it predates cutoff.
    canonical_players = read_json(DATA / "v6/normalized/canonical_players.json", {}) or {}
    canonical_fixtures = read_json(DATA / "v6/normalized/canonical_fixtures.json", {}) or {}

    def asof_admitted(payload: dict[str, Any]) -> bool:
        effective = _normalise_occurrence_slot(payload.get("effective_at"))
        source_cutoff = _normalise_occurrence_slot(original_official.get("generated_at"))
        return bool(effective and source_cutoff and effective <= source_cutoff)

    names: dict[int, str] = {}
    if asof_admitted(canonical_players):
        for row in canonical_players.get("players") or []:
            if not isinstance(row, dict):
                continue
            try:
                element = int(row.get("official_fpl_element_id"))
            except (TypeError, ValueError):
                continue
            if row.get("web_name"):
                names[element] = str(row["web_name"])
    elements: list[dict[str, Any]] = []
    for key, row in players.items():
        if not isinstance(row, dict):
            continue
        try:
            eid = int(key)
            team = int(row.get("team"))
            position = int(row.get("position"))
        except (TypeError, ValueError):
            continue
        if eid > 0 and team > 0 and position in (1, 2, 3, 4):
            elements.append({
                "id": eid, "team": team, "element_type": position,
                "web_name": names.get(eid, f"FPL #{eid}"),
            })
    if len(elements) != len(players):
        return {}
    fixture_rows = []
    if asof_admitted(canonical_fixtures):
        for row in canonical_fixtures.get("fixtures") or []:
            if not isinstance(row, dict):
                continue
            fixture_rows.append({
                "id": row.get("official_fpl_fixture_id"),
                "event": row.get("event"), "team_h": row.get("team_h"),
                "team_a": row.get("team_a"), "finished": row.get("finished"),
            })
    try:
        context = build_retrospective_context(
            bootstrap={"elements": elements},
            official_fixtures=fixture_rows,
            full_history=raw_history,
            understat=read_json(DATA / "v6/normalized/sources/understat.json", {}) or {},
            fotmob=read_json(DATA / "v6/normalized/sources/fotmob.json", {}) or {},
            report_slot=str(logical_slot),
            observation_cutoff_at=original_official.get("generated_at"),
            focus_player_ids=(154, 40, 165),
        )
    except (TypeError, ValueError, KeyError):
        return {}
    # Keep full player rows inside V6; compact DEEP only carries summaries and
    # audited focus players, preserving the 22-section report size budget.
    context.pop("players", None)
    # Full-universe fixture ledger is materialized only in the verified builder;
    # mobile DEEP carries compact coverage + explicitly scoped focus-player rows.
    ledger = context.pop("verified_context_ledger", {})
    context["verified_context_coverage"] = {
        key: ledger.get(key) for key in (
            "contract", "observation_class", "row_count", "admission_counts",
            "by_club", "by_position", "unresolved_player_count",
            "historical_predeadline_source_asof", "numeric_pstart_effect",
        )
    }
    context["focus_verified_context_rows"] = [
        row for row in ledger.get("rows") or []
        if row.get("element_id") in {154, 40, 165}
    ]
    context["binding"] = {
        "source": "V6_EXACT_OCCURRENCE_LOSSLESS_HISTORY",
        "prefetch_run_id": archive.get("report_prefetch_run_id"),
        "original_generated_at": archive.get("generated_at"),
        "original_logical_slot": archive.get("target_logical_report_slot"),
        "external_advisory_only": True,
        "historical_predeadline_lineage_admitted": False,
        "forecast_or_pstart_changed": False,
    }
    return context



def _bind_current15_official_context_shadow(
    rows: list[dict[str, Any]],
    projections: dict[str, Any] | None,
    official_v6: dict[str, Any] | None,
    *,
    occurrence_bound: bool,
    retrospective: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Repair report-only context observability from verified current V6 facts.

    This never adds a numeric model signal or changes P(start), xMins or GW7
    frozen forecasts. An unbound, missing or conflicting source fails closed.
    """
    summary: dict[str, Any] = {
        "contract": "V12_CURRENT15_BOUND_SOURCE_SHADOW_V1",
        "status": "UNAVAILABLE",
        "official_status_observed": 0,
        "advisory_role_profiles": 0,
        "retrospective_verified_manager_history": 0,
        "calibrated_role_manager_rows": 0,
        "prospective_manager_effect_verified": False,
        "numeric_model_mutation": False,
        "retrospective_is_not_predeadline": True,
        "source": "V6_OFFICIAL_FPL_CURRENT_EXACT_OCCURRENCE",
    }
    if not occurrence_bound or not isinstance(projections, dict) or not isinstance(official_v6, dict):
        summary["reason"] = "OCCURRENCE_OR_SOURCE_NOT_VERIFIED"
        return rows, summary
    if official_v6.get("source_id") != "official_fpl":
        summary["reason"] = "SOURCE_AUTHORITY_MISMATCH"
        return rows, summary
    bootstrap = (official_v6.get("data") or {}).get("bootstrap") or {}
    if (not isinstance(bootstrap, dict) or bootstrap.get("status") != "AVAILABLE"
            or not isinstance(bootstrap.get("json"), dict)
            or not isinstance(bootstrap.get("sha256"), str)
            or len(bootstrap["sha256"]) != 64):
        summary["reason"] = "OFFICIAL_BOOTSTRAP_SNAPSHOT_UNAVAILABLE"
        return rows, summary
    official_rows = bootstrap["json"].get("elements")
    projected_rows = projections.get("players")
    if not isinstance(official_rows, list) or not isinstance(projected_rows, list):
        summary["reason"] = "PLAYER_UNIVERSE_UNAVAILABLE"
        return rows, summary
    try:
        official = {int(x["id"]): x for x in official_rows if isinstance(x, dict)}
        predicted = {int(x["element"]): x for x in projected_rows if isinstance(x, dict)}
        elements = [int(x["element"]) for x in rows]
    except (KeyError, ValueError, TypeError):
        summary["reason"] = "PLAYER_ID_INVALID"
        return rows, summary
    if (len(rows) != 15 or len(set(elements)) != 15
            or len(official) != len(official_rows)
            or len(predicted) != len(projected_rows)
            or set(elements) - set(official) or set(elements) - set(predicted)):
        summary["reason"] = "CURRENT15_OR_UNIVERSE_IDENTITY_MISMATCH"
        return rows, summary
    from src.models.v12_pstart_context_evidence import build_pstart_context_observability
    valid_status = {"a", "d", "i", "s", "u"}
    bound = []
    for raw, eid in zip(rows, elements):
        player = official[eid]
        projection = predicted[eid]
        status = str(player.get("status") or "").lower()
        if status not in valid_status or int(projection.get("team") or player.get("team") or 0) != int(player.get("team") or 0):
            summary["reason"] = "CURRENT_PLAYER_STATUS_OR_TEAM_UNVERIFIED"
            return rows, summary
        xmins = projection.get("xmins") or {}
        evidence = raw.get("p_start_evidence") or {}
        context = build_pstart_context_observability(
            {**projection, "status": status},
            xmins if isinstance(xmins, dict) else {},
            evidence if isinstance(evidence, dict) else None,
        )
        context["readiness"]["status_binding"] = "CURRENT_GOVERNED_V6_BOOTSTRAP"
        context["readiness"]["numeric_model_mutation"] = False
        patched = dict(raw)
        patched["pstart_context_evidence"] = context
        bound.append(patched)
    # Past matches may verify a manager timeline, but do not establish who
    # will manage the next fixture or quantify the manager's P(start) effect.
    historical_clubs = (
        ((retrospective or {}).get("all_clubs_tactical_coverage") or {}).get("clubs") or []
    )
    historically_observed_teams = set()
    for club in historical_clubs:
        if not isinstance(club, dict):
            continue
        try:
            tid = int(club.get("team_id"))
        except (ValueError, TypeError):
            continue
        if any(
            isinstance(record, dict)
            and record.get("manager_native_id") is not None
            and isinstance(record.get("source_snapshot_sha256"), str)
            and len(record["source_snapshot_sha256"]) == 64
            for record in club.get("timeline") or []
        ):
            historically_observed_teams.add(tid)
    summary["retrospective_verified_manager_history"] = sum(
        int(official[eid].get("team") or 0) in historically_observed_teams
        for eid in elements
    )
    summary["status"] = "OBSERVABILITY_BOUND_ADVISORY_ONLY"
    summary["reason"] = None
    summary["official_status_observed"] = sum(
        x["pstart_context_evidence"]["availability"]["official_status_observed"]
        for x in bound
    )
    summary["advisory_role_profiles"] = sum(
        x["pstart_context_evidence"]["role"]["status"] == "PROFILE_ADVISORY_UNCALIBRATED"
        for x in bound
    )
    summary["official_bootstrap_original_sha256"] = bootstrap["sha256"]
    return bound, summary


def _analytics_acceptance(*, user: dict[str, Any], full_history: dict[str, Any], projections: dict[str, Any] | None = None, official_v6: dict[str, Any] | None = None, occurrence_bound: bool = False) -> dict[str, Any]:
    captaincy = dict(user.get("captaincy") or {})
    source_rows = user.get("rows") or []
    pstart_rows = [
        row for row in source_rows
        if isinstance(row, dict)
        and next((value for value in (
            row.get("p_start"), row.get("start_probability"), row.get("pstart")
        ) if value is not None), None) is not None
    ]
    pstart_rows, context_shadow = _bind_current15_official_context_shadow(
        pstart_rows, projections, official_v6, occurrence_bound=occurrence_bound,
        retrospective=(full_history.get("retrospective_context") or {}),
    )
    pstart_evidence = [
        row for row in pstart_rows
        if any(isinstance(row.get(key), dict) for key in (
            "p_start_evidence", "start_probability_evidence"
        ))
    ]
    frontier = captaincy.get("captain_frontier") or []
    pstart_status = "PASS" if len(pstart_rows) == 15 and len(pstart_evidence) == len(pstart_rows) else "PARTIAL"
    individual_evidence = [
        row for row in pstart_evidence
        if "player_selection_posterior" in {
            str(signal) for signal in (row.get("p_start_evidence") or {}).get("signals") or []
        }
    ]
    historical_coverage = dict(user.get("historical_coverage") or {})
    historical_status = (
        "PASS" if historical_coverage.get("range") == "GW1-GW6"
        and historical_coverage.get("all_finalized") is True else "PARTIAL"
    )
    calibration_status = str(user.get("calibration_status") or "NO_SETTLED_SAMPLE").upper()
    from src.engines.v12_pstart_resolution import assess_pstart_resolution
    diagnostic = dict(user.get("pstart_walk_forward_diagnostic") or {})
    calibration_status = str(diagnostic.get("status") or calibration_status).upper()
    audit = assess_pstart_resolution(
        pstart_rows, calibration_status=calibration_status
    )
    resolution = audit["status"]
    captain_state = str(captaincy.get("captain_state") or "UNAVAILABLE").upper()
    return {
        "contract": "V12_ANALYTICS_PRODUCTION_ACCEPTANCE_V1",
        "p_start": {
            "evidence_status": pstart_status,
            "resolution_status": resolution,
            "resolution_audit": audit,
            "source_context_shadow": context_shadow,
            "calibration_diagnostic": diagnostic,
            "rows_with_probability": len(pstart_rows),
            "rows_with_evidence": len(pstart_evidence),
            "formula_owner": "V12_PLAYER_MINUTES",
            "probability_recomputed_in_materializer": False,
            "acceptance_layers": {
                "EVIDENCE_BINDING": pstart_status,
                "HISTORICAL_COVERAGE": historical_status,
                "INDIVIDUAL_EVIDENCE": "PASS" if len(individual_evidence) == len(pstart_rows) else "PARTIAL",
                "MODEL_RESOLUTION": resolution,
                "CALIBRATION": calibration_status,
                "TEMPORAL_INTEGRITY": "FAIL" if user.get("future_leakage") is True else "PASS",
                "PRODUCTION_VERIFICATION": str(user.get("production_verification") or "PENDING_CONTROLLED_RUN"),
            },
            "individual_evidence_rows": len(individual_evidence),
            "individual_evidence_missing_rows": max(0, len(pstart_rows) - len(individual_evidence)),
        },
        "s08_captain": {
            "evidence_status": "PASS" if isinstance(frontier, list) and frontier and captain_state in {"LOCK", "PREPARE"} else "PARTIAL",
            "decision_state": captain_state,
            "frontier_count": len(frontier) if isinstance(frontier, list) else 0,
            "lock_requires_all_calibrated_layers": True,
            "prepare_is_not_executable": captain_state != "LOCK",
        },
        "full_history": {
            "evidence_status": "PASS" if full_history.get("status") == "PASS" else full_history.get("status", "UNAVAILABLE"),
            "coverage_gate": full_history.get("status", "UNAVAILABLE"),
            "planning_gw": full_history.get("planning_gw"),
            "historical_range": full_history.get("historical_range"),
            "covered_players": full_history.get("covered_players"),
            "expected_players": full_history.get("expected_players"),
        },
    }


def run() -> dict[str, Any]:
    user = read_json(USER_OUT, {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    team = read_json(DATA / "team.json", {})
    projections = read_json(DATA / "projections.json", {})
    lineup = read_json(DATA / "lineup_decision.json", {})
    latest = read_json(DATA / "latest.json", {})
    v6_prefetch_latest = read_json(
        DATA / "v6" / "report_prefetch" / "latest.json", {}
    )
    logical_slot = (
        user.get("logical_slot")
        or user.get("report_slot")
        or v6_prefetch_latest.get("target_logical_report_slot")
        or v6_prefetch_latest.get("logical_slot")
        or latest.get("target_logical_report_slot")
        or latest.get("logical_slot")
    )
    requested_report_kind = str(user.get("report_kind") or "").strip()
    if not requested_report_kind:
        requested_report_kind = {
            "DEEP": "full_master",
            "MATCH": "match_mode",
            "PRICE": "price",
        }.get(str(user.get("report_mode") or "").strip().upper(), "full_master")
    legacy_official = read_json(DATA / "official_detail.json", {})
    occurrence_official = _load_occurrence_bound_official_detail(
        report_kind=requested_report_kind,
        logical_slot=logical_slot,
    )
    official = dict(legacy_official)
    if occurrence_official:
        official.update(occurrence_official)
    else:
        # Never let a stale legacy history artifact claim current production
        # full-history evidence when the exact V6 occurrence is not bound.
        official["full_season_history"] = {}
    official_snapshot = read_json(DATA / "official_snapshot.json", {})
    live = read_json(DATA / "live.json", {})
    prediction_accuracy = read_json(DATA / "prediction_accuracy.json", {})
    auth = read_json(DATA / "auth.json", {})
    current_team = read_json(DATA / "v6" / "personal" / "current_team.json", {})
    full_season_history = _full_season_history_acceptance(official, user.get("planning_gw"))
    if occurrence_official:
        retrospective = _bound_retrospective_context(
            original_official=occurrence_official, logical_slot=logical_slot,
            report_kind=requested_report_kind,
        )
        if retrospective:
            full_season_history["retrospective_context"] = retrospective
    analytics_acceptance = _analytics_acceptance(
        user=user, full_history=full_season_history, projections=projections,
        official_v6=(
            read_json(DATA / "v6" / "current" / "official_fpl.json", {})
            if occurrence_official else {}
        ),
        occurrence_bound=bool(occurrence_official),
    )

    owned = _owned_rows(user, team, projections)
    watch_summary = _watchlist_summary(watchlist, deep=False)
    watch_deep = _watchlist_summary(watchlist, deep=True)
    gameweek_context = build_personal_gameweek_context(team, projections, lineup, official, official_snapshot)
    gameweek_lifecycle = build_gameweek_lifecycle(
        gameweek_context=gameweek_context,
        team=team,
        live=live,
        official_snapshot=official_snapshot,
        prediction_accuracy=prediction_accuracy,
        auth=auth,
        price_model_health=latest.get("price_model_health") or {},
    )
    personal_match_context = _post_deadline_personal_match_context(
        current_team,
        official_snapshot,
        live,
    )
    serving_contract = {
        "owned": len(owned),
        "watchlist": watch_summary["count"],
        "watchlist_per_position": watch_summary["per_position"],
        "personal_gameweek_context": True,
        "gameweek_lifecycle": True,
        "counterfactual_pnl": True,
        "actual_vs_predicted_learning": True,
        "authenticated_official_readiness": True,
        "post_deadline_locked_team_view": personal_match_context.get("status"),
        "price_calibration_readiness": True,
        "fast_context_compacted": True,
        "deep_context_full_fidelity": True,
        "full_season_history": full_season_history,
        "analytics_acceptance": analytics_acceptance,
    }

    user.setdefault("owned_squad", {})["count"] = len(owned)
    user["owned_squad"]["facts"] = owned
    user["owned_squad"]["compact_summary"] = None
    user["external_watchlist"] = {"status": watch_summary["status"], "decision": "WATCH", "count": watch_summary["count"], "positions": watch_summary["positions"]}
    user["gameweek_context"] = gameweek_context
    user["gameweek_lifecycle"] = gameweek_lifecycle
    user["personal_match_context"] = personal_match_context
    user["serving_contract"] = serving_contract
    atomic_json(USER_OUT, user)

    brief = {
        "decision": user.get("decision"),
        "generated_at": _now(),
        "planning_gw": user.get("planning_gw"),
        "serving_contract": serving_contract,
        "gameweek_context": _compact_gameweek_context(gameweek_context),
        "gameweek_lifecycle": _compact_gameweek_lifecycle(gameweek_lifecycle),
        "personal_match_context": personal_match_context,
        "finance": _finance(team),
        "owned_15": owned,
        "changes_since_last_report": user.get("changes_since_last_report"),
        "main_starting_xi_battle": _compact_battle(user),
        "captaincy": _captain(user, deep=False),
        "chip": user.get("chip"),
        "price_radar": _price(user),
        "watchlist_20": watch_summary["positions"],
        "report_time_intelligence": user.get("report_time_intelligence") or {},
        "engine": user.get("engine_line"),
        "action_board": user.get("action_board") or [],
        "full_season_history": full_season_history,
        "analytics_acceptance": analytics_acceptance,
    }
    deep = {
        **brief,
        "payload_type": "DEEP_REVIEW_PAYLOAD_V2",
        "gameweek_context": gameweek_context,
        "gameweek_lifecycle": gameweek_lifecycle,
        "personal_match_context": personal_match_context,
        "watchlist_20": watch_deep["positions"],
        "captaincy": _captain(user, deep=True),
        "full_season_history": full_season_history,
        "analytics_acceptance": analytics_acceptance,
        "starting_xi": user.get("starting_xi"),
        "horizon_policy": user.get("horizon_policy"),
        "report_mode": user.get("report_mode"),
        "technical_refs": {
            "appendix": "data/technical_appendix.json",
            "full_watchlist": "data/dss_watchlist.json",
            "official_detail_full": "data/official_detail.json",
            "official_detail_owned": "data/official_detail_owned.json",
            "official_detail_watchlist": "data/official_detail_watchlist.json",
            "prediction_accuracy": "data/prediction_accuracy.json",
            "authenticated_official": "data/auth.json",
            "authenticated_current_team": "data/v6/personal/current_team.json",
            "price_model_health": "data/latest.json#price_model_health",
        },
    }
    atomic_json(WATCH_OUT, watch_summary)
    atomic_json(BRIEF_OUT, brief)
    atomic_json(DEEP_OUT, deep)

    owned_ids = {int(x["element"]) for x in owned}
    watch_ids = {int(x["element"]) for rows in watch_summary["positions"].values() for x in rows}
    atomic_json(OWNED_DETAIL_OUT, _official_partition(official, owned_ids))
    atomic_json(WATCH_DETAIL_OUT, _official_partition(official, watch_ids))
    atomic_json(REGISTRY_RUNTIME_OUT, load_registry())

    latest.setdefault("files", {}).update({
        "decision_brief": "data/decision_brief.json",
        "deep_review_payload": "data/deep_review_payload.json",
        "dss_watchlist_summary": "data/dss_watchlist_summary.json",
        "official_detail_owned": "data/official_detail_owned.json",
        "official_detail_watchlist": "data/official_detail_watchlist.json",
        "report_artifact_registry": "data/report_artifact_registry.json",
    })
    latest["report_serving"] = {
        "registry": load_registry().get("registry"),
        "default_fast_artifact": "data/decision_brief.json",
        "default_deep_review_artifact": "data/deep_review_payload.json",
        "owned_count": len(owned),
        "watchlist_count": watch_summary["count"],
        "watchlist_per_position": watch_summary["per_position"],
        "personal_gameweek_context": True,
        "gameweek_lifecycle": True,
        "counterfactual_pnl": True,
        "actual_vs_predicted_learning": True,
        "authenticated_official_readiness": True,
        "post_deadline_locked_team_view": personal_match_context.get("status"),
        "price_calibration_readiness": True,
        "report_time_intelligence": True,
        "technical_lazy_load": True,
        "fast_context_compacted": True,
        "deep_context_full_fidelity": True,
        "full_season_history": full_season_history,
        "analytics_acceptance": analytics_acceptance,
    }
    atomic_json(DATA / "latest.json", latest)
    sizes = _enforce_sizes()
    return {
        "decision_brief": brief,
        "deep_review_payload": deep,
        "watchlist_summary": watch_summary,
        "gameweek_context": gameweek_context,
        "gameweek_lifecycle": gameweek_lifecycle,
        "personal_match_context": personal_match_context,
        "artifact_sizes": sizes,
    }


if __name__ == "__main__":
    out = run()
    planning = (out.get("gameweek_context") or {}).get("planning") or {}
    lifecycle = out.get("gameweek_lifecycle") or {}
    print(json.dumps({
        "owned": out["decision_brief"]["serving_contract"]["owned"],
        "watchlist": out["decision_brief"]["serving_contract"]["watchlist"],
        "planning_gw": planning.get("gw"),
        "estimated_points": planning.get("estimated_points"),
        "decision_authority": planning.get("decision_authority"),
        "lifecycle_status": lifecycle.get("status"),
        "counterfactual_status": (lifecycle.get("counterfactual_pnl") or {}).get("status"),
        "artifact_sizes": out["artifact_sizes"],
    }, ensure_ascii=False))
