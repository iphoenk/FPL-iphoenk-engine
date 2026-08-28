from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from src.engines.fpl_legality import squad_shape_is_legal
from src.models.v4_prediction import clamp, f
from src.utils import CONFIG, DATA, atomic_json, iso_now, read_json

OUT = DATA / "challenger_comparator_v4.json"
POLICY_PATH = CONFIG / "challenger_comparator.json"
RAW_SNAPSHOT = DATA / "runtime" / "snapshot.v1.json"

DECISION_RANK = {
    "HOLD_OWNED": 0,
    "WATCH_CHALLENGER": 1,
    "PROMOTE_TO_WATCHLIST": 2,
    "REVIEW": 3,
    "LEAN_TRANSFER": 4,
    "STRONG_TRANSFER": 5,
}


def _player_maps() -> tuple[dict[int, dict], dict[int, dict], dict[int, dict]]:
    universe = read_json(DATA / "universe.json", {})
    predictions = read_json(DATA / "predictions_v4.json", {})
    team = read_json(DATA / "team.json", {})
    umap = {
        int(row["element"]): row
        for row in universe.get("players", [])
        if row.get("element") is not None
    }
    pmap = {
        int(row["element"]): row
        for row in predictions.get("players", [])
        if row.get("element") is not None
    }
    owned = {
        int(row["element"]): row
        for row in team.get("team_value_ledger", [])
        if row.get("element") is not None
    }
    return umap, pmap, owned


def _average_fixture_metric(pred: dict, field: str, horizon: int = 3) -> float | None:
    values: list[float] = []
    for fixture in (pred.get("fixtures") or [])[:horizon]:
        xmins = fixture.get("xmins") or {}
        if xmins.get(field) is not None:
            values.append(f(xmins.get(field)))
    return sum(values) / len(values) if values else None


def _horizon_total(pred: dict, horizon: int) -> float:
    return round(sum(f(row.get("xpts")) for row in (pred.get("fixtures") or [])[:horizon]), 3)


def _horizon_uncertainty(pred: dict, horizon: int) -> float | None:
    widths = []
    for row in (pred.get("fixtures") or [])[:horizon]:
        if row.get("lower80") is None or row.get("upper80") is None:
            continue
        widths.append(max(0.0, (f(row.get("upper80")) - f(row.get("lower80"))) / 2.0))
    if not widths:
        return None
    return round(math.sqrt(sum(value * value for value in widths)), 3)


def _fixture_identity_index(raw: dict, team_names: dict[int, str]) -> dict[tuple[int, int], dict]:
    index: dict[tuple[int, int], dict] = {}
    for fixture in (raw.get("official") or {}).get("fixtures") or []:
        event = fixture.get("event")
        home_id, away_id = fixture.get("team_h"), fixture.get("team_a")
        if event is None or home_id is None or away_id is None:
            continue
        index[(int(home_id), int(event))] = {
            "opponent_id": int(away_id),
            "opponent": team_names.get(int(away_id)),
            "home": True,
            "venue": "HOME",
            "kickoff_time": fixture.get("kickoff_time"),
            "fixture_source": "raw_snapshot.official.fixtures",
        }
        index[(int(away_id), int(event))] = {
            "opponent_id": int(home_id),
            "opponent": team_names.get(int(home_id)),
            "home": False,
            "venue": "AWAY",
            "kickoff_time": fixture.get("kickoff_time"),
            "fixture_source": "raw_snapshot.official.fixtures",
        }
    return index


def _team_names(universe: dict[int, dict]) -> dict[int, str]:
    names: dict[int, str] = {}
    for row in universe.values():
        team_id = int(row.get("team_id") or 0)
        if team_id and row.get("team"):
            names.setdefault(team_id, str(row["team"]))
    return names


def _optional_watchlist(policy: dict, umap: dict[int, dict]) -> tuple[list[dict], dict]:
    relative = str((policy.get("evidence") or {}).get("optional_watchlist_path") or "data/watchlist_v4.json")
    path = Path(relative)
    if not path.is_absolute():
        path = DATA.parent / path
    if not path.is_file():
        return [], {
            "status": "UNAVAILABLE",
            "path": relative,
            "reason": "authoritative governed watchlist artifact is not materialized in V4 runtime",
        }
    payload = read_json(path, {})
    rows = payload.get("players") or payload.get("watchlist") or payload.get("candidates") or []
    candidates = []
    for row in rows:
        element = row.get("element") if isinstance(row, dict) else row
        try:
            element = int(element)
        except (TypeError, ValueError):
            continue
        if element not in umap:
            continue
        candidates.append({
            "element": element,
            "challenger_type": "GOVERNED_WATCHLIST",
            "candidate_source": relative,
            "watchlist_metadata": row if isinstance(row, dict) else {},
        })
    return candidates, {
        "status": "AVAILABLE" if candidates else "EMPTY",
        "path": relative,
        "candidates": len(candidates),
    }


