from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from typing import Any

from src.engines.fpl_rules_2026 import MAX_PER_CLUB
from src.engines.v4_official_fact_integrity import build_public_fact, official_snapshot_metadata
from src.engines.v4_wc_optimizer import build_candidates, reconcile_owned_costs
from src.utils import DATA, read_json


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _i(value: Any, default: int = -1) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def _require_policy(policy: dict[str, Any]) -> dict[str, Any]:
    cfg = policy.get("projected_value_market_discovery")
    if not isinstance(cfg, dict):
        raise RuntimeError("owned challenger policy missing projected_value_market_discovery")
    required = (
        "minimum_projected_value_score",
        "minimum_value_percentile",
        "minimum_start_probability",
        "football_edge_minimum_score",
        "structural_edge_minimum_5gw",
        "market_urgencies",
        "imminent_cycles",
        "visible_watchlist_per_position",
    )
    missing = [key for key in required if key not in cfg]
    if missing:
        raise RuntimeError(f"projected value discovery policy missing keys: {missing}")
    return cfg


def _avg_start(pred: dict[str, Any], horizon: int = 5) -> float | None:
    values = []
    for fixture in list(pred.get("fixtures") or [])[:horizon]:
        value = (fixture.get("xmins") or {}).get("start_probability")
        if value is not None:
            values.append(_f(value))
    return round(sum(values) / len(values), 4) if values else None


def _percentiles(values: dict[int, float]) -> dict[int, float]:
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    denominator = max(1, len(ordered) - 1)
    return {element: round(index / denominator, 4) for index, (element, _) in enumerate(ordered)}


def _official_maps(raw: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[int, str], dict[int, str], list[dict[str, Any]], dict[str, Any]]:
    official = raw.get("official") or {}
    bootstrap = official.get("bootstrap") or {}
    health = (raw.get("endpoint_health") or {}).get("bootstrap") or {}
    snapshot = official_snapshot_metadata(bootstrap, health)
    players = {int(row.get("id") or 0): row for row in bootstrap.get("elements") or [] if int(row.get("id") or 0) > 0}
    teams = {int(row.get("id") or 0): str(row.get("name") or row.get("short_name") or row.get("id")) for row in bootstrap.get("teams") or []}
    positions = {int(row.get("id") or 0): str(row.get("singular_name_short") or row.get("singular_name") or "") for row in bootstrap.get("element_types") or []}
    fixtures = list(official.get("fixtures") or [])
    return players, teams, positions, fixtures, snapshot


def _next_fixture(fixtures: list[dict[str, Any]], team_id: int, pred: dict[str, Any]) -> dict[str, Any] | None:
    projected = list(pred.get("fixtures") or [])
    projected_event = _i((projected[0] if projected else {}).get("event"), 0)
    candidates = [
        row for row in fixtures
        if _i(row.get("event"), 0) == projected_event
        and team_id in {_i(row.get("team_h"), 0), _i(row.get("team_a"), 0)}
    ]
    if not candidates:
        return None
    fixture = candidates[0]
    opponent = _i(fixture.get("team_a"), 0) if _i(fixture.get("team_h"), 0) == team_id else _i(fixture.get("team_h"), 0)
    return {
        "event": _i(fixture.get("event"), 0),
        "fixture_id": _i(fixture.get("id"), 0),
        "opponent_team_id": opponent,
        "home": _i(fixture.get("team_h"), 0) == team_id,
        "kickoff_time": fixture.get("kickoff_time"),
        "source": "raw_snapshot.official.fixtures",
    }


