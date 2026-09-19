from __future__ import annotations

"""P1.2A V12-native exact package search.

SEARCH != DECISION UTILITY.

This module owns only deterministic route existence, final-squad legality,
authenticated affordability semantics, coverage truth, execution-only batching/
sharding, and representation-only search frontier metadata. It intentionally
does not import or implement canonical player scoring, horizons, FT shadow
value, WAIT/PREPARE/ACT, Monte Carlo, or mini-league logic.
"""

from collections import Counter
from functools import lru_cache
from itertools import combinations, product
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.rules import RULESET_ID, SQUAD_RULES

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "v12_package_search.json"
MODEL_OWNER = "V12_PACKAGE_SEARCH"
POSITIONS = ("GK", "DEF", "MID", "FWD")
POSITION_ORDER = {position: index for index, position in enumerate(POSITIONS)}


class PackageSearchError(ValueError):
    pass


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "V12_EXACT_PACKAGE_SEARCH_V1":
        raise PackageSearchError("P1.2A search contract drift")
    if payload.get("model_owner") != MODEL_OWNER:
        raise PackageSearchError("P1.2A search owner drift")
    governance = payload.get("governance") or {}
    forbidden = (
        "decision_scores_forbidden",
        "horizon_utility_forbidden",
        "ft_shadow_forbidden",
        "canonical_weights_forbidden",
        "mini_league_forbidden",
        "monte_carlo_forbidden",
        "legacy_fixed_change_penalty_forbidden",
    )
    if not all(governance.get(key) is True for key in forbidden):
        raise PackageSearchError("P1.2A methodology boundary drift")
    return payload


def _int(value: Any, *, label: str, allow_zero: bool = True) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise PackageSearchError(f"{label} must be integer") from exc
    if out < 0 or (not allow_zero and out <= 0):
        raise PackageSearchError(f"{label} out of range")
    return out


def _position(value: Any) -> str:
    out = str(value or "").upper()
    if out not in POSITIONS:
        raise PackageSearchError(f"unsupported position: {out!r}")
    return out


def _element(row: Mapping[str, Any]) -> int:
    return _int(row.get("element"), label="element", allow_zero=False)


def _team_id(row: Mapping[str, Any]) -> int:
    return _int(row.get("team_id"), label="team_id", allow_zero=False)


def _buy_price(row: Mapping[str, Any]) -> int:
    if row.get("now_cost") is None:
        raise PackageSearchError(f"missing official current price for element={_element(row)}")
    return _int(row.get("now_cost"), label="now_cost")


def _sell_value(row: Mapping[str, Any]) -> int | None:
    # Authenticated team ledgers historically expose sell_cost. P1.2A accepts
    # the explicit sell_value alias too, but never falls back to now_cost.
    value = row.get("sell_value")
    if value is None:
        value = row.get("sell_cost")
    if value is None:
        return None
    return _int(value, label="sell_value")


def _normalized_player(row: Mapping[str, Any], *, owned: bool) -> dict[str, Any]:
    normalized = {
        "element": _element(row),
        "position": _position(row.get("position")),
        "team_id": _team_id(row),
        "now_cost": _buy_price(row),
    }
    if row.get("name") is not None:
        normalized["name"] = row.get("name")
    if row.get("status") is not None:
        normalized["status"] = str(row.get("status"))
    if row.get("eligible") is not None:
        normalized["eligible"] = bool(row.get("eligible"))
    if owned:
        normalized["sell_value"] = _sell_value(row)
        normalized["sell_value_resolved"] = normalized["sell_value"] is not None
    return normalized


def legal_squad(rows: Sequence[Mapping[str, Any]]) -> tuple[bool, str]:
    expected_size = int(SQUAD_RULES.get("squad_size") or 15)
    expected_positions = {
        str(position): int(count)
        for position, count in (SQUAD_RULES.get("position_counts") or {}).items()
    }
    max_club = int(SQUAD_RULES.get("max_players_per_club") or 3)
    if len(rows) != expected_size:
        return False, "SQUAD_SIZE"
    ids = [_element(row) for row in rows]
    if len(ids) != len(set(ids)):
        return False, "DUPLICATE_PLAYER"
    counts = Counter(_position(row.get("position")) for row in rows)
    if dict(counts) != expected_positions:
        return False, "POSITION_COMPOSITION"
    clubs = Counter(_team_id(row) for row in rows)
    if clubs and max(clubs.values()) > max_club:
        return False, "MAX_THREE_PER_CLUB"
    return True, "PASS"