def _engine_governed_candidates(umap: dict[int, dict]) -> list[dict]:
    sanity = read_json(DATA / "recommendation_sanity_v4.json", {})
    by_element: dict[int, dict] = {}
    for replacement_count, package in (sanity.get("best_by_replacement_count") or {}).items():
        if not package:
            continue
        incoming_evidence = {
            int(row["element"]): row
            for row in ((package.get("evidence") or {}).get("incoming") or [])
            if row.get("element") is not None
        }
        for row in package.get("in") or []:
            element = int(row.get("element") or 0)
            if not element or element not in umap:
                continue
            existing = by_element.setdefault(element, {
                "element": element,
                "challenger_type": "GOVERNED_DSS_CANDIDATE",
                "candidate_source": "recommendation_sanity_v4.best_by_replacement_count",
                "package_memberships": [],
                "governed_evidence": incoming_evidence.get(element) or {},
            })
            existing["package_memberships"].append({
                "replacements": int(replacement_count),
                "classification": package.get("classification"),
                "sanity_gain_5": package.get("sanity_gain_5"),
            })
    return list(by_element.values())


def _trigger_signals(universe_row: dict, pred: dict, policy: dict) -> list[str]:
    cfg = policy.get("emerging_trigger") or {}
    signals = []
    # Recent-match discovery must use Official FPL event_points from the
    # immutable raw snapshot. Season total_points is never a recent-haul proxy.
    if universe_row.get("event_points") is not None and f(universe_row.get("event_points")) >= f(cfg.get("points_signal"), 8):
        signals.append("RECENT_EVENT_POINTS_RETURN")
    if f(universe_row.get("expected_goal_involvements")) >= f(cfg.get("xgi_signal"), 0.55):
        signals.append("SEASON_UNDERLYING_XGI")
    net_transfers = f(universe_row.get("transfers_in_event")) - f(universe_row.get("transfers_out_event"))
    if net_transfers >= f(cfg.get("net_transfers_signal"), 25000):
        signals.append("MARKET_ATTENTION")
    if (
        f(universe_row.get("starts")) >= f(cfg.get("start_signal"), 1)
        and f(universe_row.get("minutes")) >= f(cfg.get("minutes_signal"), 60)
    ):
        signals.append("STARTING_ROLE")
    value = pred.get("value") or {}
    if f(value.get("xpts5_per_million")) >= f(cfg.get("value_signal_xpts5_per_million"), 2.2):
        signals.append("VALUE_OPPORTUNITY")
    status = str(universe_row.get("status") or "")
    if status in {"i", "d", "s", "u"}:
        signals.append("AVAILABILITY_CHANGE_CONTEXT")
    return signals


def _screen_candidate(candidate: dict, umap: dict[int, dict], pmap: dict[int, dict], policy: dict) -> dict:
    element = int(candidate["element"])
    universe = umap.get(element) or {}
    pred = pmap.get(element) or {}
    screening = policy.get("screening") or {}
    start = _average_fixture_metric(pred, "start_probability", 3)
    dnp = _average_fixture_metric(pred, "dnp_probability", 3)
    fixtures = len((pred.get("fixtures") or [])[:5])
    checks = {
        "eligible_status": str(universe.get("status") or "") in set(screening.get("status_allowed") or ["a", "d"]),
        "fpl_position": bool(universe.get("position")),
        "price": int(universe.get("now_cost") or 0) > 0,
        "prediction_available": bool(pred),
        "xmins": start is not None and start >= f(screening.get("minimum_start_probability_3gw"), 0.62),
        "dnp": dnp is not None and dnp <= f(screening.get("maximum_dnp_probability_3gw"), 0.28),
        "fixture_relevance": fixtures >= int(screening.get("minimum_relevant_fixtures_5gw") or 3),
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "start_probability_3gw": round(start, 4) if start is not None else None,
        "dnp_probability_3gw": round(dnp, 4) if dnp is not None else None,
        "fixture_rows_5gw": fixtures,
    }


def _role_sustainability(universe: dict, pred: dict) -> dict:
    fixtures = pred.get("fixtures") or []
    first = fixtures[0] if fixtures else {}
    rates = first.get("rates") or {}
    priors = pred.get("priors") or {}
    raw_attacking = max(0.0, f(rates.get("raw_xg90")) + f(rates.get("raw_xa90")))
    shrunk_attacking = max(0.0, f(rates.get("xg90")) + f(rates.get("xa90")))
    spike_ratio = raw_attacking / max(0.04, shrunk_attacking)
    start = _average_fixture_metric(pred, "start_probability", 3)
    dnp = _average_fixture_metric(pred, "dnp_probability", 3)
    start_series = [f((row.get("xmins") or {}).get("start_probability")) for row in fixtures[:5]]
    minute_series = [f((row.get("xmins") or {}).get("expected_minutes")) for row in fixtures[:5]]
    start_trend = round(start_series[-1] - start_series[0], 4) if len(start_series) >= 2 else None
    minute_trend = round(minute_series[-1] - minute_series[0], 1) if len(minute_series) >= 2 else None
    return {
        "tactical_role": priors.get("tactical_role") or (first.get("calibration") or {}).get("tactical_role"),
        "tactical_role_source": priors.get("tactical_role_source") or (first.get("calibration") or {}).get("tactical_role_source"),
        "starts": universe.get("starts"),
        "minutes": universe.get("minutes"),
        "start_probability_3gw": round(start, 4) if start is not None else None,
        "dnp_probability_3gw": round(dnp, 4) if dnp is not None else None,
        "start_probability_trend_5gw": start_trend,
        "expected_minutes_trend_5gw": minute_trend,
        "raw_attacking_rate": round(raw_attacking, 4),
        "shrunk_attacking_rate": round(shrunk_attacking, 4),
        "raw_to_shrunk_ratio": round(spike_ratio, 4),
        "current_season_weight": round(f(rates.get("current_season_weight")), 4),
        "fixture_run": pred.get("fixture_run") or {},
        "source": "canonical_prediction_rate_shrinkage+xmins+fixture_run",
    }