def _identity_sanity(
    element: int,
    *,
    local: dict[str, Any],
    price: dict[str, Any],
    official_player: dict[str, Any] | None,
    teams: dict[int, str],
    positions: dict[int, str],
    snapshot: dict[str, Any],
    fixtures: list[dict[str, Any]],
    pred: dict[str, Any],
) -> dict[str, Any]:
    if official_player is None or snapshot.get("freshness") != "FRESH":
        return {"status": "BLOCKED", "element": element, "reason": "FRESH_OFFICIAL_IDENTITY_UNAVAILABLE", "repairs": []}
    official_fact = build_public_fact(official_player, teams, positions, snapshot)
    required = ("element_id", "name", "team_id", "position", "now_cost", "ownership", "status")
    missing = [key for key in required if official_fact.get(key) in (None, "")]
    if missing:
        return {"status": "BLOCKED", "element": element, "reason": "OFFICIAL_IDENTITY_INCOMPLETE", "missing": missing, "repairs": []}

    price_errors = []
    expected_price = {
        "element_id": int(official_fact["element_id"]),
        "team_id": int(official_fact["team_id"]),
        "position": str(official_fact["position"]),
        "now_cost": int(official_fact["now_cost"]),
    }
    for key, expected in expected_price.items():
        actual = price.get(key)
        if key == "element_id":
            actual = price.get("element_id", price.get("element"))
        if key == "now_cost":
            actual = price.get("now_cost")
        if actual is None or str(actual) != str(expected):
            price_errors.append({"field": key, "expected": expected, "actual": actual})
    if price_errors:
        return {
            "status": "TAINTED_BLOCKED",
            "element": element,
            "reason": "OFFICIAL_PRICE_IDENTITY_MISMATCH",
            "mismatches": price_errors,
            "official_fact": official_fact,
            "repairs": [],
        }

    local_map = {
        "name": local.get("name"),
        "team_id": local.get("team_id"),
        "position": local.get("position"),
        "now_cost": local.get("now_cost"),
        "ownership": local.get("ownership"),
        "status": local.get("status"),
    }
    repairs = []
    for key in ("name", "team_id", "position", "now_cost", "ownership", "status"):
        official_value = official_fact.get(key)
        local_value = local_map.get(key)
        if local_value is not None and str(local_value) != str(official_value):
            repairs.append({"field": key, "stale_local": local_value, "official": official_value})

    fixture = _next_fixture(fixtures, int(official_fact["team_id"]), pred)
    if fixture is None:
        return {
            "status": "TAINTED_BLOCKED",
            "element": element,
            "reason": "OFFICIAL_FIXTURE_OPPONENT_MAPPING_MISSING",
            "official_fact": official_fact,
            "repairs": repairs,
        }
    return {
        "status": "PASS_REPAIRED" if repairs else "PASS",
        "element": element,
        "reason": None,
        "official_fact": official_fact,
        "fixture": fixture,
        "repairs": repairs,
        "official_snapshot_id": snapshot.get("source_snapshot_id"),
    }


