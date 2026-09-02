from __future__ import annotations

import argparse
import json
from typing import Any

from src.engines.lineup_governance import lineup_summary
from src.rules import LINEUP_RULES
from src.utils import DATA, ROOT, atomic_json, read_json

CONFIG = ROOT / "config" / "intelligence" / "understat_tactical.json"
TACTICAL = DATA / "understat_tactical_v3.json"
HEALTH = DATA / "understat_tactical_health_v3.json"
SUPPORT = DATA / "understat_decision_support_v3.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _config() -> dict[str, Any]:
    return read_json(CONFIG, {})


def _matchups() -> dict[str, dict[str, Any]]:
    payload = read_json(TACTICAL, {})
    rows = payload.get("tactical_matchups") if isinstance(payload, dict) else {}
    return rows if isinstance(rows, dict) else {}


def _minimum_confidence() -> float:
    return _f((_config().get("close_call") or {}).get("minimum_confidence"), 0.6)


def _key(matchup: dict[str, Any] | None) -> tuple[int, int, int, int]:
    row = matchup if isinstance(matchup, dict) else {}
    confidence = _f(row.get("confidence"))
    if confidence < _minimum_confidence():
        return (0, 0, 0, 0)
    state = str(row.get("state") or "INSUFFICIENT_EVIDENCE")
    state_value = {"POSITIVE": 1, "NEUTRAL": 0, "NEGATIVE": -1}.get(state, 0)
    supporting = len(row.get("supporting_signals") or [])
    conflicting = len(row.get("conflicting_signals") or [])
    return (state_value, supporting - conflicting, supporting, int(round(confidence * 1000)))


def _element_key(element: int, matchups: dict[str, dict[str, Any]]) -> tuple[int, int, int, int]:
    return _key(matchups.get(str(int(element))))


def _aggregate(elements: list[int], matchups: dict[str, dict[str, Any]]) -> tuple[int, int, int, int]:
    keys = [_element_key(element, matchups) for element in elements]
    return tuple(sum(value[index] for value in keys) for index in range(4))  # type: ignore[return-value]