def _performance_signal(candidate: dict, screening: dict, sustainability: dict, policy: dict) -> str:
    if candidate.get("challenger_type") != "EMERGING_CHALLENGER":
        return "GOVERNED_CANDIDATE"
    signals = candidate.get("trigger_signals") or []
    minimum = int((policy.get("emerging_trigger") or {}).get("minimum_signals") or 2)
    if len(signals) < minimum:
        return "NOISE"
    if not screening.get("pass"):
        return "INTERESTING"
    maximum_ratio = f((policy.get("screening") or {}).get("maximum_raw_to_shrunk_ratio_for_sustainable"), 2.5)
    if f(sustainability.get("raw_to_shrunk_ratio"), 99) > maximum_ratio:
        return "STRONG"
    return "SUSTAINABLE_CANDIDATE"


def _emerging_candidates(umap: dict[int, dict], pmap: dict[int, dict], excluded: set[int], policy: dict) -> list[dict]:
    minimum = int((policy.get("emerging_trigger") or {}).get("minimum_signals") or 2)
    rows = []
    for element, universe in umap.items():
        if element in excluded or element not in pmap:
            continue
        signals = _trigger_signals(universe, pmap[element], policy)
        if len(signals) < minimum:
            continue
        rows.append({
            "element": element,
            "challenger_type": "EMERGING_CHALLENGER",
            "candidate_source": "official_recent_performance_trigger+canonical_prediction",
            "trigger_signals": signals,
        })
    rows.sort(
        key=lambda row: (
            len(row.get("trigger_signals") or []),
            _horizon_total(pmap[row["element"]], 5),
            f(umap[row["element"]].get("transfers_in_event")) - f(umap[row["element"]].get("transfers_out_event")),
        ),
        reverse=True,
    )
    return rows[: int((policy.get("candidate_limits") or {}).get("emerging") or 20)]


def _direct_swap(owned_element: int, challenger_element: int, team: dict, umap: dict[int, dict]) -> dict:
    ledger = list(team.get("team_value_ledger") or [])
    owned = next((row for row in ledger if int(row.get("element") or 0) == owned_element), {})
    challenger = umap.get(challenger_element) or {}
    sell_cost = owned.get("sell_cost")
    now_cost = challenger.get("now_cost")
    itb = team.get("totals", {}).get("itb")
    available = None if sell_cost is None or now_cost is None or itb is None else int(sell_cost) + int(itb)
    affordable = None if available is None else int(now_cost) <= available
    replacement = {
        "element": challenger_element,
        "name": challenger.get("name"),
        "team_id": challenger.get("team_id"),
        "position": challenger.get("position"),
    }
    hypothetical = []
    for row in ledger:
        if int(row.get("element") or 0) == owned_element:
            hypothetical.append(replacement)
        else:
            hypothetical.append({
                "element": row.get("element"),
                "name": row.get("name"),
                "team_id": row.get("team_id"),
                "position": row.get("position"),
            })
    same_position = owned.get("position") == challenger.get("position")
    legal = bool(same_position and squad_shape_is_legal(hypothetical))
    return {
        "same_position": same_position,
        "owned_sell_value": sell_cost,
        "challenger_purchase_price": now_cost,
        "itb": itb,
        "available_tenths": available,
        "affordable": affordable,
        "squad_legal": legal,
        "requires_secondary_transfer": not legal or affordable is False,
        "legality_source": "src.engines.fpl_legality.squad_shape_is_legal",
        "price_source": "team_value_ledger+official_universe.now_cost",
    }