def _eligible_candidates(
    universe: Sequence[Mapping[str, Any]],
    *,
    owned_ids: set[int],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    cfg = load_config()
    eligibility = cfg.get("candidate_eligibility") or {}
    allowed_statuses = {str(value) for value in eligibility.get("allowed_statuses") or []}
    rows: list[dict[str, Any]] = []
    counts = {
        "supplied_universe_count": 0,
        "owned_excluded_count": 0,
        "ineligible_excluded_count": 0,
        "invalid_excluded_count": 0,
    }
    seen: set[int] = set()
    for raw in universe:
        counts["supplied_universe_count"] += 1
        try:
            row = _normalized_player(raw, owned=False)
        except PackageSearchError:
            counts["invalid_excluded_count"] += 1
            continue
        element = int(row["element"])
        if element in seen:
            counts["invalid_excluded_count"] += 1
            continue
        seen.add(element)
        if element in owned_ids:
            counts["owned_excluded_count"] += 1
            continue
        if raw.get("eligible") is False:
            counts["ineligible_excluded_count"] += 1
            continue
        if allowed_statuses and raw.get("status") is not None and str(raw.get("status")) not in allowed_statuses:
            counts["ineligible_excluded_count"] += 1
            continue
        rows.append(row)
    rows.sort(
        key=lambda row: (
            POSITION_ORDER[str(row["position"])],
            int(row["team_id"]),
            int(row["now_cost"]),
            int(row["element"]),
        )
    )
    return rows, counts


def _position_multiset(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, int], ...]:
    counts = Counter(_position(row.get("position")) for row in rows)
    return tuple((position, counts.get(position, 0)) for position in POSITIONS if counts.get(position, 0))


def _incoming_sets_for_outs(
    candidates_by_position: Mapping[str, Sequence[Mapping[str, Any]]],
    outs: Sequence[Mapping[str, Any]],
) -> Iterable[tuple[dict[str, Any], ...]]:
    """Lossless enumeration under exact final 2/5/5/3 composition.

    Because the current squad is legal, any legal k-in/k-out final squad must
    replace the exact outgoing positional multiset.
    """
    position_counts = dict(_position_multiset(outs))
    groups: list[list[tuple[dict[str, Any], ...]]] = []
    for position in POSITIONS:
        count = int(position_counts.get(position, 0))
        if count <= 0:
            continue
        pool = [dict(row) for row in candidates_by_position.get(position, ())]
        groups.append(list(combinations(pool, count)))
    if not groups:
        yield ()
        return
    for grouped in product(*groups):
        flat: list[dict[str, Any]] = []
        for part in grouped:
            flat.extend(part)
        if len({_element(row) for row in flat}) != len(flat):
            continue
        flat.sort(key=lambda row: (POSITION_ORDER[str(row["position"])], int(row["element"])))
        yield tuple(flat)


def _route_id(outs: Sequence[Mapping[str, Any]], ins: Sequence[Mapping[str, Any]]) -> str:
    if not outs and not ins:
        return "HOLD"
    out_ids = ",".join(str(value) for value in sorted(_element(row) for row in outs))
    in_ids = ",".join(str(value) for value in sorted(_element(row) for row in ins))
    return f"{len(outs)}:{out_ids}->{in_ids}"