def _market_state(price: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    fresh = (
        str(price.get("freshness_state") or "").upper() == "FRESH"
        and str(price.get("evidence_state") or "").upper() not in {"STALE", "FIELD_MISSING", "SCHEMA_CHANGED"}
        and str(price.get("source") or "").upper() == "OFFICIAL_FPL"
    )
    imminent = (
        fresh
        and str(price.get("direction") or "").upper() == "RISE"
        and str(price.get("model_urgency") or "").upper() in {str(v).upper() for v in cfg["market_urgencies"]}
        and str(price.get("predicted_change_cycle") or "").upper() in {str(v).upper() for v in cfg["imminent_cycles"]}
    )
    return {
        "fresh": fresh,
        "imminent_rise": imminent,
        "direction": price.get("direction"),
        "progress_percent": price.get("current_progress_percent"),
        "trajectory": price.get("trajectory_basis"),
        "predicted_change_cycle": price.get("predicted_change_cycle"),
        "predicted_change_at": price.get("predicted_change_at"),
        "next_official_price_update_at": price.get("next_official_price_update_at"),
        "eta_human": price.get("eta_human"),
        "urgency": price.get("model_urgency"),
        "confidence": price.get("confidence"),
        "freshness_state": price.get("freshness_state"),
        "evidence_state": price.get("evidence_state"),
        "confirmed_price_change": price.get("confirmed_price_change"),
        "timing_only_not_football_authority": True,
    }


def _club_legal(owned_facts: list[dict[str, Any]], outgoing_id: int, incoming_team: int) -> bool:
    counts = Counter(int(row.get("team_id") or 0) for row in owned_facts)
    outgoing = next((row for row in owned_facts if int(row.get("element") or 0) == outgoing_id), None)
    if outgoing is None:
        return False
    counts[int(outgoing.get("team_id") or 0)] -= 1
    counts[incoming_team] += 1
    return max(counts.values(), default=0) <= MAX_PER_CLUB


def discover(
    *,
    predictions: dict[str, Any],
    universe: dict[str, Any],
    prices: dict[str, Any],
    raw_snapshot: dict[str, Any],
    team: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    cfg = _require_policy(policy)
    pmap = {int(row.get("element") or 0): row for row in predictions.get("players") or [] if int(row.get("element") or 0) > 0}
    umap = {int(row.get("element") or row.get("element_id") or 0): row for row in universe.get("players") or [] if int(row.get("element") or row.get("element_id") or 0) > 0}
    price_map = {int(row.get("element_id") or row.get("element") or 0): row for row in prices.get("players") or [] if int(row.get("element_id") or row.get("element") or 0) > 0}
    official_players, teams, positions, fixtures, snapshot = _official_maps(raw_snapshot)
    owned_ids = {int(row.get("element") or 0) for row in team.get("squad") or [] if int(row.get("element") or 0) > 0}
    ledger = {int(row.get("element") or 0): row for row in team.get("team_value_ledger") or []}
    bank = _i((team.get("totals") or {}).get("itb_tenths"), _i(team.get("itb_tenths"), 0))

    owned_facts = []
    for element in sorted(owned_ids):
        raw_player = official_players.get(element)
        if raw_player:
            owned_facts.append(build_public_fact(raw_player, teams, positions, snapshot))

    provisional: list[dict[str, Any]] = []
    grouped_metric: dict[str, dict[str, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    for element, pred in pmap.items():
        if element in owned_ids:
            continue
        local = umap.get(element) or {}
        price = price_map.get(element) or {}
        identity = _identity_sanity(
            element,
            local=local,
            price=price,
            official_player=official_players.get(element),
            teams=teams,
            positions=positions,
            snapshot=snapshot,
            fixtures=fixtures,
            pred=pred,
        )
        fact = identity.get("official_fact") or {}
        position = str(fact.get("position") or local.get("position") or pred.get("position") or "")
        if position not in {"GK", "DEF", "MID", "FWD"}:
            continue
        x3, x5, x10, x15 = (_f(pred.get(key)) for key in ("xpts_3", "xpts_5", "xpts_10", "xpts_15"))
        cost = _i(fact.get("now_cost"), _i(local.get("now_cost"), 0))
        start = _avg_start(pred)
        uncertainty = max(0.0, _f(pred.get("uncertainty")))
        horizon_rate = 0.25 * (x3 / 3.0) + 0.45 * (x5 / 5.0) + 0.15 * (x10 / 10.0) + 0.15 * (x15 / 15.0)
        value_per_m = x5 / max(0.1, cost / 10.0)
        grouped_metric[position]["horizon"][element] = horizon_rate
        grouped_metric[position]["value"][element] = value_per_m
        grouped_metric[position]["uncertainty"][element] = uncertainty
        provisional.append({
            "element": element,
            "position": position,
            "pred": pred,
            "identity": identity,
            "official_fact": fact,
            "price": price,
            "xpts": {"3": round(x3, 3), "5": round(x5, 3), "10": round(x10, 3), "15": round(x15, 3)},
            "start_probability": start,
            "uncertainty": uncertainty,
            "horizon_rate": horizon_rate,
            "value_per_million_5gw": value_per_m,
        })

    percentiles: dict[str, dict[str, dict[int, float]]] = defaultdict(dict)
    for position, metrics in grouped_metric.items():
        for key, values in metrics.items():
            percentiles[position][key] = _percentiles(values)

    rows = []
    for row in provisional:
        element, position = row["element"], row["position"]
        value_pct = percentiles[position]["value"].get(element, 0.0)
        horizon_pct = percentiles[position]["horizon"].get(element, 0.0)
        unc_pct = percentiles[position]["uncertainty"].get(element, 0.0)
        start = row["start_probability"] if row["start_probability"] is not None else 0.0
        score = 0.40 * value_pct + 0.35 * horizon_pct + 0.20 * start + 0.05 * (1.0 - unc_pct)
        market = _market_state(row["price"], cfg)
        identity_ok = str((row["identity"] or {}).get("status") or "").startswith("PASS")
        projected_material = (
            identity_ok
            and score >= _f(cfg["minimum_projected_value_score"])
            and value_pct >= _f(cfg["minimum_value_percentile"])
            and start >= _f(cfg["minimum_start_probability"])
        )

        relevant_owned = []
        for owned in owned_facts:
            if owned.get("position") != position:
                continue
            owned_id = int(owned["element"])
            owned_pred = pmap.get(owned_id) or {}
            sell = _i((ledger.get(owned_id) or {}).get("sell_cost"), -1)
            incoming_cost = _i((row["official_fact"] or {}).get("now_cost"), -1)
            affordable = sell >= 0 and incoming_cost >= 0 and incoming_cost <= sell + bank
            legal = _club_legal(owned_facts, owned_id, _i((row["official_fact"] or {}).get("team_id"), 0))
            edge5 = _f((row["xpts"] or {}).get("5")) - _f(owned_pred.get("xpts_5"))
            relevant_owned.append({
                "element": owned_id,
                "name": owned.get("name"),
                "affordable": affordable,
                "club_limit_legal": legal,
                "edge_5gw": round(edge5, 3),
            })
        structural = any(
            item["affordable"] and item["club_limit_legal"] and item["edge_5gw"] >= _f(cfg["structural_edge_minimum_5gw"])
            for item in relevant_owned
        )
        football_edge = identity_ok and score >= _f(cfg["football_edge_minimum_score"]) and start >= _f(cfg["minimum_start_probability"])
        mandatory = projected_material and market["imminent_rise"]
        routes = []
        if football_edge:
            routes.append("FOOTBALL_EDGE")
        if mandatory:
            routes.append("VALUE_MARKET_URGENCY")
        if structural:
            routes.append("STRUCTURAL_EDGE")
        market_only_rejected = market["imminent_rise"] and not projected_material and not football_edge
        state = "MANDATORY_CHALLENGER_REVIEW" if mandatory else "EMERGING_CHALLENGER" if routes else "DISCOVERED"
        rows.append({
            "element": element,
            "name": (row["official_fact"] or {}).get("name"),
            "team_id": (row["official_fact"] or {}).get("team_id"),
            "position": position,
            "now_cost": (row["official_fact"] or {}).get("now_cost"),
            "ownership": (row["official_fact"] or {}).get("ownership"),
            "status": (row["official_fact"] or {}).get("status"),
            "identity_sanity": row["identity"],
            "projected_value": {
                "score": round(score, 4),
                "position_value_percentile": value_pct,
                "position_horizon_percentile": horizon_pct,
                "position_uncertainty_percentile": unc_pct,
                "value_per_million_5gw": round(row["value_per_million_5gw"], 4),
                "horizon_rate": round(row["horizon_rate"], 4),
                "start_probability": row["start_probability"],
                "uncertainty": row["uncertainty"],
                "xpts": row["xpts"],
                "position_budget_aware": True,
                "opaque_score_forbidden": True,
            },
            "market": market,
            "routes": routes,
            "mandatory_review": mandatory,
            "market_only_rejected": market_only_rejected,
            "relevant_owned": relevant_owned,
            "state": state,
            "price_signal_can_authorize_transfer": False,
        })

    rows.sort(key=lambda item: (bool(item["mandatory_review"]), _f((item["projected_value"] or {}).get("score")), _f((item["projected_value"] or {}).get("value_per_million_5gw"))), reverse=True)
    mandatory_ids = [int(row["element"]) for row in rows if row["mandatory_review"]]
    discoverable_ids = [int(row["element"]) for row in rows if row["routes"]]
    tainted = [int(row["element"]) for row in rows if not str((row["identity_sanity"] or {}).get("status") or "").startswith("PASS")]
    return {
        "contract": "V4_PROJECTED_VALUE_MARKET_DISCOVERY_V1",
        "full_universe_scanned": True,
        "eligible_non_owned_count": len(rows),
        "identity_pass_count": len(rows) - len(tainted),
        "tainted_or_blocked_count": len(tainted),
        "tainted_or_blocked_elements": tainted,
        "mandatory_candidate_ids": mandatory_ids,
        "discoverable_candidate_ids": discoverable_ids,
        "candidates": rows,
        "market_timing_is_not_football_authority": True,
        "mandatory_review_is_not_automatic_buy": True,
        "official_identity_source": "raw_snapshot.official.bootstrap+fixtures",
        "official_snapshot_id": snapshot.get("source_snapshot_id"),
        "policy": {
            "minimum_projected_value_score": cfg["minimum_projected_value_score"],
            "minimum_value_percentile": cfg["minimum_value_percentile"],
            "minimum_start_probability": cfg["minimum_start_probability"],
            "football_edge_minimum_score": cfg["football_edge_minimum_score"],
            "structural_edge_minimum_5gw": cfg["structural_edge_minimum_5gw"],
            "market_urgencies": cfg["market_urgencies"],
            "imminent_cycles": cfg["imminent_cycles"],
        },
    }


def rerank_visible_watchlist(
    tactical: dict[str, Any],
    *,
    discovery: dict[str, Any],
    predictions: dict[str, Any],
    universe: dict[str, Any],
    external: dict[str, Any] | None = None,
    per_position: int = 5,
) -> dict[str, Any]:
    from src.engines.v4_tactical_serving import _compact_tactical

    pmap = {int(row.get("element") or 0): row for row in predictions.get("players") or [] if int(row.get("element") or 0) > 0}
    umap = {int(row.get("element") or 0): row for row in universe.get("players") or [] if int(row.get("element") or 0) > 0}
    external = external if external is not None else read_json(DATA / "tactical_external_evidence.json", {})
    current = list(tactical.get("watchlist") or [])
    current_ids = {int(row.get("element") or 0) for row in current}
    candidate_by_id = {int(row["element"]): row for row in discovery.get("candidates") or []}
    selected: list[dict[str, Any]] = []
    exited: list[int] = []

    for position in ("GK", "DEF", "MID", "FWD"):
        existing = [row for row in current if row.get("position") == position]
        mandatory = [
            row for row in discovery.get("candidates") or []
            if row.get("position") == position and row.get("mandatory_review") and str((row.get("identity_sanity") or {}).get("status") or "").startswith("PASS")
        ]
        mandatory.sort(key=lambda row: (_f((row.get("projected_value") or {}).get("score")), _f((row.get("projected_value") or {}).get("value_per_million_5gw"))), reverse=True)
        mandatory_ids = [int(row["element"]) for row in mandatory[:per_position]]
        remaining_existing = [row for row in existing if int(row.get("element") or 0) not in mandatory_ids]
        remaining_existing.sort(key=lambda row: (_f(row.get("score")), _f(row.get("xpts_5"))), reverse=True)
        chosen_ids = mandatory_ids + [int(row.get("element") or 0) for row in remaining_existing[: max(0, per_position - len(mandatory_ids))]]
        if len(chosen_ids) != per_position:
            raise RuntimeError(f"projected-value watchlist rerank requires exactly {per_position} {position}")
        exited.extend(int(row.get("element") or 0) for row in existing if int(row.get("element") or 0) not in chosen_ids)

        existing_map = {int(row.get("element") or 0): row for row in existing}
        for element in chosen_ids:
            if element in existing_map:
                row = dict(existing_map[element])
                if element in mandatory_ids:
                    row["mandatory_challenger_review"] = True
                    row["entry_reason"] = "PROJECTED_VALUE_PLUS_FRESH_MARKET_URGENCY"
                    row["projected_value_market"] = candidate_by_id.get(element)
                selected.append(row)
                continue
            discovered = candidate_by_id[element]
            fact = dict((discovered.get("identity_sanity") or {}).get("official_fact") or {})
            pred = pmap.get(element) or {}
            uni = umap.get(element) or fact
            selected.append({
                **fact,
                "score": round(_f((discovered.get("projected_value") or {}).get("score")), 4),
                "xpts_5": round(_f(pred.get("xpts_5")), 3),
                "xpts_15": round(_f(pred.get("xpts_15")), 3),
                "start_probability_5": _avg_start(pred),
                "uncertainty": round(_f(pred.get("uncertainty")), 4),
                "selection_basis": "projected_value+mandatory_market_review",
                "tactical_signal_used_for_promotion": False,
                "lifecycle": "NEW",
                "entry_reason": "PROJECTED_VALUE_PLUS_FRESH_MARKET_URGENCY",
                "exit_reason": None,
                "mandatory_challenger_review": True,
                "projected_value_market": discovered,
                "tactical": _compact_tactical(pred, uni, external),
            })

    if len(selected) != per_position * 4:
        raise RuntimeError("projected-value watchlist rerank must preserve exact 20 visible candidates")
    tactical = dict(tactical)
    tactical["watchlist"] = selected
    tactical["exited_watchlist_elements"] = sorted(set((tactical.get("exited_watchlist_elements") or []) + exited))
    tactical["counts"] = {
        **(tactical.get("counts") or {}),
        "watchlist": len(selected),
        **{position: sum(row.get("position") == position for row in selected) for position in ("GK", "DEF", "MID", "FWD")},
    }
    tactical["projected_value_market_discovery"] = discovery
    tactical.setdefault("guardrails", {}).update({
        "projected_value_market_full_universe_scan": True,
        "mandatory_market_review_can_displace_stale_watchlist_member": True,
        "visible_watchlist_cardinality_preserved": True,
        "market_priority_does_not_authorize_transfer": True,
        "mandatory_review_is_not_automatic_buy": True,
    })
    return tactical


def augment_challenger(
    challenger: dict[str, Any],
    *,
    discovery: dict[str, Any],
    predictions: dict[str, Any],
    universe: dict[str, Any],
    team: dict[str, Any],
    latest: dict[str, Any],
    tactical: dict[str, Any],
    prices: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    from src.services import owned_challenger_decision_service as base

    configured_lock = read_json(DATA.parent / "config" / "locked_squad.json", {})
    locked = base.effective_planning_squad(team, configured_lock, latest)
    candidates = build_candidates(predictions, universe)
    effective_candidates, affordability = reconcile_owned_costs(candidates, locked)
    cmap = {row.element: row for row in effective_candidates}
    pmap = base._prediction_map(predictions)
    price_map = base._price_map(prices)
    tactical_owned, tactical_watch = base._tactical_maps(tactical)
    owned_ids = {int(row.get("element") or 0) for row in locked.get("players") or []}
    owned_candidates = [cmap[element] for element in sorted(owned_ids) if element in cmap]
    all_packages = base._package_rows(read_json(DATA / "wc_package_audit_v4.json", {}))
    single_packages = base._single_package_map(all_packages)
    wildcard_active = bool(locked.get("wildcard_active"))
    free_transfers = base._free_transfer_evidence(team, latest)
    bank = _i(affordability.get("bank_tenths"), _i(locked.get("itb_tenths"), 0))
    existing_pairs = {
        (int((row.get("player_out") or {}).get("element") or 0), int((row.get("player_in") or {}).get("element") or 0))
        for row in challenger.get("comparisons") or []
    }
    comparisons = list(challenger.get("comparisons") or [])
    evaluated_mandatory: set[int] = set()
    candidate_rows = {int(row["element"]): row for row in discovery.get("candidates") or []}

    for incoming_id in discovery.get("mandatory_candidate_ids") or []:
        discovered = candidate_rows.get(int(incoming_id)) or {}
        identity = discovered.get("identity_sanity") or {}
        if not str(identity.get("status") or "").startswith("PASS"):
            continue
        incoming = cmap.get(int(incoming_id))
        if incoming is None:
            continue
        fact = identity.get("official_fact") or {}
        incoming = replace(
            incoming,
            name=str(fact.get("name") or incoming.name),
            team_id=_i(fact.get("team_id"), incoming.team_id),
            team=str(fact.get("team") or incoming.team),
            position=str(fact.get("position") or incoming.position),
            cost=_i(fact.get("now_cost"), incoming.cost),
        )
        compared = False
        for outgoing in owned_candidates:
            if outgoing.position != incoming.position:
                continue
            pair = (outgoing.element, incoming.element)
            if pair in existing_pairs:
                compared = True
                continue
            row = base._compare(
                outgoing,
                incoming,
                challenger_type="MANDATORY_CHALLENGER_REVIEW",
                triggers=["PROJECTED_VALUE", "FRESH_MARKET_URGENCY"],
                sustainable=True,
                owned_candidates=owned_candidates,
                bank=bank,
                pmap=pmap,
                tactical_owned=tactical_owned,
                tactical_watch=tactical_watch,
                prices=price_map,
                single_packages=single_packages,
                wildcard_active=wildcard_active,
                free_transfers=free_transfers,
            )
            row["projected_value_market"] = discovered
            row["mandatory_review"] = True
            if row.get("decision") == "CHANGE":
                row["decision"] = "REVIEW_NOW"
                row["state"] = "REVIEW_NOW"
                row.setdefault("blockers", []).append("CROSS_ENGINE_CONFIRMATION_REQUIRED")
                row["reason"] = "V4 mandatory challenger is material, but V4 alone cannot be the final cross-engine winner."
            comparisons.append(row)
            existing_pairs.add(pair)
            compared = True
        if compared:
            evaluated_mandatory.add(int(incoming_id))

    missing = sorted(set(int(v) for v in discovery.get("mandatory_candidate_ids") or []) - evaluated_mandatory)
    publish_cfg = policy.get("publication") or {}
    challenger = dict(challenger)
    challenger["comparisons"] = comparisons
    challenger["comparison_count"] = len(comparisons)
    challenger["owned_screening"] = base._owned_screening(owned_candidates, pmap, comparisons, price_map)
    challenger["main_transfer_battles"] = base._main_battles(comparisons, _i(publish_cfg.get("max_main_transfer_battles"), 8))
    challenger["projected_value_market_discovery"] = {
        **discovery,
        "evaluated_mandatory_candidate_ids": sorted(evaluated_mandatory),
        "missing_mandatory_candidate_ids": missing,
        "mandatory_candidate_coverage_complete": not missing,
        "v4_leading_challenger_not_final_cross_engine_winner": True,
    }
    if discovery.get("mandatory_candidate_ids") and challenger.get("challenge_signal") in {"NO_TRANSFER_RECOMMENDED", "HOLD", "REVIEW"}:
        challenger["challenge_signal"] = "REVIEW_NOW"
    challenger.setdefault("publication", {}).update({
        "full_universe_projected_value_market_scan": True,
        "mandatory_candidate_coverage_complete": not missing,
        "missing_mandatory_candidate_blocks_publication": True,
        "market_urgency_timing_only": True,
    })
    challenger.setdefault("provenance", {}).update({
        "projected_value_market_discovery": "tactical_serving_v4.projected_value_market_discovery",
        "full_universe_rescan": False,
    })
    return challenger