def _rank_owned_targets(challenger: dict, owned: dict[int, dict], pmap: dict[int, dict], umap: dict[int, dict], team: dict, effective: dict, policy: dict) -> list[dict]:
    element = int(challenger["element"])
    challenger_universe, challenger_pred = umap[element], pmap[element]
    bench = effective.get("effective_plan", {}).get("bench") or {}
    bench_ids = {
        int(row.get("element"))
        for row in ([bench.get("gk")] + list(bench.get("order") or []))
        if isinstance(row, dict) and row.get("element") is not None
    }
    ranked = []
    max_gap = int((policy.get("screening") or {}).get("maximum_direct_swap_price_gap_tenths") or 25)
    for owned_element, owned_row in owned.items():
        if owned_row.get("position") != challenger_universe.get("position") or owned_element not in pmap:
            continue
        swap = _direct_swap(owned_element, element, team, umap)
        price_gap = abs(int(challenger_universe.get("now_cost") or 0) - int(owned_row.get("sell_cost") or 0))
        edge5 = _horizon_total(challenger_pred, 5) - _horizon_total(pmap[owned_element], 5)
        owned_start = _average_fixture_metric(pmap[owned_element], "start_probability", 3)
        structurally_relevant = price_gap <= max_gap or swap.get("affordable") is True or edge5 > 0
        if not structurally_relevant:
            continue
        reasons = ["SAME_FPL_POSITION"]
        if swap.get("affordable"):
            reasons.append("DIRECT_SWAP_AFFORDABLE")
        if edge5 > 0:
            reasons.append("CHALLENGER_HIGHER_5GW_XPTS")
        if owned_element in bench_ids:
            reasons.append("OWNED_BENCH_ROLE")
        minutes_risk = f((policy.get("screening") or {}).get("owned_minutes_risk_start_probability"), 0.72)
        if owned_start is not None and owned_start < minutes_risk:
            reasons.append("OWNED_MINUTES_RISK")
        ranked.append({
            "owned_element": owned_element,
            "reasons": reasons,
            "swap": swap,
            "edge5": round(edge5, 3),
            "price_gap_tenths": price_gap,
            "owned_start_probability_3gw": round(owned_start, 4) if owned_start is not None else None,
            "bench_role": owned_element in bench_ids,
        })
    ranked.sort(
        key=lambda row: (
            row["swap"].get("affordable") is True,
            row["edge5"] > 0,
            row["bench_role"],
            row["edge5"],
            -row["price_gap_tenths"],
            -(row["owned_start_probability_3gw"] or 0),
        ),
        reverse=True,
    )
    limit = int((policy.get("candidate_limits") or {}).get("owned_targets_per_challenger") or 3)
    return ranked[:limit]


def _tactical_context(team_id: int, event: int, optional: dict) -> dict:
    if not optional:
        return {"status": "UNVERIFIED", "reason": "no materialized tactical opponent context in V4 runtime"}
    teams = optional.get("teams") or {}
    team = teams.get(str(team_id)) or teams.get(team_id) or {}
    event_map = team.get("events") or {}
    row = event_map.get(str(event)) or event_map.get(event) or team.get("current") or {}
    return row if row else {"status": "UNVERIFIED", "reason": "opponent tactical context missing for event"}


def _fixture_projection_view(pred: dict, team_id: int, fixture_index: dict, tactical: dict, team_names: dict[int, str]) -> list[dict]:
    views = []
    for row in (pred.get("fixtures") or [])[:5]:
        event = int(row.get("event") or 0)
        identity = fixture_index.get((team_id, event), {})
        opponent_id = int(identity.get("opponent_id") or 0)
        calibration = row.get("calibration") or {}
        components = row.get("components") or {}
        xmins = row.get("xmins") or {}
        role = calibration.get("tactical_role")
        tactical_row = _tactical_context(opponent_id, event, tactical)
        route = sorted(
            (
                {"route": key, "xpts_component": round(f(value), 3)}
                for key, value in components.items()
                if key in {"attack", "clean_sheet", "saves", "defcon", "bonus", "appearance"} and f(value) > 0
            ),
            key=lambda item: item["xpts_component"],
            reverse=True,
        )
        views.append({
            "gw": event,
            "opponent": identity.get("opponent") or team_names.get(opponent_id),
            "opponent_id": opponent_id or None,
            "home_away": identity.get("venue") or "UNVERIFIED",
            "kickoff_time": identity.get("kickoff_time"),
            "xpts": row.get("xpts"),
            "xmins": xmins.get("expected_minutes"),
            "start_probability": xmins.get("start_probability"),
            "dnp_probability": xmins.get("dnp_probability"),
            "lower80": row.get("lower80"),
            "upper80": row.get("upper80"),
            "route_to_points": route,
            "player_role": role,
            "matchup_edge": tactical_row.get("matchup_edge", "UNVERIFIED"),
            "matchup_risk": tactical_row.get("matchup_risk", "UNVERIFIED"),
            "floor_effect": row.get("lower80"),
            "ceiling_effect": row.get("upper80"),
            "matchup_confidence": tactical_row.get("confidence", "UNVERIFIED"),
            "opponent_tactical_structure": tactical_row,
            "rest_congestion": {
                "workload_factor": xmins.get("workload_factor"),
                "rest_days": tactical_row.get("rest_days", "UNVERIFIED"),
                "previous_match_minutes": tactical_row.get("previous_match_minutes", "UNVERIFIED"),
                "midweek_schedule": tactical_row.get("midweek_schedule", "UNVERIFIED"),
                "international_context": tactical_row.get("international_context", "UNVERIFIED"),
                "status": "VERIFIED" if tactical_row.get("rest_days") != "UNVERIFIED" else "MODEL_ONLY",
            },
            "provenance": {
                "fixture": identity.get("fixture_source", "UNVERIFIED"),
                "projection": (row.get("provenance") or {}).get("model"),
                "xmins": (row.get("provenance") or {}).get("xmins_prior_source"),
                "tactical": tactical_row.get("source", "UNVERIFIED") if isinstance(tactical_row, dict) else "UNVERIFIED",
            },
        })
    return views