def _compact(element: int, matchups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row = matchups.get(str(int(element))) or {}
    dimensions = row.get("dimensions") or {}
    return {
        "state": row.get("state") or "INSUFFICIENT_EVIDENCE",
        "confidence": row.get("confidence") or 0.0,
        "freshness": row.get("freshness"),
        "sample_size": row.get("sample_size") or {},
        "opponent": (row.get("opponent_evidence") or {}).get("team") or row.get("opponent"),
        "supporting_signals": list(row.get("supporting_signals") or [])[:4],
        "conflicting_signals": list(row.get("conflicting_signals") or [])[:4],
        "dimensions": {name: (value or {}).get("state") for name, value in dimensions.items() if isinstance(value, dict)},
        "player_role_interaction": row.get("player_role_interaction") or {},
        "uncertainty": row.get("uncertainty") or {},
        "provenance": row.get("provenance") or {},
    }


def _close_group_sort(rows: list[dict[str, Any]], score_field: str, gap: float, matchups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    base = sorted(rows, key=lambda row: _f(row.get(score_field)), reverse=True)
    out: list[dict[str, Any]] = []
    index = 0
    while index < len(base):
        anchor = _f(base[index].get(score_field))
        group = [base[index]]
        index += 1
        while index < len(base) and anchor - _f(base[index].get(score_field)) <= gap + 1e-9:
            group.append(base[index])
            index += 1
        if any(_element_key(int(row.get("element") or -1), matchups) != (0, 0, 0, 0) for row in group):
            group.sort(key=lambda row: (_element_key(int(row.get("element") or -1), matchups), _f(row.get(score_field))), reverse=True)
        out.extend(group)
    return out


def _package_support(matchups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    optimizer = read_json(DATA / "package_optimizer.json", {})
    rows = []
    for package in list(optimizer.get("packages") or [])[:15]:
        incoming = [int(row.get("element") or -1) for row in package.get("ins") or [] if row.get("element") is not None]
        outgoing = [int(row.get("element") or -1) for row in package.get("outs") or [] if row.get("element") is not None]
        in_key = _aggregate(incoming, matchups)
        out_key = _aggregate(outgoing, matchups)
        rows.append({
            "package_id": package.get("id"),
            "changes": package.get("changes"),
            "legal": package.get("legal"),
            "robust_score": (package.get("score") or {}).get("robust_score"),
            "hit_cost": (package.get("score") or {}).get("hit_cost"),
            "incoming": [{"element": element, "tactical": _compact(element, matchups)} for element in incoming],
            "outgoing": [{"element": element, "tactical": _compact(element, matchups)} for element in outgoing],
            "tactical_balance": tuple(in_key[index] - out_key[index] for index in range(4)),
            "advisory_only": True,
            "transfer_or_hit_authority": False,
        })
    return rows


def apply_lineup() -> dict[str, Any]:
    lineup = read_json(DATA / "lineup_decision.json", {})
    matchups = _matchups()
    health = read_json(HEALTH, {})
    if not lineup:
        raise RuntimeError("Understat tactical consumption requires lineup_decision.json")

    original_ids = [int(row.get("element")) for row in lineup.get("starting_xi") or [] if row.get("element") is not None]
    current_ids = list(original_ids)
    captain = int((lineup.get("captain") or {}).get("element") or -1)
    vice = int((lineup.get("vice_captain") or {}).get("element") or -1)
    current_score = _f((lineup.get("lineup_score") or {}).get("robust"))
    margin = _f((_config().get("close_call") or {}).get("formation_risk_adjusted_margin"), 0.25)
    candidates = []
    for row in lineup.get("alternatives") or []:
        ids = [int(value) for value in row.get("element_ids") or []]
        score = _f(row.get("decision_score"), _f(row.get("score")))
        if len(ids) != 11 or abs(current_score - score) > margin + 1e-9:
            continue
        # Understat never owns captaincy semantics. Do not choose an alternative
        # that would force a captain/vice change solely because of this layer.
        if captain not in ids or vice not in ids:
            continue
        candidates.append((row, ids))

    current_key = _aggregate(current_ids, matchups)
    selected = None
    if candidates and str(health.get("status") or "") in {"AVAILABLE", "PARTIAL"}:
        ranked = sorted(candidates, key=lambda pair: (_aggregate(pair[1], matchups), _f(pair[0].get("decision_score"), _f(pair[0].get("score")))), reverse=True)
        if ranked and _aggregate(ranked[0][1], matchups) > current_key:
            selected = ranked[0]

    xi_changed = False
    if selected:
        row, ids = selected
        current_ids = ids
        xi_changed = set(current_ids) != set(original_ids)
        if xi_changed:
            squad = {int(player.get("element")): dict(player) for player in lineup.get("squad_rows") or [] if player.get("element") is not None}
            starters = [squad[element] for element in current_ids if element in squad]
            if len(starters) != 11:
                raise RuntimeError("Understat close-call overlay failed 11-player XI invariant")
            formation = str(row.get("formation") or "")
            if formation not in set(LINEUP_RULES.get("legal_formations") or []):
                raise RuntimeError(f"Understat close-call overlay produced illegal formation {formation}")
            starters.sort(key=lambda player: ({"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}.get(str(player.get("position")), 9), -_f(player.get("selection_score"))))
            lineup["starting_xi"] = starters
            lineup["formation"] = formation
            lineup["lineup_score"] = {
                "robust": row.get("decision_score", row.get("score")),
                "base_robust": row.get("base_score"),
                "xpts_mean": row.get("xpts_mean"),
                "xpts_std": row.get("xpts_std"),
                "risk_adjustment": row.get("risk_adjustment"),
            }

    squad_rows = [dict(row) for row in lineup.get("squad_rows") or []]
    starter_set = set(current_ids)
    bench_rows = [row for row in squad_rows if int(row.get("element") or -1) not in starter_set]
    bench_gk = next((row for row in bench_rows if row.get("position") == "GK"), None)
    outfield = [row for row in bench_rows if row.get("position") != "GK"]
    bench_gap = _f((_config().get("close_call") or {}).get("bench_score_margin"), 0.12)
    outfield = _close_group_sort(outfield, "bench_score", bench_gap, matchups)
    if bench_gk is None or len(outfield) != 3:
        raise RuntimeError("Understat close-call overlay failed bench invariant")
    lineup["bench"] = {
        "gk": {"element": bench_gk.get("element"), "name": bench_gk.get("name"), "position": bench_gk.get("position"), "bench_score": bench_gk.get("bench_score"), "understat_tactical": _compact(int(bench_gk.get("element") or -1), matchups)},
        "order": [{"element": row.get("element"), "name": row.get("name"), "position": row.get("position"), "bench_score": row.get("bench_score"), "lower80": row.get("lower80"), "upper80": row.get("upper80"), "understat_tactical": _compact(int(row.get("element") or -1), matchups)} for row in outfield],
        "close_battles": (lineup.get("bench") or {}).get("close_battles") or [],
    }

    selected_set = set(current_ids)
    alternatives = list(lineup.get("alternatives") or [])
    comparison = []
    for index, source in enumerate(lineup.get("formation_comparison") or []):
        item = dict(source)
        alt_ids = set(int(value) for value in (alternatives[index].get("element_ids") or [])) if index < len(alternatives) else set()
        item["selected"] = bool(alt_ids) and alt_ids == selected_set
        item["understat_tactical_key"] = list(_aggregate(list(alt_ids), matchups)) if alt_ids else [0, 0, 0, 0]
        comparison.append(item)
    if comparison and sum(row.get("selected") is True for row in comparison) != 1:
        raise RuntimeError("Understat close-call overlay could not reconcile formation comparison")
    if comparison:
        lineup["formation_comparison"] = comparison

    battle = dict(lineup.get("main_starting_xi_battle") or {})
    battle["understat_tiebreak"] = {
        "eligible": bool(candidates),
        "applied": xi_changed,
        "before_key": list(current_key),
        "after_key": list(_aggregate(current_ids, matchups)),
        "captaincy_semantics_unchanged": True,
        "policy": "Understat resolves existing close legal XI/bench choices only; xPts/xMins unchanged",
    }
    lineup["main_starting_xi_battle"] = battle
    lineup.setdefault("governance", {}).update({
        "understat_intelligence_contract": "UNDERSTAT_TACTICAL_INTELLIGENCE_V1",
        "understat_close_call_only": True,
        "understat_xi_tiebreak_applied": xi_changed,
        "understat_direct_xpts_mutation": False,
        "understat_direct_xmins_mutation": False,
        "understat_captaincy_semantics_unchanged": True,
        "understat_missing_evidence_neutral": True,
    })
    atomic_json(DATA / "lineup_decision.json", lineup)

    latest = read_json(DATA / "latest.json", {})
    if latest:
        latest["lineup_decision_summary"] = lineup_summary(lineup)
        latest["understat_decision_support_summary"] = {
            "status": health.get("status") or "UNAVAILABLE",
            "xi_tiebreak_applied": xi_changed,
            "captaincy_semantics_unchanged": True,
            "direct_xpts_mutation": False,
        }
        latest.setdefault("files", {})["understat_decision_support"] = "data/understat_decision_support_v3.json"
        atomic_json(DATA / "latest.json", latest)

    support = {
        "schema_version": 1,
        "contract": "V3_UNDERSTAT_DECISION_SUPPORT_V1",
        "status": health.get("status") or "UNAVAILABLE",
        "full_universe_count": ((health.get("coverage") or {}).get("official_universe_count")),
        "lineup": {"before": original_ids, "after": current_ids, "formation": lineup.get("formation"), "tiebreak_applied": xi_changed, "before_key": list(current_key), "after_key": list(_aggregate(current_ids, matchups))},
        "bench": {"order": [row.get("element") for row in outfield], "close_call_only": True},
        "transfer_packages": _package_support(matchups),
        "guardrails": {"advisory_only": True, "transfer_hit_authority": False, "price_transfer_authority": False, "direct_xpts_mutation": False, "direct_xmins_mutation": False, "captaincy_semantics_unchanged": True},
    }
    atomic_json(SUPPORT, support)

    framework = read_json(DATA / "framework_health.json", {})
    if framework:
        framework["understat_tactical_consumption"] = {
            "status": health.get("status") or "UNAVAILABLE",
            "optional_enrichment": True,
            "xi_tiebreak_applied": xi_changed,
            "bench_tiebreak_enabled": True,
            "package_comparison_count": len(support["transfer_packages"]),
            "direct_xpts_mutation": False,
            "production_blocking": False,
        }
        framework.setdefault("governance", {}).update({"understat_optional_enrichment_fail_soft": True, "understat_does_not_create_second_prediction_authority": True})
        atomic_json(DATA / "framework_health.json", framework)
    return support


def apply_watchlist() -> dict[str, Any]:
    payload = read_json(DATA / "dss_watchlist.json", {})
    if not payload:
        raise RuntimeError("Understat watchlist consumption requires dss_watchlist.json")
    matchups = _matchups()
    gap = _f((_config().get("close_call") or {}).get("watchlist_base_score_margin"), 0.15)
    positions = {}
    reranked = 0
    for position, source_rows in (payload.get("positions") or {}).items():
        rows = [dict(row) for row in source_rows or []]
        before = [int(row.get("element") or -1) for row in rows]
        rows = _close_group_sort(rows, "dss_score", gap, matchups)
        after = [int(row.get("element") or -1) for row in rows]
        reranked += int(before != after)
        for rank, row in enumerate(rows, start=1):
            element = int(row.get("element") or -1)
            row["rank"] = rank
            row["understat_tactical"] = _compact(element, matchups)
        positions[str(position)] = rows
    payload["positions"] = positions
    payload.setdefault("governance", {}).update({
        "understat_close_call_tiebreak": True,
        "understat_membership_promotion_forbidden": True,
        "understat_reranked_position_count": reranked,
        "understat_direct_xpts_mutation": False,
    })
    atomic_json(DATA / "dss_watchlist.json", payload)
    latest = read_json(DATA / "latest.json", {})
    if latest:
        summary = latest.get("dss_watchlist_summary") or {}
        summary["understat_tactical"] = {"reranked_positions": reranked, "close_call_only": True, "membership_unchanged": True}
        latest["dss_watchlist_summary"] = summary
        atomic_json(DATA / "latest.json", latest)
    return payload


def _decorate(value: Any, matchups: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, list):
        return [_decorate(item, matchups) for item in value]
    if not isinstance(value, dict):
        return value
    out = {key: _decorate(item, matchups) for key, item in value.items()}
    if out.get("element") is not None and "understat_tactical" not in out:
        try:
            out["understat_tactical"] = _compact(int(out["element"]), matchups)
        except (TypeError, ValueError):
            pass
    return out


def apply_report() -> dict[str, Any]:
    matchups = _matchups()
    health = read_json(HEALTH, {})
    support = read_json(SUPPORT, {})
    result = {}
    for name in ("user_report.json", "decision_brief.json", "deep_review_payload.json"):
        path = DATA / name
        payload = read_json(path, {})
        if not payload:
            continue
        decorated = _decorate(payload, matchups)
        decorated["understat_tactical_intelligence"] = {
            "contract": "UNDERSTAT_TACTICAL_INTELLIGENCE_V1",
            "status": health.get("status") or "UNAVAILABLE",
            "source": health.get("source") or {},
            "coverage": health.get("coverage") or {},
            "decision_usage": {
                "xi_bench_formation_close_calls": True,
                "watchlist_close_calls": True,
                "transfer_package_evidence": True,
                "captaincy_semantics_unchanged": True,
                "direct_xpts_mutation": False,
                "direct_xmins_mutation": False,
            },
            "support": support,
        }
        atomic_json(path, decorated)
        result[name] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("lineup", "watchlist", "report"), required=True)
    args = parser.parse_args()
    if args.target == "lineup":
        result = apply_lineup()
    elif args.target == "watchlist":
        result = apply_watchlist()
    else:
        result = apply_report()
    print(json.dumps({"target": args.target, "status": "PASS", "result_type": type(result).__name__}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
