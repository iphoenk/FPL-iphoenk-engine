from __future__ import annotations

import json
from typing import Any

from src.engines import dss_watchlist as core
from src.engines.challenger_discovery import build as build_challenger_discovery
from src.utils import DATA, atomic_json, read_json


def _i(value: Any, default: int = -1) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def _candidate_projection_map(projections: dict[str, Any], discovery: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out = {
        _i(row.get("element")): row
        for row in projections.get("players") or []
        if _i(row.get("element")) > 0
    }
    for row in discovery.get("candidates") or []:
        projection = row.get("projection") or {}
        eid = _i(row.get("element"))
        if eid > 0 and projection:
            out[eid] = projection
    return out


def _mandatory_by_position(discovery: dict[str, Any]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for row in discovery.get("candidates") or []:
        if row.get("mandatory_challenger_review") is not True:
            continue
        position = str(row.get("position") or "")
        eid = _i(row.get("element"))
        if position in out and eid > 0:
            out[position].append(eid)
    return out


def _local_rank_rows(
    element_ids: list[int],
    projection_map: dict[int, dict[str, Any]],
    package_by_in: dict[int, dict[str, Any]],
    owned_position: list[dict[str, Any]],
    price_by_id: dict[int, dict[str, Any]],
    framework_core: dict[str, str],
    block: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for eid in element_ids:
        proj = projection_map.get(eid)
        if not proj:
            continue
        row = core._raw_candidate(
            proj,
            package_by_in.get(eid),
            owned_position,
            price_by_id.get(eid) or {},
            framework_core,
        )
        admitted, reasons = core._admitted(row, block)
        row["admitted"] = admitted
        row["rejection_reasons"] = reasons
        if admitted:
            rows.append(row)
    core._normalise(rows)
    rows.sort(
        key=lambda row: (
            float(row.get("dss_score") or 0.0),
            core._horizon(row, 5) if "horizons" in row else 0.0,
            -_i(row.get("now_cost"), 0),
        ),
        reverse=True,
    )
    return rows


def _decorate(
    row: dict[str, Any],
    position: str,
    rank: int,
    previous_rank: dict[int, tuple[str, int]],
    mandatory: set[int],
) -> dict[str, Any]:
    out = dict(row)
    out["rank"] = rank
    out["lifecycle"] = core._lifecycle(_i(out.get("element")), position, rank, previous_rank)
    why, risks = core._reasons(out)
    out["reasons"] = why
    out["risks"] = risks
    out["action"] = "PROMOTE REVIEW" if _i(out.get("element")) in mandatory else "WATCH"
    out["mandatory_challenger_review"] = _i(out.get("element")) in mandatory
    out.pop("raw_metrics", None)
    out.pop("normalised_metrics", None)
    return out


def build(
    *,
    base_payload: dict[str, Any] | None = None,
    discovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(base_payload or core.build())
    discovery = dict(discovery or build_challenger_discovery())
    if discovery.get("contract") != "V3_CHALLENGER_DISCOVERY_V1":
        raise RuntimeError("challenger discovery contract missing before watchlist publication")

    projections = read_json(DATA / "projections.json", {})
    team = read_json(DATA / "team.json", {})
    package_optimizer = read_json(DATA / "package_optimizer.json", {})
    prices = read_json(DATA / "prices.json", {})
    price_alerts = read_json(DATA / "price_alerts.json", {})
    framework = read_json(DATA / "framework_health.json", {})
    previous = read_json(DATA / "dss_watchlist.json", {})

    core_audit = core._registry_audit(framework, "dss_core", core.load_core_registry())
    block = bool(
        (core.load_policy().get("admission") or {}).get("block_on_critical_dss_failure", True)
        and core_audit.get("critical_failed")
    )
    framework_core = {row["id"]: row["framework_status"] for row in core_audit.get("modules") or []}
    _, owned_by_position = core._owned_context(team, projections)
    package_by_in = core._package_map(package_optimizer)
    price_by_id = core._price_map(prices, price_alerts)
    previous_rank = core._previous_ranks(previous)
    projection_map = _candidate_projection_map(projections, discovery)
    mandatory_by_position = _mandatory_by_position(discovery)

    promoted: list[dict[str, Any]] = []
    displaced: list[dict[str, Any]] = []
    final_positions: dict[str, list[dict[str, Any]]] = {}
    max_per = int(core.load_policy().get("max_per_position") or 5)

    for position in core.load_policy().get("positions") or ["GK", "DEF", "MID", "FWD"]:
        current = list((payload.get("positions") or {}).get(position) or [])
        current_ids = [_i(row.get("element")) for row in current if _i(row.get("element")) > 0]
        mandatory_ids = list(mandatory_by_position.get(position) or [])
        union_ids = list(dict.fromkeys(current_ids + mandatory_ids))
        ranked = _local_rank_rows(
            union_ids,
            projection_map,
            package_by_in,
            owned_by_position.get(position) or [],
            price_by_id,
            framework_core,
            block,
        )
        selected = ranked[:max_per]
        selected_ids = {_i(row.get("element")) for row in selected}
        current_set = set(current_ids)
        mandatory_set = set(mandatory_ids)
        for eid in selected_ids - current_set:
            promoted.append({"element": eid, "position": position, "reason": "MANDATORY_PROJECTED_VALUE_MARKET_REVIEW"})
        for eid in current_set - selected_ids:
            displaced.append({"element": eid, "position": position, "reason": "LOWER_GOVERNED_LOCAL_DSS_PRIORITY"})
        final_positions[position] = [
            _decorate(row, position, idx, previous_rank, mandatory_set)
            for idx, row in enumerate(selected, start=1)
        ]

    payload["positions"] = final_positions
    payload["removed"] = list(payload.get("removed") or []) + displaced
    summary = payload.setdefault("screening_summary", {})
    summary["published_candidates"] = sum(len(rows) for rows in final_positions.values())
    summary["mandatory_review_candidates"] = int(discovery.get("mandatory_review_count") or 0)
    summary["mandatory_promoted_to_visible_watchlist"] = len(promoted)
    summary["mandatory_promotion_details"] = promoted
    summary["mandatory_displaced_visible"] = displaced
    payload.setdefault("screening_audit", {})["challenger_discovery"] = {
        "contract": discovery.get("contract"),
        "universe_count": discovery.get("universe_count"),
        "eligible_candidate_count": discovery.get("eligible_candidate_count"),
        "material_candidate_count": discovery.get("material_candidate_count"),
        "mandatory_review_count": discovery.get("mandatory_review_count"),
        "blocked_identity_count": discovery.get("blocked_identity_count"),
    }
    payload.setdefault("governance", {})["mandatory_value_market_candidates_can_displace_visible_watchlist"] = True
    payload["governance"]["mandatory_review_never_auto_buy"] = True
    payload["governance"]["visible_watchlist_exactly_five_per_position"] = all(
        len(rows) == max_per for rows in final_positions.values()
    )
    if not payload["governance"]["visible_watchlist_exactly_five_per_position"]:
        payload["status"] = "BLOCKED"
    return payload


def run() -> dict[str, Any]:
    payload = build()
    if payload.get("status") == "BLOCKED":
        raise RuntimeError("FAIL CLOSED: governed watchlist publication blocked")
    atomic_json(core.OUT, payload)
    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {})["dss_watchlist"] = "data/dss_watchlist.json"
    latest["dss_watchlist_summary"] = {
        "model": payload.get("model"),
        "screening_contract": payload.get("screening_contract"),
        "status": payload.get("status"),
        "published_candidates": (payload.get("screening_summary") or {}).get("published_candidates"),
        "mandatory_review_candidates": (payload.get("screening_summary") or {}).get("mandatory_review_candidates"),
        "mandatory_promoted_to_visible_watchlist": (payload.get("screening_summary") or {}).get("mandatory_promoted_to_visible_watchlist"),
        "full_registry_traversal": (payload.get("screening_audit") or {}).get("full_registry_traversal"),
        "position_counts": {position: len(rows) for position, rows in (payload.get("positions") or {}).items()},
    }
    atomic_json(DATA / "latest.json", latest)
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result.get("status"),
        "published": (result.get("screening_summary") or {}).get("published_candidates"),
        "mandatory": (result.get("screening_summary") or {}).get("mandatory_review_candidates"),
        "promoted": (result.get("screening_summary") or {}).get("mandatory_promoted_to_visible_watchlist"),
    }, ensure_ascii=False))