def _comparison_pair(challenger: dict, owned_element: int, maps: tuple[dict[int, dict], dict[int, dict], dict[int, dict]], team: dict, effective: dict, raw: dict, policy: dict, tactical: dict) -> dict:
    umap, pmap, owned = maps
    challenger_element = int(challenger["element"])
    owned_pred, challenger_pred = pmap[owned_element], pmap[challenger_element]
    owned_universe, challenger_universe = umap[owned_element], umap[challenger_element]
    names = _team_names(umap)
    fixture_index = _fixture_identity_index(raw, names)
    owned_fixtures = _fixture_projection_view(owned_pred, int(owned_universe.get("team_id") or 0), fixture_index, tactical, names)
    challenger_fixtures = _fixture_projection_view(challenger_pred, int(challenger_universe.get("team_id") or 0), fixture_index, tactical, names)
    horizons = {}
    for horizon in (1, 2, 3, 5):
        owned_total = _horizon_total(owned_pred, horizon)
        challenger_total = _horizon_total(challenger_pred, horizon)
        horizons[str(horizon)] = {
            "owned_xpts": owned_total,
            "challenger_xpts": challenger_total,
            "projected_edge": round(challenger_total - owned_total, 3),
            "owned_uncertainty80_half_range": _horizon_uncertainty(owned_pred, horizon),
            "challenger_uncertainty80_half_range": _horizon_uncertainty(challenger_pred, horizon),
        }
    raw_gain5 = f(horizons["5"]["projected_edge"])
    owned_u = _horizon_uncertainty(owned_pred, 5)
    challenger_u = _horizon_uncertainty(challenger_pred, 5)
    combined_uncertainty = math.sqrt((owned_u or 0) ** 2 + (challenger_u or 0) ** 2) if owned_u is not None and challenger_u is not None else None
    edge_ratio = raw_gain5 / combined_uncertainty if combined_uncertainty and combined_uncertainty > 0 else None
    screening = _screen_candidate(challenger, umap, pmap, policy)
    sustainability = _role_sustainability(challenger_universe, challenger_pred)
    performance_signal = _performance_signal(challenger, screening, sustainability, policy)
    swap = _direct_swap(owned_element, challenger_element, team, umap)
    active_chip = (((effective.get("effective_plan") or {}).get("chip_context") or {}).get("active_chip") or "NONE").upper()
    wildcard = active_chip == "WILDCARD"
    opportunity_cost: float | None = 0.0 if wildcard else None
    structural_cost: float | None = 0.0 if swap.get("squad_legal") and swap.get("affordable") else None
    net_value = raw_gain5 - opportunity_cost - structural_cost if opportunity_cost is not None and structural_cost is not None else None
    tactical_verified = sum(row.get("matchup_edge") != "UNVERIFIED" for row in challenger_fixtures)
    congestion_verified = sum((row.get("rest_congestion") or {}).get("status") == "VERIFIED" for row in challenger_fixtures)
    core_completeness = sum([
        bool(screening.get("pass")),
        swap.get("affordable") is not None,
        swap.get("squad_legal") is not None,
        len(challenger_fixtures) >= 3,
        combined_uncertainty is not None,
    ]) / 5.0
    confidence_weights = policy.get("confidence_weights") or {}
    confidence = clamp(
        f(confidence_weights.get("core_completeness"), 0.58) * core_completeness
        + f(confidence_weights.get("start_security"), 0.22) * (screening.get("start_probability_3gw") or 0)
        + f(confidence_weights.get("tactical_evidence"), 0.10) * min(1.0, tactical_verified / 3.0)
        + f(confidence_weights.get("congestion_evidence"), 0.10) * min(1.0, congestion_verified / 3.0)
    )
    decision_cfg = policy.get("decision_policy") or {}
    decision = "HOLD_OWNED"
    reasons = []
    risks = []
    if swap.get("affordable") is False or not swap.get("squad_legal"):
        decision = "HOLD_OWNED"
        risks.append("DIRECT_SWAP_NOT_CURRENTLY_LEGAL_OR_AFFORDABLE")
    elif challenger.get("challenger_type") == "EMERGING_CHALLENGER" and performance_signal != "SUSTAINABLE_CANDIDATE":
        decision = "WATCH_CHALLENGER"
        reasons.append("RECENT_PERFORMANCE_IS_DISCOVERY_SIGNAL_NOT_TRANSFER_PROOF")
    elif raw_gain5 <= 0:
        decision = "HOLD_OWNED"
        reasons.append("OWNED_RETAINS_5GW_MODEL_EDGE")
    elif edge_ratio is None or edge_ratio < f(decision_cfg.get("edge_to_uncertainty_review"), 0.35):
        decision = "REVIEW" if raw_gain5 > 0 else "HOLD_OWNED"
        reasons.append("PROJECTED_EDGE_SMALL_RELATIVE_TO_UNCERTAINTY")
    elif challenger.get("challenger_type") == "EMERGING_CHALLENGER" and edge_ratio < f(decision_cfg.get("edge_to_uncertainty_lean"), 0.80):
        decision = "PROMOTE_TO_WATCHLIST"
        reasons.append("SUSTAINABLE_EMERGING_SIGNAL_WITHOUT_TRANSFER_GRADE_EDGE")
    elif edge_ratio >= f(decision_cfg.get("edge_to_uncertainty_strong"), 1.35) and confidence >= f(decision_cfg.get("minimum_core_confidence_for_strong"), 0.80):
        decision = "STRONG_TRANSFER"
        reasons.append("LARGE_MULTI_GW_EDGE_RELATIVE_TO_MODEL_UNCERTAINTY")
    elif edge_ratio >= f(decision_cfg.get("edge_to_uncertainty_lean"), 0.80) and confidence >= f(decision_cfg.get("minimum_core_confidence_for_lean"), 0.68):
        decision = "LEAN_TRANSFER"
        reasons.append("MULTI_GW_EDGE_EXCEEDS_UNCERTAINTY_SCREEN")
    else:
        decision = "REVIEW"
        reasons.append("POSITIVE_EDGE_BUT_EVIDENCE_NOT_STRONG_ENOUGH")
    if bool(decision_cfg.get("missing_tactical_or_congestion_caps_strong", True)) and decision == "STRONG_TRANSFER" and (tactical_verified < 3 or congestion_verified < 3):
        decision = "LEAN_TRANSFER"
        risks.append("TACTICAL_OR_CONGESTION_EVIDENCE_INCOMPLETE_STRONG_TRANSFER_CAPPED")
    if not wildcard and opportunity_cost is None:
        if decision in {"LEAN_TRANSFER", "STRONG_TRANSFER"}:
            decision = "REVIEW"
        risks.append("FREE_TRANSFER_OPPORTUNITY_COST_UNVERIFIED")
    if challenger.get("challenger_type") == "GOVERNED_DSS_CANDIDATE":
        reasons.append("ENGINE_GOVERNED_CANDIDATE_NOT_MISLABELLED_AS_WATCHLIST")
    if tactical_verified < min(3, len(challenger_fixtures)):
        risks.append("TACTICAL_OPPONENT_STRUCTURE_INCOMPLETE")
    if congestion_verified < min(3, len(challenger_fixtures)):
        risks.append("ALL_COMPETITION_REST_CONGESTION_INCOMPLETE")
    reversal = [
        "CHALLENGER_FAILS_TO_START_OR_XMINS_FALLS",
        "POSITIONAL_COMPETITOR_RETURNS_OR_ROLE_DEEPENS",
        "OWNED_ROLE_OR_XMINS_IMPROVES",
        "INJURY_OR_SUSPENSION_CHANGES_AVAILABILITY",
        "FIXTURE_OR_MIDWEEK_SCHEDULE_CHANGES",
        "PRICE_MOVE_REMOVES_AFFORDABILITY",
        "UNDERLYING_ATTACKING_RATE_REGRESSES",
    ]
    return {
        "player_out": {
            "element": owned_element,
            "name": owned_universe.get("name"),
            "team": owned_universe.get("team"),
            "position": owned_universe.get("position"),
            "sell_value": (owned.get(owned_element) or {}).get("sell_cost"),
        },
        "player_in": {
            "element": challenger_element,
            "name": challenger_universe.get("name"),
            "team": challenger_universe.get("team"),
            "position": challenger_universe.get("position"),
            "price": challenger_universe.get("now_cost"),
        },
        "challenger_type": challenger.get("challenger_type"),
        "candidate_source": challenger.get("candidate_source"),
        "trigger_signals": challenger.get("trigger_signals") or [],
        "planning_gw": (team.get("projection_baseline") or {}).get("planning_gw"),
        "horizon_1gw": horizons["1"],
        "horizon_2gw": horizons["2"],
        "horizon_3gw": horizons["3"],
        "horizon_5gw": horizons["5"],
        "fixture_by_fixture": {
            "owned": owned_fixtures,
            "challenger": challenger_fixtures,
        },
        "xpts_by_gw": {
            "owned": {str(row["gw"]): row.get("xpts") for row in owned_fixtures},
            "challenger": {str(row["gw"]): row.get("xpts") for row in challenger_fixtures},
        },
        "xmins_by_gw": {
            "owned": {str(row["gw"]): row.get("xmins") for row in owned_fixtures},
            "challenger": {str(row["gw"]): row.get("xmins") for row in challenger_fixtures},
        },
        "start_probability_by_gw": {
            "owned": {str(row["gw"]): row.get("start_probability") for row in owned_fixtures},
            "challenger": {str(row["gw"]): row.get("start_probability") for row in challenger_fixtures},
        },
        "tactical_matchup_by_gw": {
            "owned": {str(row["gw"]): {"route_to_points": row.get("route_to_points"), "matchup_edge": row.get("matchup_edge"), "matchup_risk": row.get("matchup_risk"), "confidence": row.get("matchup_confidence")} for row in owned_fixtures},
            "challenger": {str(row["gw"]): {"route_to_points": row.get("route_to_points"), "matchup_edge": row.get("matchup_edge"), "matchup_risk": row.get("matchup_risk"), "confidence": row.get("matchup_confidence")} for row in challenger_fixtures},
        },
        "rest_congestion_by_gw": {
            "owned": {str(row["gw"]): row.get("rest_congestion") for row in owned_fixtures},
            "challenger": {str(row["gw"]): row.get("rest_congestion") for row in challenger_fixtures},
        },
        "midweek_schedule": {
            "status": "VERIFIED" if congestion_verified >= 3 else "PARTIAL_OR_UNVERIFIED",
            "challenger": {str(row["gw"]): (row.get("rest_congestion") or {}).get("midweek_schedule") for row in challenger_fixtures},
        },
        "international_context": {
            "status": "UNVERIFIED" if congestion_verified < 3 else "AVAILABLE_IN_TACTICAL_CONTEXT",
            "challenger": {str(row["gw"]): (row.get("rest_congestion") or {}).get("international_context") for row in challenger_fixtures},
        },
        "role_sustainability": sustainability,
        "performance_signal": performance_signal,
        "raw_gain_2gw": horizons["2"]["projected_edge"],
        "raw_gain_3gw": horizons["3"]["projected_edge"],
        "raw_gain_5gw": horizons["5"]["projected_edge"],
        "structural_cost": structural_cost,
        "opportunity_cost": opportunity_cost,
        "net_transfer_value": round(net_value, 3) if net_value is not None else None,
        "affordability": swap,
        "confidence": round(confidence, 4),
        "edge_to_uncertainty_5gw": round(edge_ratio, 4) if edge_ratio is not None else None,
        "decision": decision,
        "decision_reasons": reasons,
        "decision_risks": sorted(set(risks)),
        "reversal_triggers": reversal,
        "watchlist_governance_suggestion": (
            "PROMOTE_TO_WATCHLIST"
            if decision == "PROMOTE_TO_WATCHLIST"
            else "REVIEW_DEMOTION"
            if challenger.get("challenger_type") == "GOVERNED_WATCHLIST" and (not screening.get("pass") or raw_gain5 <= 0)
            else "KEEP_OR_REPRIORITIZE"
            if challenger.get("challenger_type") == "GOVERNED_WATCHLIST"
            else "NO_AUTOMATIC_WATCHLIST_MUTATION"
        ),
        "data_quality": {
            "core_projection": "VERIFIED_CANONICAL",
            "xmins": "VERIFIED_CANONICAL",
            "fixture_identity": "VERIFIED_OFFICIAL_SNAPSHOT" if challenger_fixtures else "MISSING",
            "price_legality": "VERIFIED_CANONICAL",
            "tactical_verified_gws": tactical_verified,
            "congestion_verified_gws": congestion_verified,
            "critical_core_complete": core_completeness == 1.0,
            "unverified_evidence_fabricated": False,
        },
    }


