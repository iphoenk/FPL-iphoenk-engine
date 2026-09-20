from __future__ import annotations

"""P1.8 V12-native mini-league decision overlay.

The football-optimal decision is frozen first. Mini-league evidence is then
applied as a bounded downstream relative-risk overlay. This module never owns
raw football scoring, legality, package search, or P1.4 football-world math.
"""

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.engines.canonical_decision_methodology import (
    CANONICAL_AUTHORITY,
    CANONICAL_WEIGHTS,
    validate_methodology_weights,
)
from src.engines.v12_model_evidence import (
    bind_deterministic_output,
    build_model_run_binding,
    fingerprint,
    freeze_prediction,
    settle_frozen_record,
)
from src.engines.v12_monte_carlo import (
    package_route_definitions,
    run_correlated_monte_carlo,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "v12_mini_league_overlay.json"
CANONICAL_PATH = ROOT / CANONICAL_AUTHORITY
MODEL_OWNER = "V12_MINI_LEAGUE_OVERLAY"
MODEL_ID = "v12_mini_league_decision_overlay"
COVERAGE_STATES = {"FULL", "PARTIAL", "UNAVAILABLE"}
POSTURES = {"PROTECT", "BALANCED", "CHASE"}


class MiniLeagueOverlayError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(out):
        raise MiniLeagueOverlayError("non-finite numerical input")
    return out


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def _pct(num: float, den: int) -> float | None:
    return None if den <= 0 else round(float(num) * 100.0 / float(den), 4)


def _canonical_sha256() -> str:
    return hashlib.sha256(CANONICAL_PATH.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "V12_MINI_LEAGUE_DECISION_OVERLAY_V1":
        raise MiniLeagueOverlayError("P1.8 overlay contract drift")
    if payload.get("model_owner") != MODEL_OWNER:
        raise MiniLeagueOverlayError("P1.8 overlay owner drift")
    return payload


def legacy_mini_league_inventory() -> list[dict[str, Any]]:
    return [
        {
            "surface": "src.runtime_v6.domains.report_plane.league_prefetch",
            "classification": "FACTUAL_DISPLAY",
            "reusable": "ATOMIC_STANDINGS_AND_SUBMITTED_PICKS_ONLY",
            "decision_authority": False,
        },
        {
            "surface": "data/v6/mini_leagues/<league_id>/history",
            "classification": "DENOMINATOR_DISCIPLINE",
            "reusable": "CURRENT_COHORT_FACTS_AND_COVERAGE_METADATA",
            "decision_authority": False,
        },
        {
            "surface": "src.engines.official_expansion._mini_league_tracking",
            "classification": "REPORT_DECORATION",
            "reusable": "CURRENT_RANK_GAP_DISPLAY_ONLY",
            "decision_authority": False,
        },
        {
            "surface": "config/strategy/mini_leagues.json",
            "classification": "FACTUAL_DISPLAY",
            "reusable": "LEAGUE_DISCOVERY_AND_NONCRITICAL_TRACKING_POLICY",
            "decision_authority": False,
        },
        {
            "surface": "legacy ownership/captain heuristic",
            "classification": "LEGACY_DECISION_HEURISTIC",
            "reusable": "NONE_FOUND_AS_CANONICAL_OWNER",
            "decision_authority": False,
        },
    ]


def _normalised_pick(raw: Mapping[str, Any]) -> dict[str, Any]:
    element = raw.get("element_id", raw.get("element"))
    position = raw.get("squad_position", raw.get("position"))
    multiplier = raw.get("multiplier")
    return {
        "element_id": _i(element, -1),
        "squad_position": _i(position, -1),
        "multiplier": (
            None if multiplier is None else _f(multiplier)
        ),
        "captain": bool(raw.get("captain", raw.get("is_captain"))),
        "vice_captain": bool(
            raw.get("vice_captain", raw.get("is_vice_captain"))
        ),
    }


def _entry_records(manager_picks: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    entries = manager_picks.get("entries") or {}
    if not isinstance(entries, Mapping):
        return out
    for key, raw in entries.items():
        if not isinstance(raw, Mapping):
            continue
        entry_id = _i(raw.get("entry_id", key), -1)
        if entry_id <= 0:
            continue
        out[entry_id] = {
            "entry_id": entry_id,
            "status": str(raw.get("status") or "UNAVAILABLE"),
            "active_chip": raw.get("active_chip"),
            "picks": [
                _normalised_pick(p)
                for p in raw.get("picks") or []
                if isinstance(p, Mapping)
            ],
            "checked_at": raw.get("checked_at"),
        }
    return out


def build_mini_league_snapshot(
    standings: Mapping[str, Any],
    manager_picks: Mapping[str, Any],
    *,
    our_entry_id: int,
    planning_gw: int,
    league_scope: str | None = None,
    selected_entry_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Normalize factual league state without persisting raw V6 pick payloads."""
    standings_rows = [
        dict(row)
        for row in standings.get("managers") or []
        if isinstance(row, Mapping) and row.get("entry_id") is not None
    ]
    standings_by_id = {_i(row.get("entry_id")): row for row in standings_rows}
    pick_records = _entry_records(manager_picks)

    expected = standings.get("expected_manager_count")
    if expected is None and standings.get("complete") is True:
        expected = len(standings_rows)
    expected = _i(expected, len(standings_rows))
    standing_ids = sorted(x for x in standings_by_id if x > 0)

    if selected_entry_ids is not None:
        selected = sorted(set(_i(x) for x in selected_entry_ids if _i(x) > 0))
        included_ids = [x for x in selected if x in standings_by_id]
        scope = league_scope or "SELECTED_RIVALS"
        expected_scope = len(selected)
    else:
        included_ids = standing_ids
        scope = league_scope or (
            "FULL_LEAGUE" if standings.get("complete") is True else "PARTIAL_FETCH"
        )
        expected_scope = expected

    available_ids = [
        entry_id
        for entry_id in included_ids
        if (pick_records.get(entry_id) or {}).get("status") == "AVAILABLE"
    ]
    missing_ids = sorted(set(included_ids) - set(available_ids))

    if not standings_rows and not pick_records:
        coverage = "UNAVAILABLE"
    else:
        standings_complete = bool(standings.get("complete"))
        picks_complete = (
            len(available_ids) == len(included_ids)
            and len(included_ids) == expected_scope
            and expected_scope > 0
        )
        if scope == "FULL_LEAGUE":
            picks_complete = picks_complete and standings_complete
        coverage = "FULL" if picks_complete else "PARTIAL"

    rival_ids = [x for x in available_ids if x != int(our_entry_id)]
    denominator = len(rival_ids)
    exposure: dict[int, dict[str, Any]] = {}
    all_multiplier_semantics_valid = True
    chips: dict[str, int] = {}

    for entry_id in rival_ids:
        record = pick_records[entry_id]
        picks = record["picks"]
        if len(picks) != 15:
            all_multiplier_semantics_valid = False
        chip = str(record.get("active_chip") or "NONE")
        chips[chip] = chips.get(chip, 0) + 1
        for pick in picks:
            element = _i(pick.get("element_id"), -1)
            if element <= 0:
                continue
            row = exposure.setdefault(
                element,
                {
                    "element_id": element,
                    "ownership_count": 0,
                    "starter_count": 0,
                    "bench_count": 0,
                    "captain_count": 0,
                    "vice_count": 0,
                    "effective_multiplier_sum": 0.0,
                    "multiplier_complete": True,
                },
            )
            row["ownership_count"] += 1
            position = _i(pick.get("squad_position"), -1)
            if 1 <= position <= 11:
                row["starter_count"] += 1
            elif position > 11:
                row["bench_count"] += 1
            if pick.get("captain"):
                row["captain_count"] += 1
            if pick.get("vice_captain"):
                row["vice_count"] += 1
            multiplier = pick.get("multiplier")
            if multiplier is None:
                row["multiplier_complete"] = False
                all_multiplier_semantics_valid = False
            else:
                row["effective_multiplier_sum"] += _f(multiplier)

    eo_supported = (
        coverage == "FULL"
        and denominator > 0
        and all_multiplier_semantics_valid
        and bool(load_config()["coverage"]["eo_requires_full_pick_coverage"])
    )
    exposure_rows = []
    for element in sorted(exposure):
        row = exposure[element]
        effective_pct = (
            _pct(row["effective_multiplier_sum"], denominator)
            if row["multiplier_complete"] and denominator > 0
            else None
        )
        exposure_rows.append(
            {
                **row,
                "denominator": denominator,
                "ownership_pct": _pct(row["ownership_count"], denominator),
                "starter_pct": _pct(row["starter_count"], denominator),
                "bench_pct": _pct(row["bench_count"], denominator),
                "captain_pct": _pct(row["captain_count"], denominator),
                "vice_pct": _pct(row["vice_count"], denominator),
                "effective_exposure_pct_collected_scope": effective_pct,
                "eo_pct": effective_pct if eo_supported else None,
                "eo_supported": eo_supported,
                "ordinary_ownership_is_not_eo": True,
            }
        )

    ours = standings_by_id.get(int(our_entry_id))
    ordered = sorted(
        standings_rows,
        key=lambda row: (
            _i(row.get("league_rank"), 10**9),
            -_i(row.get("league_total"), 0),
            _i(row.get("entry_id"), 10**9),
        ),
    )
    leader = ordered[0] if ordered else None
    our_rank = _i((ours or {}).get("league_rank"), 0) or None
    our_total = _i((ours or {}).get("league_total"), 0) if ours else None
    leader_total = _i((leader or {}).get("league_total"), 0) if leader else None
    nearest_above = None
    nearest_below = None
    if our_rank is not None:
        nearest_above = next(
            (
                row
                for row in reversed(ordered)
                if _i(row.get("league_rank"), 0) < our_rank
            ),
            None,
        )
        nearest_below = next(
            (
                row
                for row in ordered
                if _i(row.get("league_rank"), 0) > our_rank
            ),
            None,
        )
    cluster = [
        {
            "entry_id": _i(row.get("entry_id")),
            "rank": _i(row.get("league_rank"), 0) or None,
            "total_points": _i(row.get("league_total"), 0),
        }
        for row in ordered
        if our_rank is not None
        and abs(_i(row.get("league_rank"), 10**9) - our_rank) <= 2
    ]

    current_context = {
        "our_entry_id": int(our_entry_id),
        "our_rank": our_rank,
        "our_total_points": our_total,
        "leader_entry_id": _i((leader or {}).get("entry_id"), 0) or None,
        "leader_points": leader_total,
        "points_to_leader": (
            max(0, leader_total - our_total)
            if leader_total is not None and our_total is not None
            else None
        ),
        "nearest_above_entry_id": _i((nearest_above or {}).get("entry_id"), 0) or None,
        "points_to_nearest_above": (
            max(0, _i(nearest_above.get("league_total")) - our_total)
            if nearest_above is not None and our_total is not None
            else None
        ),
        "nearest_below_entry_id": _i((nearest_below or {}).get("entry_id"), 0) or None,
        "points_ahead_nearest_below": (
            max(0, our_total - _i(nearest_below.get("league_total")))
            if nearest_below is not None and our_total is not None
            else None
        ),
        "rank_cluster": cluster,
        "manager_count": expected if expected > 0 else len(standings_rows),
        "planning_gw": int(planning_gw),
        "gw_remaining_including_planning_gw": max(0, 38 - int(planning_gw) + 1),
    }

    denominator_fp = fingerprint(
        {
            "league_id": standings.get("league_id", manager_picks.get("league_id")),
            "scope": scope,
            "expected_scope": expected_scope,
            "standing_ids": included_ids,
            "available_ids": available_ids,
            "rival_ids": rival_ids,
        }
    )
    snapshot_id = (
        f"ML:{standings.get('league_id', manager_picks.get('league_id', 'UNKNOWN'))}:"
        f"GW{int(planning_gw)}:{denominator_fp[:16]}"
    )
    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "league_id": standings.get("league_id", manager_picks.get("league_id")),
        "league_name": standings.get("league_name"),
        "league_kind": standings.get("league_kind"),
        "planning_gw": int(planning_gw),
        "generated_at": max(
            str(standings.get("generated_at") or ""),
            str(manager_picks.get("generated_at") or ""),
        )
        or None,
        "coverage_state": coverage,
        "league_scope": scope,
        "expected_manager_count": expected_scope,
        "standings_manager_count": len(included_ids),
        "submitted_picks_available_count": len(available_ids),
        "submitted_picks_missing_count": len(missing_ids),
        "missing_entry_ids": missing_ids,
        "rival_exposure_denominator": denominator,
        "denominator_fingerprint": denominator_fp,
        "eo_supported": eo_supported,
        "exposures": exposure_rows,
        "chip_counts": chips,
        "current_league_context": current_context,
        "provenance": {
            "standings_authority": standings.get("authority"),
            "picks_authority": manager_picks.get("authority"),
            "standings_complete": bool(standings.get("complete")),
            "picks_complete": bool(manager_picks.get("complete")),
            "standings_generated_at": standings.get("generated_at"),
            "picks_generated_at": manager_picks.get("generated_at"),
            "raw_v6_payload_persisted": False,
        },
    }


def _route_map(package_utility: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("route_id")): dict(row)
        for row in package_utility.get("routes") or []
        if isinstance(row, Mapping) and row.get("route_id") is not None
    }


def _first_lineup(route: Mapping[str, Any]) -> dict[str, Any]:
    rows = (
        (route.get("football_route_utility") or {}).get("per_gw") or []
    )
    return dict(rows[0]) if rows else {}


def _mc_route_metrics(
    monte_carlo: Mapping[str, Any] | None,
    route_id: str,
) -> dict[str, Any]:
    mc = dict(monte_carlo or {})
    if (
        mc.get("model_owner") != "V12_MONTE_CARLO"
        or mc.get("execution_state") != "EXECUTED"
        or mc.get("canonical_pass") is not True
        or _i(mc.get("actual_paths")) < 500_000
    ):
        return {
            "status": "UNAVAILABLE",
            "reason": "CANONICAL_P1_4_MC_NOT_EXECUTED",
        }
    row = dict(((mc.get("metrics") or {}).get(route_id) or {}).get("1") or {})
    if not row:
        return {"status": "UNAVAILABLE", "reason": "ROUTE_NOT_IN_MC"}
    return {
        "status": "AVAILABLE",
        "actual_paths": _i(mc.get("actual_paths")),
        "output_fingerprint": mc.get("output_fingerprint"),
        "mean_difference_vs_hold": row.get("mean_difference_vs_hold"),
        "p_route_gt_hold": row.get("p_route_gt_hold"),
        "p_route_lt_hold": row.get("p_route_lt_hold"),
        "downside_probability": row.get("downside_probability"),
        "material_upside_probability": row.get("material_upside_probability"),
        "expected_regret": row.get("expected_regret"),
        "paired_difference_standard_error": row.get(
            "paired_difference_standard_error"
        ),
    }


def build_football_baseline(
    package_utility: Mapping[str, Any],
    monte_carlo: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if package_utility.get("model_owner") != "V12_PACKAGE_UTILITY":
        raise MiniLeagueOverlayError(
            "P1.8 requires P1.2B V12_PACKAGE_UTILITY baseline"
        )
    route_id = str(package_utility.get("selected_route_id") or "")
    routes = _route_map(package_utility)
    if not route_id or route_id not in routes:
        raise MiniLeagueOverlayError("football baseline route is missing")
    route = routes[route_id]
    lineup = _first_lineup(route)
    baseline = {
        "route_id": route_id,
        "classification": route.get("classification"),
        "players_out": deepcopy(route.get("players_out") or []),
        "players_in": deepcopy(route.get("players_in") or []),
        "starting_xi": list(lineup.get("starting_xi") or []),
        "bench_gk": lineup.get("bench_gk"),
        "bench_order": list(lineup.get("bench_order") or []),
        "captain": lineup.get("captain"),
        "vice_captain": lineup.get("vice_captain"),
        "gw_plus_1_football_utility": (
            (route.get("horizons") or {}).get("GW+1") or {}
        ).get("net_delta_vs_hold"),
        "three_gw_football_utility": (
            (route.get("horizons") or {}).get("3GW") or {}
        ).get("net_delta_vs_hold"),
        "five_gw_football_utility": (
            (route.get("horizons") or {}).get("5GW") or {}
        ).get("net_delta_vs_hold"),
        "robustness": deepcopy(route.get("robustness") or {}),
        "expected_regret": route.get("expected_regret"),
        "mc_route_distribution": _mc_route_metrics(monte_carlo, route_id),
        "decision": deepcopy(package_utility.get("decision") or {}),
        "package_model_output_fingerprint": (
            (package_utility.get("model_evidence_binding") or {}).get(
                "output_fingerprint"
            )
        ),
        "mc_output_fingerprint": (
            monte_carlo.get("output_fingerprint")
            if isinstance(monte_carlo, Mapping)
            else None
        ),
    }
    baseline["football_baseline_fingerprint"] = fingerprint(baseline)
    return baseline


def derive_risk_posture(
    league_snapshot: Mapping[str, Any],
    *,
    explicit_posture: str | None = None,
) -> dict[str, Any]:
    cfg = load_config()["risk_posture"]
    if explicit_posture is not None:
        posture = str(explicit_posture).upper()
        if posture not in POSTURES:
            raise MiniLeagueOverlayError("invalid explicit risk posture")
        return {
            "posture": posture,
            "source": "EXPLICIT_CURRENT_DECISION_PREFERENCE",
            "default_used": False,
        }

    context = dict(league_snapshot.get("current_league_context") or {})
    remaining = _i(context.get("gw_remaining_including_planning_gw"), 99)
    late = remaining <= _i(cfg.get("late_horizon_gws_remaining_at_most"), 5)
    rank = context.get("our_rank")
    ahead = context.get("points_ahead_nearest_below")
    deficit = context.get("points_to_leader")

    if (
        late
        and rank == 1
        and ahead is not None
        and _f(ahead) >= _f(cfg.get("protect_min_points_ahead_nearest"), 15)
    ):
        return {
            "posture": "PROTECT",
            "source": "CURRENT_LEAGUE_POINTS_AND_REMAINING_HORIZON",
            "default_used": False,
        }
    if (
        late
        and rank is not None
        and int(rank) > 1
        and deficit is not None
        and _f(deficit) >= _f(cfg.get("chase_min_points_to_leader"), 20)
    ):
        return {
            "posture": "CHASE",
            "source": "CURRENT_LEAGUE_POINTS_AND_REMAINING_HORIZON",
            "default_used": False,
        }
    return {
        "posture": "BALANCED",
        "source": "DEFAULT_NO_MATERIAL_CONTEXT_TRIGGER",
        "default_used": True,
    }


def _horizon_value(route: Mapping[str, Any], label: str) -> float | None:
    value = ((route.get("horizons") or {}).get(label) or {}).get(
        "net_delta_vs_hold"
    )
    return None if value is None else _f(value)


def _pair_probability(
    monte_carlo: Mapping[str, Any] | None,
    candidate_id: str,
    baseline_id: str,
) -> float | None:
    mc = dict(monte_carlo or {})
    if (
        mc.get("execution_state") != "EXECUTED"
        or mc.get("canonical_pass") is not True
    ):
        return None
    pairs = mc.get("paired_outputs") or {}
    direct = pairs.get(f"{candidate_id}__VS__{baseline_id}__H1")
    if isinstance(direct, Mapping) and direct.get("p_a_gt_b") is not None:
        return _f(direct["p_a_gt_b"])
    reverse = pairs.get(f"{baseline_id}__VS__{candidate_id}__H1")
    if isinstance(reverse, Mapping) and reverse.get("p_a_gt_b") is not None:
        return 1.0 - _f(reverse["p_a_gt_b"])
    return None


def close_decision_gate(
    baseline_route: Mapping[str, Any],
    candidate_route: Mapping[str, Any],
    *,
    monte_carlo: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = load_config()["close_decision_gate"]
    gaps = {}
    close = True
    for label in ("GW+1", "3GW", "5GW"):
        base = _horizon_value(baseline_route, label)
        candidate = _horizon_value(candidate_route, label)
        if base is None or candidate is None:
            gaps[label] = None
            continue
        gap = candidate - base
        gaps[label] = round(gap, 6)
        if abs(gap) > _f((cfg.get("max_absolute_gap") or {}).get(label), 0.0):
            close = False

    base_regret = baseline_route.get("expected_regret")
    candidate_regret = candidate_route.get("expected_regret")
    regret_gap = (
        None
        if base_regret is None or candidate_regret is None
        else _f(candidate_regret) - _f(base_regret)
    )
    if (
        regret_gap is not None
        and abs(regret_gap) > _f(cfg.get("max_expected_regret_gap"), 0.75)
    ):
        close = False

    pair_p = _pair_probability(
        monte_carlo,
        str(candidate_route.get("route_id")),
        str(baseline_route.get("route_id")),
    )
    if pair_p is not None and not (
        _f(cfg.get("paired_probability_close_low"), 0.40)
        <= pair_p
        <= _f(cfg.get("paired_probability_close_high"), 0.60)
    ):
        close = False

    return {
        "version": cfg.get("version"),
        "status": "CLOSE" if close else "NOT_CLOSE",
        "football_horizon_gaps_vs_baseline": gaps,
        "expected_regret_gap": (
            None if regret_gap is None else round(regret_gap, 6)
        ),
        "p_candidate_gt_baseline": pair_p,
        "large_football_edge_preserved": not close,
    }


def _exposure_map(snapshot: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        _i(row.get("element_id")): dict(row)
        for row in snapshot.get("exposures") or []
        if isinstance(row, Mapping)
    }


def route_exposure(
    route: Mapping[str, Any],
    league_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    lineup = _first_lineup(route)
    xi = [int(x) for x in lineup.get("starting_xi") or []]
    captain = _i(lineup.get("captain"), -1)
    vice = _i(lineup.get("vice_captain"), -1)
    emap = _exposure_map(league_snapshot)
    denominator = _i(league_snapshot.get("rival_exposure_denominator"), 0)

    starter_fracs = []
    for element in xi:
        row = emap.get(element) or {}
        pct = row.get("starter_pct")
        starter_fracs.append(0.0 if pct is None else _f(pct) / 100.0)
    mean_starter = (
        sum(starter_fracs) / len(starter_fracs) if starter_fracs else 0.0
    )
    cap_row = emap.get(captain) or {}
    vice_row = emap.get(vice) or {}
    cap_frac = _f(cap_row.get("captain_pct"), 0.0) / 100.0
    vice_frac = _f(vice_row.get("vice_pct"), 0.0) / 100.0
    differential = max(0.0, min(1.0, 1.0 - mean_starter))
    defensive = max(
        0.0,
        min(1.0, 0.70 * mean_starter + 0.30 * cap_frac),
    )

    return {
        "denominator": denominator,
        "starting_xi_count": len(xi),
        "mean_rival_starter_exposure": mean_starter,
        "mean_differential_exposure": differential,
        "captain_rival_exposure": cap_frac,
        "vice_rival_exposure": vice_frac,
        "defensive_coverage_index": defensive,
        "captain_leverage": {
            "our_captain_element": captain if captain > 0 else None,
            "rival_captain_count": cap_row.get("captain_count", 0),
            "rival_captain_denominator": denominator,
            "rival_captain_pct": cap_row.get("captain_pct"),
            "relative_upside_index_if_our_captain_succeeds": (
                max(0.0, 1.0 - cap_frac) if denominator > 0 else None
            ),
            "relative_downside_index_if_our_captain_fails": (
                cap_frac if denominator > 0 else None
            ),
            "chosen_for_difference_only": False,
        },
        "vice_exposure": {
            "our_vice_element": vice if vice > 0 else None,
            "rival_vice_count": vice_row.get("vice_count", 0),
            "rival_vice_denominator": denominator,
            "rival_vice_pct": vice_row.get("vice_pct"),
        },
    }


def _relative_mc_metric(
    relative_mc: Mapping[str, Any] | None,
    route_id: str,
    leader_entry_id: int | None,
) -> dict[str, Any]:
    if leader_entry_id is None:
        return {"status": "UNAVAILABLE", "reason": "NO_LEADER_ID"}
    mc = dict(relative_mc or {})
    if (
        mc.get("model_owner") != "V12_MONTE_CARLO"
        or mc.get("execution_state") != "EXECUTED"
        or mc.get("canonical_pass") is not True
        or mc.get("common_random_numbers") is not True
    ):
        return {
            "status": "UNAVAILABLE",
            "reason": "CANONICAL_SHARED_WORLD_RELATIVE_MC_NOT_AVAILABLE",
        }
    rival_id = f"RIVAL:{leader_entry_id}"
    pair = (mc.get("paired_outputs") or {}).get(
        f"{route_id}__VS__{rival_id}__H1"
    )
    invert = False
    if not isinstance(pair, Mapping):
        pair = (mc.get("paired_outputs") or {}).get(
            f"{rival_id}__VS__{route_id}__H1"
        )
        invert = isinstance(pair, Mapping)
    if not isinstance(pair, Mapping) or pair.get("mean_difference") is None:
        return {"status": "UNAVAILABLE", "reason": "ROUTE_LEADER_PAIR_NOT_SIMULATED"}
    mean = _f(pair.get("mean_difference"))
    p = _f(pair.get("p_a_gt_b"))
    if invert:
        mean = -mean
        p = 1.0 - p
    return {
        "status": "AVAILABLE",
        "scope": "CURRENT_GW_RELATIVE_POINTS_ONLY",
        "same_football_worlds": True,
        "leader_entry_id": int(leader_entry_id),
        "expected_relative_points": mean,
        "p_gain_points_on_leader": p,
        "p_lose_points_to_leader": 1.0 - p,
        "paired_standard_error": pair.get("paired_difference_standard_error"),
        "mc_output_fingerprint": mc.get("output_fingerprint"),
        "final_rank_probability": "NOT_COMPUTED",
    }


def _quality_factor(
    gate: Mapping[str, Any],
) -> float:
    if gate.get("status") == "CLOSE":
        return 1.0
    return 0.0


def leverage_utility(
    route: Mapping[str, Any],
    *,
    baseline_route: Mapping[str, Any],
    league_snapshot: Mapping[str, Any],
    posture: str,
    monte_carlo: Mapping[str, Any] | None,
    relative_mc: Mapping[str, Any] | None,
) -> dict[str, Any]:
    cfg = load_config()
    weights = cfg["leverage"]["posture_weights"][posture]
    exposure = route_exposure(route, league_snapshot)
    baseline_exposure = route_exposure(baseline_route, league_snapshot)
    mc = _mc_route_metrics(monte_carlo, str(route.get("route_id")))
    leader = (league_snapshot.get("current_league_context") or {}).get(
        "leader_entry_id"
    )
    rel = _relative_mc_metric(
        relative_mc,
        str(route.get("route_id")),
        _i(leader, 0) or None,
    )
    gate = close_decision_gate(
        baseline_route,
        route,
        monte_carlo=monte_carlo,
    )
    quality = 1.0 if str(route.get("route_id")) == str(baseline_route.get("route_id")) else _quality_factor(gate)

    # Mini-league leverage is relative to the frozen football baseline,
    # not to an arbitrary 50% ownership threshold. This prevents a genuinely
    # more-differential close route from being penalized merely because most
    # of the unchanged XI remains commonly owned.
    defensive = (
        _f(exposure.get("defensive_coverage_index"), 0.0)
        - _f(baseline_exposure.get("defensive_coverage_index"), 0.0)
    )
    captain_coverage = (
        _f((exposure.get("captain_leverage") or {}).get("rival_captain_pct"), 0.0)
        - _f(
            (baseline_exposure.get("captain_leverage") or {}).get(
                "rival_captain_pct"
            ),
            0.0,
        )
    ) / 100.0
    differential = (
        _f(exposure.get("mean_differential_exposure"), 0.0)
        - _f(baseline_exposure.get("mean_differential_exposure"), 0.0)
    )
    mc_upside = (
        _f(mc.get("material_upside_probability"), 0.5) - 0.5
        if mc.get("status") == "AVAILABLE"
        else 0.0
    )
    mc_downside = (
        _f(mc.get("downside_probability"), 0.5) - 0.5
        if mc.get("status") == "AVAILABLE"
        else 0.0
    )
    relative_edge = (
        math.tanh(_f(rel.get("expected_relative_points")) / 5.0)
        if rel.get("status") == "AVAILABLE"
        else 0.0
    )
    relative_weight = {
        "PROTECT": 0.10,
        "BALANCED": 0.15,
        "CHASE": 0.20,
    }[posture]
    raw = (
        _f(weights.get("defensive_coverage")) * defensive
        + _f(weights.get("captain_coverage")) * captain_coverage
        + _f(weights.get("differential_upside")) * differential
        + _f(weights.get("mc_upside")) * mc_upside
        - _f(weights.get("mc_downside_penalty")) * mc_downside
        + relative_weight * relative_edge
    )
    max_adjustment = _f(
        cfg["leverage"].get("max_absolute_overlay_adjustment_points"),
        0.75,
    )
    adjustment = max(
        -max_adjustment,
        min(max_adjustment, raw * max_adjustment * quality),
    )
    football = _horizon_value(route, "GW+1")
    final = None if football is None else football + adjustment
    return {
        "version": cfg["leverage"]["version"],
        "risk_posture": posture,
        "football_baseline_utility": football,
        "mini_league_overlay_utility": round(adjustment, 6),
        "final_relative_decision_utility": (
            None if final is None else round(final, 6)
        ),
        "components": {
            "defensive_coverage_delta_vs_football_baseline": defensive,
            "captain_coverage_delta_vs_football_baseline": captain_coverage,
            "differential_upside_delta_vs_football_baseline": differential,
            "mc_upside_centered": mc_upside,
            "mc_downside_centered": mc_downside,
            "relative_mc_edge": relative_edge,
            "football_quality_factor": quality,
        },
        "exposure": exposure,
        "football_mc": mc,
        "relative_mc": rel,
        "close_decision_gate": gate,
        "poor_football_option_cannot_be_promoted_by_exposure_only": True,
    }


def _reversal_triggers(
    league_snapshot: Mapping[str, Any],
    *,
    switched: bool,
) -> dict[str, Any]:
    if not switched:
        return {
            "required": False,
            "triggers": [],
        }
    return {
        "required": True,
        "triggers": [
            "FOOTBALL_UTILITY_GAP_EXCEEDS_CLOSE_DECISION_GATE",
            "NEW_INJURY_OR_AVAILABILITY_EVIDENCE",
            "LEAGUE_DENOMINATOR_OR_COVERAGE_CHANGES",
            "RIVAL_CAPTAIN_EXPOSURE_CHANGES",
            "PRICE_OR_AFFORDABILITY_CONSTRAINT_CHANGES",
            "P1_4_RELATIVE_TAIL_EDGE_DISAPPEARS",
            "FOOTBALL_BASELINE_MODEL_FINGERPRINT_CHANGES",
        ],
        "league_denominator_fingerprint": league_snapshot.get(
            "denominator_fingerprint"
        ),
    }


def _model_binding(
    *,
    football_baseline: Mapping[str, Any],
    league_snapshot: Mapping[str, Any],
    monte_carlo: Mapping[str, Any] | None,
    relative_mc: Mapping[str, Any] | None,
    generated_at: str,
    planning_gw: int,
    input_snapshot_id: str,
) -> dict[str, Any]:
    cfg = load_config()
    timestamps = {
        "league_snapshot": league_snapshot.get("generated_at")
        or generated_at,
        "football_baseline": generated_at,
    }
    artifacts = {
        "football_baseline": str(
            football_baseline.get("football_baseline_fingerprint")
        ),
        "league_denominator": str(league_snapshot.get("denominator_fingerprint")),
    }
    if isinstance(monte_carlo, Mapping) and monte_carlo.get("output_fingerprint"):
        artifacts["football_mc"] = str(monte_carlo.get("output_fingerprint"))
    if isinstance(relative_mc, Mapping) and relative_mc.get("output_fingerprint"):
        artifacts["relative_mc"] = str(relative_mc.get("output_fingerprint"))

    return build_model_run_binding(
        input_snapshot_id=input_snapshot_id,
        factual_snapshot_timestamps=timestamps,
        factual_artifact_fingerprints=artifacts,
        deterministic_factual_inputs={
            "football_baseline_fingerprint": football_baseline.get(
                "football_baseline_fingerprint"
            ),
            "mini_league_snapshot_id": league_snapshot.get("snapshot_id"),
            "coverage_state": league_snapshot.get("coverage_state"),
            "league_scope": league_snapshot.get("league_scope"),
            "denominator_fingerprint": league_snapshot.get(
                "denominator_fingerprint"
            ),
            "mc_output_fingerprint": (
                monte_carlo.get("output_fingerprint")
                if isinstance(monte_carlo, Mapping)
                else None
            ),
        },
        model_version=str(cfg.get("model_version")),
        feature_version=str(cfg.get("feature_version")),
        parameter_version=str(cfg.get("parameter_version")),
        parameters={
            "coverage": cfg.get("coverage"),
            "risk_posture": cfg.get("risk_posture"),
            "close_decision_gate": cfg.get("close_decision_gate"),
            "leverage": cfg.get("leverage"),
        },
        calibration_version=str(cfg.get("calibration_version")),
        calibration_cutoff=str(cfg.get("calibration_cutoff")),
        calibration_parameters={"automatic_retuning": False},
        generated_at=generated_at,
        planning_gw=int(planning_gw),
        canonical_v12_revision=_canonical_sha256(),
    )


def evaluate_mini_league_overlay(
    package_utility: Mapping[str, Any],
    league_snapshot: Mapping[str, Any],
    *,
    monte_carlo: Mapping[str, Any] | None = None,
    relative_mc: Mapping[str, Any] | None = None,
    explicit_risk_posture: str | None = None,
    input_snapshot_id: str = "P1_8_DECISION_SNAPSHOT",
    generated_at: str | None = None,
) -> dict[str, Any]:
    validate_methodology_weights(
        CANONICAL_WEIGHTS,
        authority=CANONICAL_AUTHORITY,
    )
    generated = generated_at or _now()

    # Critical ordering: baseline exists and is fingerprinted before league
    # exposure is allowed into route preference.
    baseline = build_football_baseline(package_utility, monte_carlo)
    baseline_immutable_fp = fingerprint(baseline)
    routes = _route_map(package_utility)
    baseline_route = routes[baseline["route_id"]]

    coverage = str(league_snapshot.get("coverage_state") or "UNAVAILABLE")
    if coverage not in COVERAGE_STATES:
        raise MiniLeagueOverlayError("invalid league coverage state")
    posture = derive_risk_posture(
        league_snapshot,
        explicit_posture=explicit_risk_posture,
    )
    # Screen the full P1.2 universe cheaply first. P1.8 is allowed to
    # alter preference only for the frozen baseline, HOLD, or genuinely close
    # alternatives. Non-close routes remain inspectable but do not pay the
    # expensive exposure/MC-enrichment cost. With PARTIAL/UNAVAILABLE league
    # evidence no switch is permitted, so only baseline/HOLD need full overlay
    # materialization.
    route_rows = []
    for route_id, route in sorted(routes.items()):
        gate = close_decision_gate(
            baseline_route,
            route,
            monte_carlo=monte_carlo,
        )
        material = (
            route_id == baseline["route_id"]
            or route_id == "HOLD"
            or (coverage == "FULL" and gate["status"] == "CLOSE")
        )
        if material:
            lev = leverage_utility(
                route,
                baseline_route=baseline_route,
                league_snapshot=league_snapshot,
                posture=posture["posture"],
                monte_carlo=monte_carlo,
                relative_mc=relative_mc,
            )
            route_rows.append(
                {
                    "route_id": route_id,
                    "classification": route.get("classification"),
                    "football_baseline_utility": lev["football_baseline_utility"],
                    "mini_league_overlay_utility": lev[
                        "mini_league_overlay_utility"
                    ],
                    "final_relative_decision_utility": lev[
                        "final_relative_decision_utility"
                    ],
                    "close_decision_gate": lev["close_decision_gate"],
                    "league_exposure": lev["exposure"],
                    "football_mc": lev["football_mc"],
                    "relative_mc": lev["relative_mc"],
                    "components": lev["components"],
                    "material_overlay_evaluated": True,
                }
            )
        else:
            football = _horizon_value(route, "GW+1")
            route_rows.append(
                {
                    "route_id": route_id,
                    "classification": route.get("classification"),
                    "football_baseline_utility": football,
                    "mini_league_overlay_utility": 0.0,
                    "final_relative_decision_utility": football,
                    "close_decision_gate": gate,
                    "league_exposure": {
                        "status": "NOT_MATERIAL_FOR_OVERLAY",
                        "reason": (
                            "LEAGUE_EVIDENCE_CANNOT_SWITCH_BASELINE"
                            if coverage != "FULL"
                            else "OUTSIDE_CLOSE_DECISION_GATE"
                        ),
                    },
                    "football_mc": {
                        "status": "NOT_REEVALUATED_BY_P1_8",
                        "p1_4_distribution_unchanged": True,
                    },
                    "relative_mc": {
                        "status": "NOT_REQUIRED_NONMATERIAL_ROUTE",
                    },
                    "components": {
                        "football_quality_factor": 0.0,
                        "screened_out_before_expensive_overlay": True,
                    },
                    "material_overlay_evaluated": False,
                }
            )

    if fingerprint(baseline) != baseline_immutable_fp:
        raise MiniLeagueOverlayError("football baseline mutated by overlay")

    baseline_row = next(
        row for row in route_rows if row["route_id"] == baseline["route_id"]
    )
    adjusted = baseline_row
    switch_allowed = coverage == "FULL"
    if switch_allowed:
        eligible = [
            row
            for row in route_rows
            if row["route_id"] == baseline["route_id"]
            or row["close_decision_gate"]["status"] == "CLOSE"
        ]
        resolved = [
            row
            for row in eligible
            if row["final_relative_decision_utility"] is not None
        ]
        if resolved:
            adjusted = max(
                resolved,
                key=lambda row: (
                    _f(row["final_relative_decision_utility"]),
                    row["route_id"] == baseline["route_id"],
                    row["route_id"],
                ),
            )

    switched = adjusted["route_id"] != baseline["route_id"]
    if coverage != "FULL":
        state = "NO_ACTIONABLE_LEAGUE_EDGE"
    elif switched and posture["posture"] == "BALANCED":
        state = "CLOSE_CALL_SWITCH"
    elif switched:
        state = "RISK_POSTURE_SWITCH"
    elif (
        baseline_row["mini_league_overlay_utility"] > 0
        and len(route_rows) > 1
    ):
        state = "BASELINE_STRENGTHENED"
    else:
        state = "BASELINE_PRESERVED"

    relevant_ids = set(int(x) for x in baseline.get("starting_xi") or [])
    adjusted_route = routes.get(adjusted["route_id"]) or {}
    adjusted_lineup = _first_lineup(adjusted_route)
    relevant_ids.update(int(x) for x in adjusted_lineup.get("starting_xi") or [])
    for value in (
        baseline.get("captain"),
        baseline.get("vice_captain"),
        adjusted_lineup.get("captain"),
        adjusted_lineup.get("vice_captain"),
    ):
        if value is not None:
            relevant_ids.add(_i(value))
    relevant_exposure = [
        dict(row)
        for row in league_snapshot.get("exposures") or []
        if _i((row or {}).get("element_id"), -1) in relevant_ids
    ]
    relevant_exposure.sort(
        key=lambda row: (
            -_i(row.get("captain_count"), 0),
            -_i(row.get("starter_count"), 0),
            -_i(row.get("ownership_count"), 0),
            _i(row.get("element_id"), 10**9),
        )
    )
    relevant_exposure = relevant_exposure[
        : _i(load_config()["report"].get("max_relevant_exposures"), 8)
    ]

    decision_delta = {
        "football_baseline_route_id": baseline["route_id"],
        "mini_league_adjusted_route_id": adjusted["route_id"],
        "changed": switched,
        "state": state,
        "reason": (
            "PARTIAL_OR_UNAVAILABLE_LEAGUE_EVIDENCE_CANNOT_SWITCH_BASELINE"
            if coverage != "FULL"
            else (
                "CLOSE_FOOTBALL_DECISION_WITH_BOUNDED_RELATIVE_RISK_EDGE"
                if switched
                else "NO_MATERIAL_MINI_LEAGUE_REASON_TO_OVERTURN_FOOTBALL_BASELINE"
            )
        ),
    }
    reversal = _reversal_triggers(
        league_snapshot,
        switched=switched,
    )

    planning_gw = _i(package_utility.get("planning_gw"), 1)
    binding = _model_binding(
        football_baseline=baseline,
        league_snapshot=league_snapshot,
        monte_carlo=monte_carlo,
        relative_mc=relative_mc,
        generated_at=generated,
        planning_gw=planning_gw,
        input_snapshot_id=input_snapshot_id,
    )
    core = {
        "schema_version": 1,
        "model_owner": MODEL_OWNER,
        "model_id": MODEL_ID,
        "planning_gw": planning_gw,
        "football_baseline": baseline,
        "league_context": deepcopy(
            league_snapshot.get("current_league_context") or {}
        ),
        "mini_league_evidence_provenance": {
            "snapshot_id": league_snapshot.get("snapshot_id"),
            "provenance": deepcopy(league_snapshot.get("provenance") or {}),
            "runtime_binding": deepcopy(
                league_snapshot.get("runtime_binding") or {}
            ),
        },
        "coverage": {
            "state": coverage,
            "scope": league_snapshot.get("league_scope"),
            "expected_manager_count": league_snapshot.get(
                "expected_manager_count"
            ),
            "submitted_picks_available_count": league_snapshot.get(
                "submitted_picks_available_count"
            ),
            "submitted_picks_missing_count": league_snapshot.get(
                "submitted_picks_missing_count"
            ),
            "rival_exposure_denominator": league_snapshot.get(
                "rival_exposure_denominator"
            ),
            "denominator_fingerprint": league_snapshot.get(
                "denominator_fingerprint"
            ),
        },
        "risk_posture": posture,
        "relevant_rival_exposure": relevant_exposure,
        "route_overlays": route_rows,
        "adjusted_decision": {
            "route_id": adjusted["route_id"],
            "classification": adjusted["classification"],
            "overlay_state": state,
            "football_baseline_utility": adjusted[
                "football_baseline_utility"
            ],
            "mini_league_overlay_utility": adjusted[
                "mini_league_overlay_utility"
            ],
            "final_relative_decision_utility": adjusted[
                "final_relative_decision_utility"
            ],
        },
        "decision_delta": decision_delta,
        "reversal_triggers": reversal,
        "rank_probability_boundary": {
            "p_finish_first": "NOT_COMPUTED",
            "p_top_3": "NOT_COMPUTED",
            "future_final_rank": "NOT_COMPUTED",
            "reason": "FUTURE_DECISIONS_OF_ALL_MANAGERS_NOT_SIMULATED",
        },
        "governance": {
            "authority": False,
            "downstream_overlay_only": True,
            "football_baseline_computed_first": True,
            "football_baseline_immutable": True,
            "raw_football_score_mutated": False,
            "gate0_mutated": False,
            "weights_20_25_30_25_mutated": False,
            "p1_1_math_mutated": False,
            "p1_3_math_mutated": False,
            "p1_6_math_mutated": False,
            "p1_7_math_mutated": False,
            "p1_2_math_mutated": False,
            "p1_4_math_mutated": False,
            "second_mini_league_mc_used": False,
            "raw_v6_payload_duplicated": False,
            "football_report_suppressed_on_league_failure": False,
        },
    }
    bound = bind_deterministic_output(binding, core)
    evidence = {
        **{k: v for k, v in binding.items() if k != "deterministic_output"},
        "authority": False,
        "mini_league_snapshot_id": league_snapshot.get("snapshot_id"),
        "coverage_state": coverage,
        "denominator_fingerprint": league_snapshot.get(
            "denominator_fingerprint"
        ),
        "football_baseline_fingerprint": baseline[
            "football_baseline_fingerprint"
        ],
        "mc_output_fingerprint": (
            monte_carlo.get("output_fingerprint")
            if isinstance(monte_carlo, Mapping)
            else None
        ),
        "output_fingerprint": bound["output_fingerprint"],
        "raw_v6_payload_duplicated": False,
    }
    return {
        **core,
        "status": (
            "READY"
            if coverage == "FULL"
            else "DEGRADED" if coverage == "PARTIAL" else "UNAVAILABLE"
        ),
        "generated_at": generated,
        "model_version": load_config().get("model_version"),
        "feature_version": load_config().get("feature_version"),
        "parameter_version": load_config().get("parameter_version"),
        "run_fingerprint": binding["run_fingerprint"],
        "output_fingerprint": bound["output_fingerprint"],
        "model_evidence_binding": evidence,
    }


def attach_mini_league_overlay(
    package_utility: Mapping[str, Any],
    overlay: Mapping[str, Any],
) -> dict[str, Any]:
    if package_utility.get("model_owner") != "V12_PACKAGE_UTILITY":
        raise MiniLeagueOverlayError("overlay can attach only to P1.2B artifact")
    if overlay.get("model_owner") != MODEL_OWNER:
        raise MiniLeagueOverlayError("invalid overlay owner")
    baseline = overlay.get("football_baseline") or {}
    if str(baseline.get("route_id")) != str(
        package_utility.get("selected_route_id")
    ):
        raise MiniLeagueOverlayError("overlay football baseline route mismatch")
    out = deepcopy(dict(package_utility))
    out["mini_league_overlay"] = deepcopy(dict(overlay))
    out.setdefault("governance", {})["mini_league_overlay_owner"] = MODEL_OWNER
    out["governance"]["mini_league_overlay_downstream_only"] = True
    return out


def freeze_mini_league_decision(
    overlay: Mapping[str, Any],
    *,
    deadline_time: Any,
    frozen_at: Any,
) -> dict[str, Any]:
    binding = dict(overlay.get("model_evidence_binding") or {})
    generated = overlay.get("generated_at")
    baseline = dict(overlay.get("football_baseline") or {})
    adjusted = dict(overlay.get("adjusted_decision") or {})
    league_exposure_snapshot = {
        "coverage": deepcopy(overlay.get("coverage") or {}),
        "league_context": deepcopy(overlay.get("league_context") or {}),
        "risk_posture": deepcopy(overlay.get("risk_posture") or {}),
    }
    baseline_record = freeze_prediction(
        model_binding=binding,
        deadline_time=deadline_time,
        forecast_generated_at=generated,
        frozen_at=frozen_at,
        forecast_rows=[],
        decision_snapshot={
            "captured_at": generated,
            "decision_kind": "P1.8_FOOTBALL_BASELINE",
            "route_id": baseline.get("route_id"),
            "football_baseline_fingerprint": baseline.get(
                "football_baseline_fingerprint"
            ),
            "league_exposure_snapshot": league_exposure_snapshot,
        },
    )
    adjusted_record = freeze_prediction(
        model_binding=binding,
        deadline_time=deadline_time,
        forecast_generated_at=generated,
        frozen_at=frozen_at,
        forecast_rows=[],
        decision_snapshot={
            "captured_at": generated,
            "decision_kind": "P1.8_MINI_LEAGUE_ADJUSTED",
            "route_id": adjusted.get("route_id"),
            "decision_delta": deepcopy(overlay.get("decision_delta") or {}),
            "overlay_reason": (overlay.get("decision_delta") or {}).get("reason"),
            "league_exposure_snapshot": league_exposure_snapshot,
        },
    )
    return {
        "football_baseline_freeze": baseline_record,
        "mini_league_adjusted_freeze": adjusted_record,
        "separate_freezes": True,
    }


def settle_mini_league_decision(
    frozen: Mapping[str, Any],
    *,
    baseline_relative_points: float,
    adjusted_relative_points: float,
    event_finished: bool,
    settled_at: Any,
) -> dict[str, Any]:
    baseline_record = frozen.get("football_baseline_freeze") or {}
    adjusted_record = frozen.get("mini_league_adjusted_freeze") or {}
    baseline = settle_frozen_record(
        baseline_record,
        actual_rows=[],
        decision_outcome_evidence=None,
        event_finished=event_finished,
        settled_at=settled_at,
    )
    adjusted = settle_frozen_record(
        adjusted_record,
        actual_rows=[],
        decision_outcome_evidence=None,
        event_finished=event_finished,
        settled_at=settled_at,
    )
    relative_gain = _f(adjusted_relative_points) - _f(
        baseline_relative_points
    )
    return {
        "football_baseline_settlement": baseline,
        "mini_league_adjusted_settlement": adjusted,
        "relative_points_baseline": _f(baseline_relative_points),
        "relative_points_adjusted": _f(adjusted_relative_points),
        "relative_points_gained_or_lost_by_overlay": relative_gain,
        "overlay_regret": max(0.0, -relative_gain),
        "overlay_improved_realized_relative_outcome": relative_gain > 0.0,
        "decision_quality_is_separate_from_realized_variance": True,
    }


def overlay_calibration_summary(
    settled_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [dict(row) for row in settled_rows]
    changed = [
        row
        for row in rows
        if bool((row.get("decision_delta") or {}).get("changed"))
    ]
    sacrifices = [
        _f(row.get("football_utility_sacrificed"))
        for row in changed
        if row.get("football_utility_sacrificed") is not None
    ]
    gains = [
        _f(row.get("relative_points_gained_or_lost_by_overlay"))
        for row in changed
        if row.get("relative_points_gained_or_lost_by_overlay") is not None
    ]
    regrets = [
        _f(row.get("overlay_regret"))
        for row in changed
        if row.get("overlay_regret") is not None
    ]
    by_posture = {}
    for posture in sorted(POSTURES):
        subset = [
            row
            for row in changed
            if str(row.get("risk_posture")) == posture
        ]
        by_posture[posture] = {
            "sample_size": len(subset),
            "mean_relative_gain": (
                sum(_f(x.get("relative_points_gained_or_lost_by_overlay")) for x in subset)
                / len(subset)
                if subset
                else None
            ),
        }
    return {
        "sample_size": len(rows),
        "overlay_change_count": len(changed),
        "overlay_change_frequency": (
            len(changed) / len(rows) if rows else None
        ),
        "mean_football_utility_sacrificed": (
            sum(sacrifices) / len(sacrifices) if sacrifices else None
        ),
        "mean_realized_relative_gain": (
            sum(gains) / len(gains) if gains else None
        ),
        "mean_relative_regret": (
            sum(regrets) / len(regrets) if regrets else None
        ),
        "performance_by_risk_posture": by_posture,
        "one_gw_permanent_leverage_rule_forbidden": True,
        "automatic_methodology_mutation": False,
    }


def _projection_position_map(
    projections: Mapping[str, Any],
) -> dict[int, str]:
    out = {}
    for row in projections.get("players") or []:
        if not isinstance(row, Mapping):
            continue
        element = _i(row.get("element", row.get("id")), -1)
        raw = str(row.get("position") or "").upper()
        if raw not in {"GK", "DEF", "MID", "FWD"}:
            raw = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}.get(
                _i(row.get("element_type")),
                "",
            )
        if element > 0 and raw:
            out[element] = raw
    return out


def build_rival_route_definitions(
    manager_picks: Mapping[str, Any],
    projections: Mapping[str, Any],
    *,
    entry_ids: Sequence[int],
    planning_gw: int,
) -> list[dict[str, Any]]:
    records = _entry_records(manager_picks)
    positions = _projection_position_map(projections)
    out = []
    for entry_id in sorted(set(int(x) for x in entry_ids)):
        record = records.get(entry_id)
        if not record or record.get("status") != "AVAILABLE":
            continue
        picks = record.get("picks") or []
        starters = [
            _i(p["element_id"])
            for p in picks
            if 1 <= _i(p.get("squad_position"), -1) <= 11
        ]
        bench_rows = sorted(
            [
                p
                for p in picks
                if _i(p.get("squad_position"), -1) > 11
            ],
            key=lambda p: _i(p.get("squad_position"), 99),
        )
        bench_gks = [
            _i(p["element_id"])
            for p in bench_rows
            if positions.get(_i(p["element_id"])) == "GK"
        ]
        outfield_bench = [
            _i(p["element_id"])
            for p in bench_rows
            if positions.get(_i(p["element_id"])) != "GK"
        ]
        captain = next(
            (_i(p["element_id"]) for p in picks if p.get("captain")),
            None,
        )
        vice = next(
            (_i(p["element_id"]) for p in picks if p.get("vice_captain")),
            None,
        )
        if (
            len(starters) != 11
            or len(bench_gks) != 1
            or len(outfield_bench) != 3
            or captain is None
            or vice is None
        ):
            continue
        out.append(
            {
                "route_id": f"RIVAL:{entry_id}",
                "classification": "RIVAL_FACTUAL_LINEUP",
                "per_gw": [
                    {
                        "status": "READY",
                        "gw": int(planning_gw),
                        "starting_xi": starters,
                        "bench_gk": bench_gks[0],
                        "bench_order": outfield_bench,
                        "captain": captain,
                        "vice_captain": vice,
                    }
                ],
                "execution_cost_points": 0.0,
                "transfer_economics": {
                    "status": "NOT_APPLICABLE_RIVAL_CURRENT_GW_FACT",
                },
            }
        )
    return out


def run_relative_mini_league_mc(
    projections: Mapping[str, Any],
    package_utility: Mapping[str, Any],
    manager_picks: Mapping[str, Any],
    *,
    candidate_route_ids: Sequence[str],
    rival_entry_ids: Sequence[int],
    actual_paths: int,
    seed: int,
    input_snapshot_id: str,
    canonical: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Reuse P1.4 directly; this is deliberately not a second MC engine."""
    ours = package_route_definitions(
        package_utility,
        route_ids=candidate_route_ids,
    )
    rival = build_rival_route_definitions(
        manager_picks,
        projections,
        entry_ids=rival_entry_ids,
        planning_gw=_i(package_utility.get("planning_gw"), 1),
    )
    combined = ours + rival
    if len(combined) > 8:
        raise MiniLeagueOverlayError(
            "P1.4 material route bound exceeded; select fewer relevant rivals"
        )
    result = run_correlated_monte_carlo(
        projections,
        combined,
        actual_paths=actual_paths,
        seed=seed,
        input_snapshot_id=input_snapshot_id,
        canonical=canonical,
        horizons=(1,),
        selected_route_id=str(package_utility.get("selected_route_id") or "HOLD"),
        generated_at=generated_at,
    )
    result["mini_league_relative_scope"] = {
        "scope": "SELECTED_RIVALS",
        "rival_entry_ids": sorted(
            int(x) for x in rival_entry_ids
        ),
        "current_gw_only": True,
        "same_p1_4_football_worlds": True,
        "second_mc_engine": False,
        "future_final_rank_probability": "NOT_COMPUTED",
    }
    return result