def _clubs_after(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(_team_id(row) for row in rows)
    return {str(team_id): int(counts[team_id]) for team_id in sorted(counts)}


def _economics(
    outs: Sequence[Mapping[str, Any]],
    ins: Sequence[Mapping[str, Any]],
    *,
    bank_before: int,
) -> dict[str, Any]:
    sell_values = [_sell_value(row) for row in outs]
    gross_buy = sum(_buy_price(row) for row in ins)
    unresolved = [int(_element(row)) for row, value in zip(outs, sell_values) if value is None]
    if unresolved:
        return {
            "status": "UNRESOLVED_SELL_VALUE",
            "gross_buy_cost": gross_buy,
            "gross_sell_value": None,
            "bank_before": bank_before,
            "bank_after": None,
            "affordable": None,
            "unresolved_sell_value_elements": unresolved,
            "sell_value_fallback_to_market_price": False,
        }
    gross_sell = sum(int(value) for value in sell_values if value is not None)
    bank_after = int(bank_before) + gross_sell - gross_buy
    return {
        "status": "RESOLVED",
        "gross_buy_cost": gross_buy,
        "gross_sell_value": gross_sell,
        "bank_before": bank_before,
        "bank_after": bank_after,
        "affordable": bank_after >= 0,
        "unresolved_sell_value_elements": [],
        "sell_value_fallback_to_market_price": False,
    }


def _route(
    current: Sequence[Mapping[str, Any]],
    outs: Sequence[Mapping[str, Any]],
    ins: Sequence[Mapping[str, Any]],
    *,
    bank_before: int,
) -> dict[str, Any] | None:
    out_ids = {_element(row) for row in outs}
    final_rows = [dict(row) for row in current if _element(row) not in out_ids]
    final_rows.extend(dict(row) for row in ins)
    structural_legal, reason = legal_squad(final_rows)
    if not structural_legal:
        return None
    economics = _economics(outs, ins, bank_before=bank_before)
    route_id = _route_id(outs, ins)
    positions = {
        position: int(count)
        for position, count in _position_multiset(outs)
    }
    return {
        "route_id": route_id,
        "classification": "HOLD" if route_id == "HOLD" else "CHANGE",
        "players_out": [
            {
                "element": _element(row),
                "position": _position(row.get("position")),
                "club": _team_id(row),
                "sell_value": _sell_value(row),
            }
            for row in sorted(outs, key=lambda row: _element(row))
        ],
        "players_in": [
            {
                "element": _element(row),
                "position": _position(row.get("position")),
                "club": _team_id(row),
                "buy_price": _buy_price(row),
            }
            for row in sorted(ins, key=lambda row: _element(row))
        ],
        "transfer_count": len(outs),
        "positions_changed": positions,
        "clubs_after": _clubs_after(final_rows),
        "gross_buy_cost": economics["gross_buy_cost"],
        "gross_sell_value": economics["gross_sell_value"],
        "bank_before": economics["bank_before"],
        "bank_after": economics["bank_after"],
        "affordable": economics["affordable"],
        "economics_status": economics["status"],
        "unresolved_sell_value_elements": economics["unresolved_sell_value_elements"],
        "legal": True,
        "legality_reason": reason,
        "ruleset_id": RULESET_ID,
        "final_squad_elements": sorted(_element(row) for row in final_rows),
        "sell_value_fallback_to_market_price": False,
    }


def _enumerate_exact(
    current: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    *,
    bank_before: int,
    max_transfers: int,
    shard_index: int = 0,
    shard_count: int = 1,
) -> list[dict[str, Any]]:
    if shard_count <= 0 or shard_index < 0 or shard_index >= shard_count:
        raise PackageSearchError("invalid shard specification")
    current_rows = [dict(row) for row in current]
    candidates_by_position = {
        position: [dict(row) for row in candidates if _position(row.get("position")) == position]
        for position in POSITIONS
    }
    routes: list[dict[str, Any]] = []
    if shard_index == 0:
        hold = _route(current_rows, (), (), bank_before=bank_before)
        if hold is None:
            raise PackageSearchError("HOLD route unexpectedly illegal")
        routes.append(hold)

    ordinal = 0
    for transfer_count in range(1, max_transfers + 1):
        for outs in combinations(current_rows, transfer_count):
            assigned_shard = ordinal % shard_count
            ordinal += 1
            if assigned_shard != shard_index:
                continue
            for ins in _incoming_sets_for_outs(candidates_by_position, outs):
                if len(ins) != transfer_count:
                    continue
                route = _route(current_rows, outs, ins, bank_before=bank_before)
                if route is not None:
                    routes.append(route)
    routes.sort(key=lambda row: (int(row["transfer_count"]), str(row["route_id"])))
    return routes


def enumerate_routes_scalar(
    current_squad: Sequence[Mapping[str, Any]],
    candidate_universe: Sequence[Mapping[str, Any]],
    *,
    bank: int,
    max_transfers: int,
) -> list[dict[str, Any]]:
    current = [_normalized_player(row, owned=True) for row in current_squad]
    ok, reason = legal_squad(current)
    if not ok:
        raise PackageSearchError(f"current squad illegal: {reason}")
    candidates, _ = _eligible_candidates(
        candidate_universe,
        owned_ids={_element(row) for row in current},
    )
    return _enumerate_exact(
        current,
        candidates,
        bank_before=_int(bank, label="bank"),
        max_transfers=_validated_transfer_bound(max_transfers),
    )


def enumerate_routes_batch(
    current_squad: Sequence[Mapping[str, Any]],
    candidate_universe: Sequence[Mapping[str, Any]],
    *,
    bank: int,
    max_transfers: int,
    batch_size: int = 512,
) -> list[dict[str, Any]]:
    """Execution-only exact batching surface.

    Route construction is deliberately the same scalar kernel. Batching changes
    materialization cadence only and therefore cannot become a second search
    authority.
    """
    if int(batch_size) <= 0:
        raise PackageSearchError("batch_size must be positive")
    rows = enumerate_routes_scalar(
        current_squad,
        candidate_universe,
        bank=bank,
        max_transfers=max_transfers,
    )
    # Materialize deterministic chunks and flatten them again. This keeps the
    # public contract ready for vectorized legality acceleration without
    # changing route identity or authority today.
    chunks = [rows[index : index + int(batch_size)] for index in range(0, len(rows), int(batch_size))]
    return [row for chunk in chunks for row in chunk]


def enumerate_routes_sharded(
    current_squad: Sequence[Mapping[str, Any]],
    candidate_universe: Sequence[Mapping[str, Any]],
    *,
    bank: int,
    max_transfers: int,
    shard_count: int,
) -> list[dict[str, Any]]:
    current = [_normalized_player(row, owned=True) for row in current_squad]
    ok, reason = legal_squad(current)
    if not ok:
        raise PackageSearchError(f"current squad illegal: {reason}")
    candidates, _ = _eligible_candidates(
        candidate_universe,
        owned_ids={_element(row) for row in current},
    )
    parts = [
        _enumerate_exact(
            current,
            candidates,
            bank_before=_int(bank, label="bank"),
            max_transfers=_validated_transfer_bound(max_transfers),
            shard_index=index,
            shard_count=int(shard_count),
        )
        for index in range(int(shard_count))
    ]
    merged = [row for part in parts for row in part]
    route_ids = [str(row["route_id"]) for row in merged]
    if len(route_ids) != len(set(route_ids)):
        raise PackageSearchError("shard overlap detected")
    merged.sort(key=lambda row: (int(row["transfer_count"]), str(row["route_id"])))
    return merged


def _validated_transfer_bound(max_transfers: int) -> int:
    cfg = load_config()
    value = _int(max_transfers, label="max_transfers")
    maximum = int(cfg.get("maximum_supported_transfers") or 3)
    if value > maximum:
        raise PackageSearchError(
            f"max_transfers={value} exceeds bounded P1.2A support={maximum}"
        )
    return value


def _coverage(
    *,
    candidates: Sequence[Mapping[str, Any]],
    universe_counts: Mapping[str, int],
    universe_complete: bool,
    expected_eligible_universe_count: int | None,
    lossy_pruning: bool,
) -> dict[str, Any]:
    eligible = len(candidates)
    expected = eligible if expected_eligible_universe_count is None else int(expected_eligible_universe_count)
    searched = eligible
    full = (
        bool(universe_complete)
        and not bool(lossy_pruning)
        and expected == eligible
        and searched == eligible
    )
    reason = (
        "COMPLETE_ELIGIBLE_UNIVERSE_ZERO_LOSSY_PRUNING"
        if full
        else "INCOMPLETE_OR_LOSSY_SEARCH_SCOPE"
    )
    return {
        **{str(key): int(value) for key, value in universe_counts.items()},
        "eligible_universe_count": expected,
        "eligible_universe_count_observed": eligible,
        "searched_universe_count": searched,
        "universe_complete": bool(universe_complete),
        "lossy_pruning": bool(lossy_pruning),
        "search_authority": "FULL" if full else "PARTIAL",
        "authority_reason": reason,
        "coverage_complete": full,
    }


def build_search_frontier(routes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Representation-only skyline on search/economic dimensions.

    It cannot add/remove routes from search output and is not a football or
    package-utility frontier.
    """
    executable = [
        dict(row)
        for row in routes
        if row.get("legal") is True and row.get("affordable") is True
    ]
    frontier: list[dict[str, Any]] = []
    for route in executable:
        transfers = int(route.get("transfer_count") or 0)
        bank_after = int(route.get("bank_after") or 0)
        dominated = False
        for other in executable:
            if other is route:
                continue
            other_transfers = int(other.get("transfer_count") or 0)
            other_bank = int(other.get("bank_after") or 0)
            if (
                other_transfers <= transfers
                and other_bank >= bank_after
                and (other_transfers < transfers or other_bank > bank_after)
            ):
                dominated = True
                break
        if not dominated:
            frontier.append(
                {
                    "route_id": route.get("route_id"),
                    "transfer_count": transfers,
                    "bank_after": bank_after,
                }
            )
    frontier.sort(key=lambda row: (int(row["transfer_count"]), -int(row["bank_after"]), str(row["route_id"])))
    return {
        "authority": "REPRESENTATION_ONLY",
        "scoring_authority": False,
        "dimensions": ["lower_transfer_count", "higher_bank_after"],
        "route_set_mutated": False,
        "count": len(frontier),
        "routes": frontier,
    }


def search_packages(
    *,
    current_squad: Sequence[Mapping[str, Any]],
    candidate_universe: Sequence[Mapping[str, Any]],
    bank: int,
    max_transfers: int | None = None,
    universe_complete: bool,
    expected_eligible_universe_count: int | None = None,
    lossy_pruning: bool = False,
    execution_mode: str = "SCALAR",
    shard_count: int = 1,
    batch_size: int = 512,
) -> dict[str, Any]:
    cfg = load_config()
    bound = _validated_transfer_bound(
        int(cfg.get("default_max_transfers") or 2)
        if max_transfers is None
        else int(max_transfers)
    )
    current = [_normalized_player(row, owned=True) for row in current_squad]
    ok, reason = legal_squad(current)
    if not ok:
        raise PackageSearchError(f"current squad illegal: {reason}")
    owned_ids = {_element(row) for row in current}
    candidates, universe_counts = _eligible_candidates(
        candidate_universe,
        owned_ids=owned_ids,
    )
    mode = str(execution_mode or "SCALAR").upper()
    if mode == "SCALAR":
        routes = _enumerate_exact(
            current,
            candidates,
            bank_before=_int(bank, label="bank"),
            max_transfers=bound,
        )
    elif mode == "BATCH":
        routes = enumerate_routes_batch(
            current,
            candidate_universe,
            bank=bank,
            max_transfers=bound,
            batch_size=batch_size,
        )
    elif mode == "SHARDED":
        routes = enumerate_routes_sharded(
            current,
            candidate_universe,
            bank=bank,
            max_transfers=bound,
            shard_count=shard_count,
        )
    else:
        raise PackageSearchError(f"unsupported execution_mode={mode}")

    coverage = _coverage(
        candidates=candidates,
        universe_counts=universe_counts,
        universe_complete=universe_complete,
        expected_eligible_universe_count=expected_eligible_universe_count,
        lossy_pruning=lossy_pruning,
    )
    for route in routes:
        route["search_authority"] = coverage["search_authority"]
        route["universe_coverage"] = {
            "eligible_universe_count": coverage["eligible_universe_count"],
            "searched_universe_count": coverage["searched_universe_count"],
            "coverage_complete": coverage["coverage_complete"],
        }

    unresolved = sum(1 for route in routes if route.get("economics_status") != "RESOLVED")
    affordable = sum(1 for route in routes if route.get("affordable") is True)
    unaffordable = sum(1 for route in routes if route.get("affordable") is False)
    return {
        "schema_version": 1,
        "model": cfg.get("model_id"),
        "model_owner": MODEL_OWNER,
        "ruleset_id": RULESET_ID,
        "status": "READY",
        "search_authority": coverage["search_authority"],
        "eligible_universe_count": coverage["eligible_universe_count"],
        "searched_universe_count": coverage["searched_universe_count"],
        "route_denominator": len(routes),
        "coverage": coverage,
        "execution": {
            "mode": mode,
            "batch_size": int(batch_size) if mode == "BATCH" else None,
            "shard_count": int(shard_count) if mode == "SHARDED" else 1,
            "scalar_reference_authority": True,
            "execution_layer_is_not_search_authority": True,
        },
        "route_counts": {
            "total": len(routes),
            "affordable": affordable,
            "unaffordable": unaffordable,
            "economics_unresolved": unresolved,
        },
        "routes": routes,
        "search_frontier": build_search_frontier(routes),
        "governance": {
            "search_decision_utility_separated": True,
            "hold_included": any(route.get("route_id") == "HOLD" for route in routes),
            "lossless_position_multiset_pruning": True,
            "lossy_pruning_applied": bool(lossy_pruning),
            "decision_score_present": False,
            "ft_shadow_present": False,
            "canonical_weights_present": False,
            "horizon_utility_present": False,
            "monte_carlo_present": False,
            "mini_league_present": False,
            "v6_mutated": False,
        },
    }