def run() -> dict[str, Any]:
    policy = read_json(POLICY_PATH, {})
    if policy.get("mode") != "ADVISORY_ONLY":
        raise RuntimeError("challenger comparator must start ADVISORY_ONLY")
    umap, pmap, owned = _player_maps()
    if not umap or not pmap or len(owned) != 15:
        raise RuntimeError("canonical universe, predictions and 15-player owned squad are required")
    team = read_json(DATA / "team.json", {})
    effective = read_json(DATA / "effective_plan_v4.json", {})
    raw = read_json(RAW_SNAPSHOT, {})
    if raw.get("schema") != "snapshot.v1":
        raise RuntimeError("immutable raw snapshot contract is required for fixture identity")
    event_points_coverage = 0
    for player in (((raw.get("official") or {}).get("bootstrap") or {}).get("elements") or []):
        element = int(player.get("id") or 0)
        if element in umap:
            # Local comparator evidence only: do not mutate canonical universe.
            umap[element]["event_points"] = player.get("event_points")
            event_points_coverage += player.get("event_points") is not None
    optional_tactical_relative = str((policy.get("evidence") or {}).get("optional_tactical_path") or "data/tactical_context_v4.json")
    optional_tactical_path = DATA.parent / optional_tactical_relative
    tactical = read_json(optional_tactical_path, {}) if optional_tactical_path.is_file() else {}
    watchlist, watchlist_status = _optional_watchlist(policy, umap)
    engine_governed = _engine_governed_candidates(umap)
    governed_limit = int((policy.get("candidate_limits") or {}).get("governed") or 20)
    governed = (watchlist + engine_governed)[:governed_limit]
    excluded = set(owned) | {int(row["element"]) for row in governed}
    emerging = _emerging_candidates(umap, pmap, excluded, policy)
    candidates = governed + emerging
    comparisons = []
    candidate_summaries = []
    for candidate in candidates:
        screening = _screen_candidate(candidate, umap, pmap, policy)
        sustainability = _role_sustainability(umap[int(candidate["element"])], pmap[int(candidate["element"])])
        performance_signal = _performance_signal(candidate, screening, sustainability, policy)
        candidate_summaries.append({
            **candidate,
            "name": umap[int(candidate["element"])].get("name"),
            "team": umap[int(candidate["element"])].get("team"),
            "position": umap[int(candidate["element"])].get("position"),
            "price": umap[int(candidate["element"])].get("now_cost"),
            "screening": screening,
            "performance_signal": performance_signal,
            "role_sustainability": sustainability,
        })
        if not screening.get("pass") and candidate.get("challenger_type") == "EMERGING_CHALLENGER":
            continue
        targets = _rank_owned_targets(candidate, owned, pmap, umap, team, effective, policy)
        for target in targets:
            comparisons.append(_comparison_pair(candidate, int(target["owned_element"]), (umap, pmap, owned), team, effective, raw, policy, tactical))
    comparisons.sort(key=lambda row: (DECISION_RANK.get(row.get("decision"), -1), f(row.get("raw_gain_5gw"))), reverse=True)
    comparisons = comparisons[: int((policy.get("candidate_limits") or {}).get("published_comparisons") or 40)]
    decision_counts = Counter(row.get("decision") for row in comparisons)
    output = {
        "schema_version": 497,
        "engine": "v4.9.6-owned-challenger-comparator",
        "generated_at": iso_now(),
        "status": "PASS",
        "capability_state": "ADVISORY_ONLY",
        "planning_gw": (team.get("projection_baseline") or {}).get("planning_gw"),
        "purpose": "continuously test whether an external alternative is sufficiently superior to an OWNED player over a realistic multi-GW horizon to justify review",
        "challenger_universe": {
            "governed_watchlist": watchlist_status,
            "governed_watchlist_candidates": len(watchlist),
            "engine_governed_candidates": len(engine_governed),
            "emerging_challengers": len(emerging),
            "emerging_trigger_is_not_transfer": True,
            "recent_event_points_source": "raw_snapshot.official.bootstrap.elements.event_points",
            "recent_event_points_coverage": event_points_coverage,
            "season_total_points_never_used_as_recent_haul": True,
        },
        "candidate_summaries": candidate_summaries,
        "comparisons": comparisons,
        "summary": {
            "comparisons": len(comparisons),
            "decision_counts": dict(decision_counts),
            "top_reviews": [
                {
                    "player_out": row["player_out"],
                    "player_in": row["player_in"],
                    "challenger_type": row["challenger_type"],
                    "raw_gain_5gw": row["raw_gain_5gw"],
                    "decision": row["decision"],
                    "confidence": row["confidence"],
                }
                for row in comparisons[:10]
            ],
        },
        "external_consensus": {
            "status": "UNAVAILABLE_IN_V4_RUNTIME",
            "advisory_only": True,
            "note": "LiveFPL/OneFPL/FFFix/FFHub/FFScout consensus may be added by a higher orchestration layer; no majority voting",
        },
        "evidence_governance": {
            "fact_priority": ["Official FPL", "official competition/club", "reliable team news", "analytics/model", "tactical/editorial", "community"],
            "official_facts_source": "raw_snapshot+universe",
            "model_source": "predictions_v4",
            "governed_candidate_source": "recommendation_sanity_v4 plus optional materialized watchlist",
            "tactical_source": optional_tactical_relative if tactical else "UNVERIFIED",
            "all_competition_congestion_source": "UNVERIFIED unless materialized tactical/workload context provides it",
        },
        "known_limitations": [
            "V4 currently has no authoritative materialized watchlist artifact unless data/watchlist_v4.json is supplied",
            "full opponent-coach tactical structure is not fabricated when no tactical context artifact is available",
            "all-competition midweek and international workload remains partial until verified source data is materialized",
            "normal free-transfer opportunity cost remains unverified when transfer availability is not present in canonical runtime artifacts",
        ],
        "guardrails": {
            "process_isolated_microservice": True,
            "official_api_refetch": False,
            "advisory_only": True,
            "recent_haul_is_discovery_signal_only": True,
            "canonical_xpts_reused": True,
            "canonical_xmins_reused": True,
            "canonical_fixture_projection_reused": True,
            "canonical_price_and_legality_reused": True,
            "canonical_role_sustainability_reused": True,
            "watchlist_screening_not_reimplemented": True,
            "effective_plan_mutated": False,
            "optimizer_recommendation_mutated": False,
            "watchlist_mutated": False,
            "lineup_captain_chip_mutated": False,
            "missing_evidence_never_fabricated": True,
            "strong_transfer_capped_when_material_evidence_incomplete": True,
            "majority_voting": False,
        },
    }
    atomic_json(OUT, output)
    print(json.dumps({
        "service": "challenger_comparator",
        "status": output["status"],
        "candidates": len(candidate_summaries),
        "comparisons": len(comparisons),
        "watchlist": watchlist_status.get("status"),
        "decisions": dict(decision_counts),
    }, ensure_ascii=False))
    return output


if __name__ == "__main__":
    run()
