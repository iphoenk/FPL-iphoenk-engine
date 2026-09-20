from __future__ import annotations

import itertools
from copy import deepcopy
import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from statistics import NormalDist
from pathlib import Path
from typing import Any

from src.engines.canonical_decision_methodology import validate_monte_carlo_provenance
from src.engines.p0_decision_quality import resolve_locked_chip_context
from src.engines.v12_lineup_optimizer import (
    compare_legacy_decision,
    load_config as load_v12_lineup_config,
    optimize_lineup,
)
from src.engines.p1_decision_governance import (
    bench_battles,
    choose_close_call_lineup,
    decision_scores,
    lineup_risk_adjustment,
    state_conditional_slot_utility,
    uncertainty_fields,
    vice_rank,
)
from src.engines.v12_mini_league_overlay import (
    MODEL_OWNER as MINI_LEAGUE_OWNER,
    attach_mini_league_overlay,
    build_mini_league_snapshot,
    evaluate_mini_league_overlay,
)
from src.engines.v12_monte_carlo import mc_invocation_policy
from src.engines.v12_package_search import legal_squad as v12_package_legal_squad
from src.rules import LINEUP_RULES, RULESET_ID, SQUAD_RULES
from src.utils import CONFIG, DATA, ROOT, atomic_json, read_json

POLICY_PATH = ROOT / "config" / "intelligence" / "lineup_governance.json"
LINEUP_OUT = DATA / "lineup_decision.json"
PACKAGE_DECISION_OUT = DATA / "package_decision.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _materialize_native_mini_league_overlay(
    package_optimizer: dict[str, Any],
    lock: dict[str, Any],
    *,
    data_root: Path = DATA,
) -> dict[str, Any]:
    """Bind P1.8 to already-published V6 mini-league facts.

    This is a downstream consumer only: it reads V6 artifacts but never imports
    or mutates the V6 runtime/data plane. Missing, stale, or mismatched league
    evidence degrades the overlay without suppressing the football baseline.
    """
    if package_optimizer.get("model_owner") != "V12_PACKAGE_UTILITY":
        return package_optimizer

    planning_gw = int(package_optimizer.get("planning_gw") or 0)
    expected_entry_id = int(lock.get("team_id") or 0)
    manifest = read_json(data_root / "v6" / "report_prefetch" / "latest.json", {})
    manifest_gw = int(manifest.get("gw") or 0) if isinstance(manifest, dict) else 0
    manifest_entry_id = (
        int(manifest.get("entry_id") or 0) if isinstance(manifest, dict) else 0
    )
    league_id = (
        int(manifest.get("priority_league_id") or 0)
        if isinstance(manifest, dict)
        else 0
    )

    occurrence_matches = bool(
        planning_gw > 0
        and manifest_gw == planning_gw
        and expected_entry_id > 0
        and manifest_entry_id == expected_entry_id
        and league_id > 0
    )
    standings: dict[str, Any] = {}
    manager_picks: dict[str, Any] = {}
    if occurrence_matches:
        standings = read_json(
            data_root / "v6" / "mini_leagues" / str(league_id) / "standings.json",
            {},
        )
        manager_picks = read_json(
            data_root
            / "v6"
            / "mini_leagues"
            / str(league_id)
            / f"gw_{planning_gw}_manager_picks.json",
            {},
        )

    snapshot = build_mini_league_snapshot(
        standings,
        manager_picks,
        our_entry_id=expected_entry_id,
        planning_gw=max(1, planning_gw),
        league_scope="FULL_LEAGUE",
    )
    snapshot["runtime_binding"] = {
        "source": "PUBLISHED_V6_REPORT_PREFETCH_FACTS",
        "occurrence_matches": occurrence_matches,
        "manifest_request_id": (
            manifest.get("request_id") if isinstance(manifest, dict) else None
        ),
        "manifest_gw": manifest_gw or None,
        "manifest_entry_id": manifest_entry_id or None,
        "priority_league_id": league_id or None,
        "raw_v6_payload_duplicated": False,
    }
    football_mc = package_optimizer.get("monte_carlo")
    if not isinstance(football_mc, dict):
        football_mc = None
    binding = package_optimizer.get("model_evidence_binding") or {}
    input_snapshot_id = str(
        binding.get("input_snapshot_id")
        or (
            manifest.get("request_id")
            if isinstance(manifest, dict)
            else None
        )
        or "P1_8_RUNTIME_PACKAGE_DECISION"
    )
    overlay = evaluate_mini_league_overlay(
        package_optimizer,
        snapshot,
        monte_carlo=football_mc,
        relative_mc=None,
        input_snapshot_id=input_snapshot_id,
        generated_at=(
            manifest.get("generated_at")
            if isinstance(manifest, dict) and manifest.get("generated_at")
            else package_optimizer.get("generated_at")
        ),
    )
    return attach_mini_league_overlay(package_optimizer, overlay)


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _authoritative_squad_rows(
    team: dict[str, Any] | None,
    lock: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Resolve decision squad from the team-state owner, never from raw capture after resolution.

    The lock fallback exists only for legacy unit fixtures that do not provide a
    team-state artifact. Any payload that claims team-state authority but lacks a
    complete squad fails closed instead of silently falling back to raw config.
    """
    expected = int(SQUAD_RULES.get("squad_size") or 15)
    team = team if isinstance(team, dict) else {}
    squad = [row for row in team.get("squad") or [] if isinstance(row, dict)]
    if squad:
        ids = [int(row.get("element") or -1) for row in squad]
        if len(ids) != expected or len(set(ids)) != expected or any(element <= 0 for element in ids):
            raise RuntimeError(f"canonical team squad invalid: count={len(ids)} unique={len(set(ids))}")
        ledger_ids = {
            int(row.get("element") or -1)
            for row in team.get("team_value_ledger") or []
            if isinstance(row, dict) and row.get("element") is not None
        }
        if ledger_ids and ledger_ids != set(ids):
            raise RuntimeError(
                "canonical team squad and value ledger diverged: "
                f"squad_only={sorted(set(ids) - ledger_ids)} ledger_only={sorted(ledger_ids - set(ids))}"
            )
        authority = str(
            team.get("squad_authority")
            or (team.get("projection_baseline") or {}).get("effective_authority")
            or ""
        ) or None
        return squad, authority, False

    if team.get("squad_authority") or team.get("projection_baseline"):
        raise RuntimeError("canonical team authority present without a complete resolved squad")

    # Compatibility for isolated legacy unit fixtures only. Production callers
    # must pass team.json and are fail-closed by the validation chain below.
    fallback = [row for row in lock.get("players") or [] if isinstance(row, dict)]
    ids = [int(row.get("element") or -1) for row in fallback]
    if len(ids) != expected or len(set(ids)) != expected or any(element <= 0 for element in ids):
        raise RuntimeError(f"legacy lock fixture invalid: count={len(ids)} unique={len(set(ids))}")
    return fallback, str(lock.get("authoritative_phase") or "") or None, True


def _effective_lock_context(
    team: dict[str, Any] | None,
    lock: dict[str, Any],
    legacy_fixture_fallback: bool,
) -> dict[str, Any]:
    """Expose raw user-lock context only when team-state actually accepted it."""
    if legacy_fixture_fallback:
        return lock
    team = team if isinstance(team, dict) else {}
    baseline = team.get("projection_baseline") if isinstance(team.get("projection_baseline"), dict) else {}
    if baseline.get("override_applied") is True:
        return lock
    return {}


def _gw_projection(proj: dict[str, Any], gw: int) -> dict[str, Any]:
    for row in proj.get("xpts_by_gw") or []:
        if int(row.get("gw") or -1) == int(gw):
            return row
    return {"gw": gw, "mean": 0.0, "std": 0.0, "fixtures": []}


def _defensive_route_proxy(gw_row: dict[str, Any]) -> float:
    total = 0.0
    for fixture in gw_row.get("fixtures") or []:
        components = fixture.get("components") or {}
        total += _f(components.get("clean_sheet")) + _f(components.get("saves")) + _f(components.get("defensive_contribution"))
    return round(max(0.0, total), 4)


def _player_row(proj: dict[str, Any], gw: int, policy: dict[str, Any]) -> dict[str, Any]:
    gw_row = _gw_projection(proj, gw)
    xmins = proj.get("xmins") or {}
    mean = _f(gw_row.get("mean"))
    std = _f(gw_row.get("std"))
    scores = decision_scores(proj, gw_row, xmins, policy)
    uncertainty = uncertainty_fields(gw_row, xmins, policy)
    attack_context = scores.get("attack_context") or {}
    return {
        "element": int(proj["element"]),
        "name": proj.get("name"),
        "position": proj.get("position"),
        "team_id": int(proj.get("team_id") or -1),
        "now_cost": int(proj.get("now_cost") or 0),
        "xpts_mean": round(mean, 3),
        "xpts_std": round(std, 3),
        "lower80": uncertainty.get("lower80"),
        "upper80": uncertainty.get("upper80"),
        "interval_width": uncertainty.get("interval_width"),
        "selection_score": scores.get("selection_score"),
        "captain_score": scores.get("captain_score"),
        "vice_score": scores.get("vice_score"),
        "bench_score": scores.get("bench_score"),
        "score_decomposition": scores.get("score_decomposition"),
        "attack_ceiling_proxy": attack_context.get("attack_ceiling_proxy"),
        "focality_proxy": attack_context.get("focality_proxy"),
        "penalty_role_evidence": attack_context.get("penalty_role_evidence"),
        "set_piece_role_evidence": attack_context.get("set_piece_role_evidence"),
        "defensive_route_proxy": _defensive_route_proxy(gw_row),
        "start_probability": round(_f(xmins.get("start_probability")), 4),
        "bench_probability": uncertainty.get("bench_probability"),
        "cameo_probability": uncertainty.get("cameo_probability"),
        "late_cameo_probability": uncertainty.get("late_cameo_probability"),
        "dnp_probability": uncertainty.get("dnp_probability"),
        "availability": uncertainty.get("availability"),
        "expected_minutes": round(_f(xmins.get("expected_minutes")), 2),
        "starter_minutes_if_start": _f(xmins.get("starter_minutes_if_start")),
        "cameo_minutes_if_used": _f(xmins.get("cameo_minutes_if_used", xmins.get("bench_minutes_if_used"))),
        "late_cameo_minutes_if_used": _f(xmins.get("late_cameo_minutes_if_used")),
        "xmins_distribution": dict(xmins.get("xmins_distribution") or {}),
        "projection_confidence": proj.get("projection_confidence"),
    }


def _formation(rows: list[dict[str, Any]]) -> str | None:
    counts = {pos: sum(1 for p in rows if p.get("position") == pos) for pos in ("DEF", "MID", "FWD")}
    form = f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"
    return form if form in set(LINEUP_RULES.get("legal_formations") or []) else None


def _legal_auto_sub_value(
    starter: dict[str, Any],
    starters: list[dict[str, Any]],
    bench_rows: list[dict[str, Any]],
) -> tuple[float, int | None]:
    """Return first legal prospective bench substitute under FPL formation rules."""
    ordered = sorted(
        bench_rows,
        key=lambda row: (_f(row.get("bench_score")), _f(row.get("xpts_mean"))),
        reverse=True,
    )
    starter_id = int(starter.get("element") or -1)
    for substitute in ordered:
        if starter.get("position") == "GK":
            if substitute.get("position") != "GK":
                continue
        elif substitute.get("position") == "GK":
            continue
        replaced = [
            substitute if int(row.get("element") or -1) == starter_id else row
            for row in starters
        ]
        if starter.get("position") == "GK" or _formation(replaced):
            return max(0.0, _f(substitute.get("xpts_mean"))), int(
                substitute.get("element") or -1
            )
    return 0.0, None


def _pairwise_regret(
    candidate: dict[str, Any],
    comparator: dict[str, Any],
) -> tuple[float, float]:
    mu = _f(candidate.get("xpts_mean")) - _f(comparator.get("xpts_mean"))
    sigma = math.sqrt(
        max(0.0, _f(candidate.get("xpts_std")) ** 2)
        + max(0.0, _f(comparator.get("xpts_std")) ** 2)
    )
    if sigma <= 1e-12:
        return (1.0 if mu > 0 else 0.5 if mu == 0 else 0.0, max(0.0, -mu))
    z = mu / sigma
    p_outperform = NormalDist(mu=mu, sigma=sigma).cdf(0.0)
    # P(D > 0), where D = candidate - comparator.
    p_outperform = 1.0 - p_outperform
    phi = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    expected_regret = sigma * phi - mu * NormalDist().cdf(-z)
    return p_outperform, max(0.0, expected_regret)


def _lineup_candidates(players: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    required_size = int(LINEUP_RULES.get("starting_xi_size") or 11)
    required_gk = int(LINEUP_RULES.get("starting_goalkeepers") or 1)
    candidates: list[dict[str, Any]] = []
    all_ids = {int(p["element"]) for p in players}
    for combo in itertools.combinations(players, required_size):
        rows = list(combo)
        if sum(1 for p in rows if p.get("position") == "GK") != required_gk:
            continue
        form = _formation(rows)
        if not form:
            continue
        ids = sorted(int(p["element"]) for p in rows)
        bench_rows = [
            p for p in players if int(p["element"]) in all_ids - set(ids)
        ]
        base_score = sum(_f(p.get("selection_score")) for p in rows)
        mean = sum(_f(p.get("xpts_mean")) for p in rows)
        variance = sum(_f(p.get("xpts_std")) ** 2 for p in rows)
        risk = lineup_risk_adjustment(rows, bench_rows, policy)
        decision_score = base_score + _f(risk.get("adjustment"))

        slot_rows: list[dict[str, Any]] = []
        for starter in rows:
            auto_sub_value, auto_sub_element = _legal_auto_sub_value(
                starter, rows, bench_rows
            )
            slot = state_conditional_slot_utility(
                starter, legal_auto_sub_value=auto_sub_value
            )
            slot_rows.append({
                "element": starter.get("element"),
                "auto_sub_element": auto_sub_element,
                **slot,
            })
        expected_utility = sum(_f(row.get("expected_utility")) for row in slot_rows)
        conditional_floor = sum(_f(row.get("lower80")) for row in rows)
        upper_tail = sum(_f(row.get("upper80")) for row in rows)
        auto_sub_preservation = sum(
            _f(row.get("auto_sub_preservation_value")) for row in slot_rows
        )
        cameo_blocking_cost = sum(
            _f(row.get("cameo_auto_sub_blocking_cost")) for row in slot_rows
        )
        candidates.append({
            "formation": form,
            "score": round(decision_score, 4),
            "decision_score": round(decision_score, 4),
            "base_score": round(base_score, 4),
            "risk_adjustment": risk,
            "xpts_mean": round(mean, 3),
            "xpts_std": round(variance ** 0.5, 3),
            "element_ids": ids,
            "v12_expected_utility": round(expected_utility, 4),
            "conditional_floor": round(conditional_floor, 4),
            "upper_tail": round(upper_tail, 4),
            "auto_sub_preservation_value": round(auto_sub_preservation, 4),
            "cameo_auto_sub_blocking_cost": round(cameo_blocking_cost, 4),
            "lineup_optionality": round(
                auto_sub_preservation - cameo_blocking_cost, 4
            ),
            "slot_state_utility": slot_rows,
            "robustness_method": "STATE_CONDITIONAL_WITH_LEGAL_AUTOSUB",
        })

    if not candidates:
        return []
    comparator = max(
        candidates,
        key=lambda row: (_f(row.get("xpts_mean")), -_f(row.get("xpts_std"))),
    )
    for row in candidates:
        p_outperform, regret = _pairwise_regret(row, comparator)
        row["p_outperform_mean_comparator"] = round(p_outperform, 6)
        row["expected_regret"] = round(regret, 6)
        row["uncertainty_overlap_with_mean_comparator"] = not (
            _f(row.get("upper_tail")) < _f(comparator.get("conditional_floor"))
            or _f(comparator.get("upper_tail")) < _f(row.get("conditional_floor"))
        )
        if row is comparator:
            classification = "MEAN-EDGE-DOMINATED"
        elif (
            _f(row.get("v12_expected_utility"))
            > _f(comparator.get("v12_expected_utility"))
            and _f(row.get("xpts_mean")) < _f(comparator.get("xpts_mean"))
        ):
            classification = "ROBUSTNESS-DOMINATED"
        elif (
            _f(row.get("v12_expected_utility"))
            >= _f(comparator.get("v12_expected_utility"))
            and _f(row.get("xpts_mean")) >= _f(comparator.get("xpts_mean"))
        ):
            classification = "MEAN-EDGE-DOMINATED"
        else:
            classification = "INDETERMINATE"
        row["robustness_classification"] = classification

    return choose_close_call_lineup(candidates, policy)


def _safe_captain_pool(starters: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = policy.get("captaincy") or {}
    min_start = _f(cfg.get("minimum_start_probability"), 0.70)
    max_dnp = _f(cfg.get("maximum_dnp_probability"), 0.15)
    pool = [p for p in starters if _f(p.get("start_probability")) >= min_start and _f(p.get("dnp_probability")) <= max_dnp]
    if len(pool) < 2:
        pool = list(starters)
    pool.sort(key=lambda p: (_f(p.get("captain_score")), _f(p.get("xpts_mean"))), reverse=True)
    return pool[: max(2, int(cfg.get("safe_pool_size") or 5))]


def _battle(best: dict[str, Any], second: dict[str, Any] | None, pmap: dict[int, dict[str, Any]]) -> dict[str, Any]:
    if not second:
        return {"status": "NO_ALTERNATIVE", "margin": None, "starter_side": [], "bench_side": []}
    best_ids = set(best.get("element_ids") or [])
    second_ids = set(second.get("element_ids") or [])
    starter_side = [pmap[e] for e in sorted(best_ids - second_ids) if e in pmap]
    bench_side = [pmap[e] for e in sorted(second_ids - best_ids) if e in pmap]
    best_decision = _f(best.get("decision_score"), _f(best.get("score")))
    second_decision = _f(second.get("decision_score"), _f(second.get("score")))
    best_base = _f(best.get("base_score"), _f(best.get("score")))
    second_base = _f(second.get("base_score"), _f(second.get("score")))
    margin = round(best_decision - second_decision, 4)
    intervals_overlap = not (
        _f(best.get("upper_tail")) < _f(second.get("conditional_floor"))
        or _f(second.get("upper_tail")) < _f(best.get("conditional_floor"))
    )
    p_outperform, regret = _pairwise_regret(best, second)
    if (
        _f(best.get("xpts_mean")) < _f(second.get("xpts_mean"))
        and _f(best.get("v12_expected_utility")) > _f(second.get("v12_expected_utility"))
    ):
        classification = "ROBUSTNESS-DOMINATED"
    elif (
        _f(best.get("xpts_mean")) >= _f(second.get("xpts_mean"))
        and _f(best.get("v12_expected_utility")) >= _f(second.get("v12_expected_utility"))
    ):
        classification = "MEAN-EDGE-DOMINATED"
    else:
        classification = "INDETERMINATE"
    threshold = _f((load_policy().get("battle") or {}).get("close_margin_threshold"))
    if threshold <= 0:
        raise RuntimeError("lineup battle close_margin_threshold must be positive")
    return {
        "status": "CLOSE" if abs(margin) < threshold else "CLEAR",
        "distribution_status": "UNCERTAINTY_OVERLAP" if intervals_overlap else "DISTRIBUTIONALLY_SEPARATED",
        "margin": margin,
        "base_score_margin": round(best_base - second_base, 4),
        "p_selected_outperforms_alternative": round(p_outperform, 6),
        "expected_regret": round(regret, 6),
        "robustness_classification": classification,
        "fixed_close_threshold_is_decision_authority": False,
        "starter_side": [{"element": p["element"], "name": p["name"], "position": p["position"], "selection_score": p["selection_score"]} for p in starter_side],
        "bench_side": [{"element": p["element"], "name": p["name"], "position": p["position"], "selection_score": p["selection_score"]} for p in bench_side],
        "alternative_formation": second.get("formation"),
        "risk_adjustment": {"selected": best.get("risk_adjustment"), "alternative": second.get("risk_adjustment")},
        "v12_robustness": {
            "selected_expected_utility": best.get("v12_expected_utility"),
            "alternative_expected_utility": second.get("v12_expected_utility"),
            "selected_conditional_floor": best.get("conditional_floor"),
            "alternative_conditional_floor": second.get("conditional_floor"),
            "selected_upper_tail": best.get("upper_tail"),
            "alternative_upper_tail": second.get("upper_tail"),
            "selected_auto_sub_preservation": best.get("auto_sub_preservation_value"),
            "selected_cameo_blocking_cost": best.get("cameo_auto_sub_blocking_cost"),
        },
    }


def _chip_context(lock: dict[str, Any], chips: dict[str, Any], planning_gw: int, policy: dict[str, Any]) -> dict[str, Any]:
    context = resolve_locked_chip_context(lock, chips, planning_gw, policy)
    context["ruleset_id"] = RULESET_ID
    return context


def _build_legacy_lineup_decision(
    projections: dict[str, Any],
    lock: dict[str, Any],
    chips: dict[str, Any],
    *,
    team: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = load_policy()
    planning_gw = int(projections.get("planning_gw") or 1)
    proj_map = {int(p["element"]): p for p in projections.get("players") or []}
    squad_rows, squad_authority, legacy_fixture_fallback = _authoritative_squad_rows(team, lock)
    authoritative_ids = [int(row.get("element") or -1) for row in squad_rows]
    missing = [element for element in authoritative_ids if element not in proj_map]
    if len(authoritative_ids) != int(SQUAD_RULES.get("squad_size") or 15) or missing:
        raise RuntimeError(f"cannot govern lineup: authoritative={len(authoritative_ids)} missing_projection_ids={missing}")

    players = [_player_row(proj_map[element], planning_gw, policy) for element in authoritative_ids]
    pmap = {int(p["element"]): p for p in players}
    candidates = _lineup_candidates(players, policy)
    if not candidates:
        raise RuntimeError("no legal starting XI candidate")
    best = candidates[0]
    best_ids = set(best["element_ids"])
    starters = [pmap[e] for e in best["element_ids"]]
    starters.sort(key=lambda p: ({"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}.get(str(p.get("position")), 9), -_f(p.get("selection_score"))))

    safe_pool = _safe_captain_pool(starters, policy)
    captain = safe_pool[0]
    vice_candidates = vice_rank(safe_pool, int(captain["element"]), policy)
    if not vice_candidates:
        raise RuntimeError("captaincy governance could not produce a distinct vice captain")
    vice = vice_candidates[0]

    bench_players = [p for p in players if int(p["element"]) not in best_ids]
    bench_gk = next((p for p in bench_players if p.get("position") == "GK"), None)
    outfield_bench = [p for p in bench_players if p.get("position") != "GK"]
    outfield_bench.sort(key=lambda p: (_f(p.get("bench_score")), _f(p.get("xpts_mean"))), reverse=True)
    if not bench_gk or len(outfield_bench) != int((LINEUP_RULES.get("bench") or {}).get("outfield") or 3):
        raise RuntimeError("invalid governed bench structure")

    alt_n = max(3, int((policy.get("selection") or {}).get("publish_alternative_lineups") or 6))
    alternatives = candidates[:alt_n]
    battle = _battle(best, candidates[1] if len(candidates) > 1 else None, pmap)
    formation_comparison = [
        {
            "formation": row.get("formation"),
            "base_score": row.get("base_score"),
            "decision_score": row.get("decision_score"),
            "xpts_mean": row.get("xpts_mean"),
            "xpts_std": row.get("xpts_std"),
            "risk_adjustment": row.get("risk_adjustment"),
            "selected": index == 0,
        }
        for index, row in enumerate(alternatives)
    ]
    bench_close = bench_battles(outfield_bench, policy)
    effective_lock = _effective_lock_context(team, lock, legacy_fixture_fallback)
    decision = {
        "generated_at": _now(),
        "model": policy.get("model_id"),
        "ruleset_id": RULESET_ID,
        "planning_gw": planning_gw,
        "squad_authority": squad_authority,
        "formation": best["formation"],
        "squad_rows": sorted(players, key=lambda p: ({"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}.get(str(p.get("position")), 9), -_f(p.get("selection_score")))),
        "starting_xi": starters,
        "captain": {
            "element": captain["element"], "name": captain["name"], "captain_score": captain["captain_score"],
            "dnp_probability": captain["dnp_probability"], "lower80": captain["lower80"], "upper80": captain["upper80"],
            "score_decomposition": captain.get("score_decomposition"),
        },
        "vice_captain": {
            "element": vice["element"], "name": vice["name"], "captain_score": vice["captain_score"], "vice_score": vice["vice_score"],
            "dnp_probability": vice["dnp_probability"], "attack_ceiling_proxy": vice.get("attack_ceiling_proxy"),
            "focality_proxy": vice.get("focality_proxy"), "score_decomposition": vice.get("score_decomposition"),
        },
        "captain_safe_pool": [
            {
                "element": p["element"], "name": p["name"], "captain_score": p["captain_score"], "vice_score": p["vice_score"],
                "start_probability": p["start_probability"], "dnp_probability": p["dnp_probability"],
                "attack_ceiling_proxy": p.get("attack_ceiling_proxy"), "focality_proxy": p.get("focality_proxy"),
            }
            for p in safe_pool
        ],
        "bench": {
            "gk": {"element": bench_gk["element"], "name": bench_gk["name"], "position": bench_gk["position"], "bench_score": bench_gk["bench_score"]},
            "order": [
                {"element": p["element"], "name": p["name"], "position": p["position"], "bench_score": p["bench_score"], "lower80": p["lower80"], "upper80": p["upper80"]}
                for p in outfield_bench
            ],
            "close_battles": bench_close,
        },
        "lineup_score": {
            "robust": best["decision_score"], "base_robust": best["base_score"], "xpts_mean": best["xpts_mean"], "xpts_std": best["xpts_std"],
            "risk_adjustment": best.get("risk_adjustment"),
        },
        "main_starting_xi_battle": battle,
        "formation_comparison": formation_comparison,
        "alternatives": alternatives,
        "chip_context": _chip_context(effective_lock, chips, planning_gw, policy),
        "governance": {
            "all_legal_xi_enumerated": True,
            "manual_squad_authority_preserved": True,
            "team_state_authority_consumed": not legacy_fixture_fallback,
            "legacy_lock_fixture_fallback": legacy_fixture_fallback,
            "raw_user_lock_context_consumed": bool(effective_lock),
            "rejected_user_lock_context_suppressed": not legacy_fixture_fallback and bool(lock) and not bool(effective_lock),
            "optimizer_does_not_mutate_locked_composition": True,
            "captain_dnp_guard_applied": True,
            "bench_order_is_model_output_not_manual_lock": True,
            "squad_selection_scores_published_for_report_transparency": True,
            "planning_chip_is_target_gw_scoped": True,
            "raw_xpts_preserved": True,
            "uncertainty_is_additive_not_replacement": True,
            "lineup_risk_adjustment_is_bounded": True,
            "no_artificial_attacking_formation_preference": True,
            "vice_uses_dedicated_score": True,
            "bench_uses_dedicated_score": True,
        },
    }
    return decision



def build_lineup_decision(
    projections: dict[str, Any],
    lock: dict[str, Any],
    chips: dict[str, Any],
    *,
    team: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Production orchestration for the V12-native P1.7 lineup owner.

    The pre-P1.7 implementation is retained as a migration/regression oracle.
    It is not the production selection owner after this switch.
    """
    planning_gw = int(projections.get("planning_gw") or 1)
    squad_rows, squad_authority, legacy_fixture_fallback = _authoritative_squad_rows(
        team, lock
    )
    authoritative_ids = [int(row.get("element") or -1) for row in squad_rows]
    native = optimize_lineup(
        projections,
        authoritative_ids,
        planning_gw=planning_gw,
        generated_at=_now(),
    )
    migration_cfg = dict(load_v12_lineup_config().get("migration") or {})
    execute_legacy_oracle = (
        migration_cfg.get("production_legacy_oracle_execution") is True
    )
    if execute_legacy_oracle:
        legacy = _build_legacy_lineup_decision(
            projections,
            lock,
            chips,
            team=team,
        )
        migration = compare_legacy_decision(legacy, native)
        if migration.get("unexpected_regression_count"):
            raise RuntimeError(
                "P1.7 ownership migration blocked by unexpected regression: "
                f"{migration.get('unexpected_regressions')}"
            )
    else:
        migration = {
            "status": "NOT_EXECUTED_PRODUCTION_POST_ACCEPTANCE",
            "classification": None,
            "unexpected_regressions": [],
            "unexpected_regression_count": 0,
            "ownership_migration_blocked": False,
            "oracle_status": migration_cfg.get(
                "oracle_status",
                "CI_REGRESSION_ORACLE_ONLY_AFTER_ACCEPTANCE",
            ),
            "acceptance_reference_sha": migration_cfg.get(
                "acceptance_reference_sha"
            ),
            "classification_taxonomy": [
                "EXACT_EQUIVALENT",
                "DISTRIBUTIONAL_IMPROVEMENT",
                "AUTOSUB_OPTION_VALUE_IMPROVEMENT",
                "CAMEO_BLOCKING_IMPROVEMENT",
                "CAPTAIN_FALLBACK_IMPROVEMENT",
                "BUG_FIX",
                "UNEXPECTED_REGRESSION",
            ],
        }
    effective_lock = _effective_lock_context(
        team, lock, legacy_fixture_fallback
    )
    native["squad_authority"] = squad_authority
    native["chip_context"] = _chip_context(
        effective_lock, chips, planning_gw, load_policy()
    )
    native["migration_comparison"] = migration
    native.setdefault("governance", {}).update({
        "production_owner": "V12_LINEUP_OPTIMIZER",
        "legacy_lineup_governance_status": (
            "MIGRATION_ORACLE"
            if execute_legacy_oracle
            else "REGRESSION_ORACLE_CI_ONLY"
        ),
        "legacy_oracle_executed_in_production": execute_legacy_oracle,
        "legacy_runtime_v3_dependency_added": False,
        "team_state_authority_consumed": not legacy_fixture_fallback,
        "legacy_lock_fixture_fallback": legacy_fixture_fallback,
        "raw_user_lock_context_consumed": bool(effective_lock),
        "rejected_user_lock_context_suppressed": (
            not legacy_fixture_fallback
            and bool(lock)
            and not bool(effective_lock)
        ),
        "scheduler_changed": False,
        "report_cadence_changed": False,
        "authority_added": False,
    })
    return native


def build_package_decision(
    package_optimizer: dict[str, Any],
    projections: dict[str, Any],
    lock: dict[str, Any],
    team: dict[str, Any],
) -> dict[str, Any]:
    """Consume P1.2B package utility as the only V12 package decision owner.

    Legacy optimizer artifacts remain migration/regression/performance
    references. They are fail-safe HOLD inputs and cannot authorize a V12
    transfer action after P1.2 ownership migration.
    """
    policy = load_policy()
    package_cfg = policy.get("package_governance") or {}
    pmap = {int(p["element"]): p for p in projections.get("players") or []}
    ledger_by_id = {
        int(p.get("element") or -1): p
        for p in team.get("team_value_ledger") or []
    }
    squad_rows, _, legacy_fixture_fallback = _authoritative_squad_rows(
        team, lock
    )
    current = []
    for owned in squad_rows:
        element = int(owned.get("element") or -1)
        proj = pmap.get(element)
        if not proj:
            continue
        ledger = ledger_by_id.get(element) or {}
        current.append(
            {
                "element": element,
                "name": proj.get("name"),
                "position": proj.get("position"),
                "team_id": int(proj.get("team_id") or -1),
                "now_cost": int(proj.get("now_cost") or 0),
                "sell_cost": (
                    int(ledger.get("sell_cost"))
                    if ledger.get("sell_cost") is not None
                    else None
                ),
            }
        )
    current_legal, current_legality_reason = v12_package_legal_squad(current)

    baseline = (
        team.get("projection_baseline")
        if isinstance(team.get("projection_baseline"), dict)
        else {}
    )
    phase_authoritative = lock.get("authoritative_phase") in set(
        package_cfg.get("authoritative_phases") or []
    )
    authoritative = phase_authoritative and (
        baseline.get("override_applied") is True if baseline else True
    )
    freeze = (
        bool(package_cfg.get("freeze_locked_composition_when_authoritative"))
        and authoritative
    )

    native = package_optimizer.get("model_owner") == "V12_PACKAGE_UTILITY"
    if native:
        routes = list(package_optimizer.get("routes") or [])
        by_id = {
            str(row.get("route_id")): dict(row)
            for row in routes
            if row.get("route_id") is not None
        }
        hold = by_id.get("HOLD")
        native_selected_id = str(
            package_optimizer.get("selected_route_id") or ""
        )
        native_selected = by_id.get(native_selected_id)
        if hold is None or native_selected is None:
            raise RuntimeError(
                "P1.2B package artifact missing HOLD or selected native route"
            )
        raw_overlay = package_optimizer.get("mini_league_overlay")
        overlay_payload = (
            deepcopy(raw_overlay)
            if isinstance(raw_overlay, dict)
            and raw_overlay.get("model_owner") == MINI_LEAGUE_OWNER
            else {
                "status": "NOT_RUN",
                "reason": "NO_OCCURRENCE_BOUND_V12_MINI_LEAGUE_OVERLAY",
            }
        )
        adjusted_id = native_selected_id
        overlay_changed = False
        if overlay_payload.get("model_owner") == MINI_LEAGUE_OWNER:
            baseline_route_id = str(
                (overlay_payload.get("football_baseline") or {}).get("route_id")
                or ""
            )
            delta = dict(overlay_payload.get("decision_delta") or {})
            candidate_adjusted = str(
                (overlay_payload.get("adjusted_decision") or {}).get("route_id")
                or native_selected_id
            )
            if baseline_route_id != native_selected_id:
                raise RuntimeError(
                    "P1.8 overlay football baseline does not match P1.2 selection"
                )
            if candidate_adjusted not in by_id:
                raise RuntimeError("P1.8 adjusted route is not a P1.2 legal route")
            overlay_changed = bool(delta.get("changed"))
            if overlay_changed and (
                (overlay_payload.get("coverage") or {}).get("state") != "FULL"
            ):
                raise RuntimeError(
                    "P1.8 partial/unavailable league evidence cannot switch route"
                )
            adjusted_id = candidate_adjusted
        adjusted_selected = by_id.get(adjusted_id) or native_selected
        selected = hold if freeze else adjusted_selected
        selected_id = str(selected.get("route_id") or "")
        selected_package = {"id": selected_id, **selected}
        final_ids = [
            int(value)
            for value in selected.get("final_squad_elements") or []
        ]
        final_rows = []
        for element in final_ids:
            proj = pmap.get(element)
            if not proj:
                continue
            final_rows.append(
                {
                    "element": element,
                    "position": proj.get("position"),
                    "team_id": int(proj.get("team_id") or -1),
                    "now_cost": int(proj.get("now_cost") or 0),
                }
            )
        final_legal, final_legality_reason = v12_package_legal_squad(
            final_rows
        )
        selected_legal = (
            selected.get("legal") is True and final_legal
        )
        selected_affordable = selected.get("affordable") is not False
        gate0_revalidated = bool(
            current_legal and selected_legal and selected_affordable
        )
        if not gate0_revalidated:
            raise RuntimeError(
                "P1.2 native package decision failed Gate0 revalidation"
            )
        decision = dict(package_optimizer.get("decision") or {})
        football_baseline_decision = deepcopy(decision)
        if overlay_changed and not freeze:
            decision = {
                **decision,
                "football_action": (
                    "HOLD"
                    if selected.get("classification") == "HOLD"
                    else "CHANGE"
                ),
                "operational_action": "PREPARE",
                "reason": "P1_8_DOWNSTREAM_OVERLAY_SWITCH_REQUIRES_EXISTING_EXECUTION_GATES",
                "mini_league_overlay_state": (
                    overlay_payload.get("decision_delta") or {}
                ).get("state"),
            }
        if freeze:
            decision = {
                "football_action": "HOLD",
                "operational_action": "WAIT",
                "reason": "AUTHORITATIVE_LOCK_FREEZE",
            }
        mc_policy = mc_invocation_policy(
            package_optimizer,
            route_id=native_selected_id,
        )
        raw_mc = package_optimizer.get("monte_carlo")
        if isinstance(raw_mc, dict):
            mc_payload = deepcopy(raw_mc)
        else:
            mc_payload = {
                "execution_state": "NOT_RUN",
                "reason": "NO_OCCURRENCE_BOUND_V12_MC_ARTIFACT",
            }
        mc_validation = validate_monte_carlo_provenance(
            mc_payload,
            required_for_close_decision=(
                mc_policy.get("status") == "MC_REQUIRED"
            ),
        )
        return {
            "generated_at": _now(),
            "model": "package_governance_v1",
            "ruleset_id": RULESET_ID,
            "planning_gw": int(projections.get("planning_gw") or 1),
            "selected_package": selected_package,
            "selected_package_id": selected_id,
            "optimizer_best_candidate_id": native_selected_id,
            "football_baseline_selected_package_id": native_selected_id,
            "mini_league_adjusted_package_id": adjusted_id,
            "manual_authority_override": freeze,
            "current_squad_legal": current_legal,
            "current_squad_legality_reason": current_legality_reason,
            "selected_squad_legality_reason": final_legality_reason,
            "gate0_revalidated": gate0_revalidated,
            "decision": decision,
            "football_baseline_decision": football_baseline_decision,
            "mini_league_overlay": overlay_payload,
            "decision_delta": deepcopy(
                overlay_payload.get("decision_delta")
                if isinstance(overlay_payload, dict)
                else None
            ),
            "model_evidence_binding": deepcopy(
                package_optimizer.get("model_evidence_binding")
            ),
            "package_frontier": deepcopy(
                package_optimizer.get("package_frontier")
            ),
            "monte_carlo": mc_payload,
            "monte_carlo_validation": mc_validation,
            "monte_carlo_invocation_policy": mc_policy,
            "governance": {
                "production_package_decision_owner": "V12_PACKAGE_UTILITY",
                "p1_2a_search_owner": "V12_PACKAGE_SEARCH",
                "native_package_utility_consumed": True,
                "legacy_package_optimizer_decision_authority": False,
                "legacy_package_optimizer_status": (
                    "MIGRATION_REGRESSION_PERFORMANCE_REFERENCE_ONLY"
                ),
                "optimizer_is_candidate_generator_only": False,
                "locked_composition_preserved": freeze,
                "manual_authority_wins": True,
                "team_state_authority_consumed": not legacy_fixture_fallback,
                "legacy_lock_fixture_fallback": legacy_fixture_fallback,
                "rejected_user_lock_cannot_freeze_package": (
                    bool(baseline)
                    and baseline.get("override_applied") is not True
                ),
                "scheduler_changed": False,
                "report_cadence_changed": False,
                "authority_added": False,
                "monte_carlo_owner": "V12_MONTE_CARLO",
                "mc_code_existence_is_not_execution": True,
                "mc_does_not_change_p1_2_action_logic": True,
                "mini_league_overlay_owner": MINI_LEAGUE_OWNER,
                "mini_league_overlay_downstream_only": True,
                "football_baseline_preserved": True,
                "mini_league_overlay_changed_route": overlay_changed,
            },
        }

    # Non-native optimizer artifacts can remain operational performance inputs
    # only. They never authorize a transfer decision after P1.2.
    legacy_packages = list(package_optimizer.get("packages") or [])
    legacy_best = (
        legacy_packages[0]
        if legacy_packages
        else package_optimizer.get("hold")
    )
    hold = package_optimizer.get("hold")
    if not hold:
        raise RuntimeError(
            "legacy package reference did not provide mandatory HOLD"
        )
    selected = hold
    selected_legal = bool(selected.get("legal")) and bool(
        (selected.get("score") or {}).get("valid")
    )
    gate0_revalidated = bool(current_legal and selected_legal)
    return {
        "generated_at": _now(),
        "model": "package_governance_v1",
        "ruleset_id": RULESET_ID,
        "planning_gw": int(projections.get("planning_gw") or 1),
        "selected_package": selected,
        "selected_package_id": selected.get("id"),
        "optimizer_best_candidate_id": (legacy_best or {}).get("id"),
        "manual_authority_override": freeze,
        "current_squad_legal": current_legal,
        "current_squad_legality_reason": current_legality_reason,
        "gate0_revalidated": gate0_revalidated,
        "decision": {
            "football_action": "HOLD",
            "operational_action": "PREPARE",
            "reason": "NATIVE_P1_2B_UTILITY_ARTIFACT_REQUIRED_FOR_CHANGE_ACTION",
        },
        "monte_carlo": {
            "execution_state": "NOT_RUN",
            "reason": "LEGACY_PACKAGE_ARTIFACT_IS_NONCANONICAL_MC_SOURCE",
        },
        "monte_carlo_validation": {
            "status": "PARTIAL",
            "execution_state": "NOT_RUN",
            "canonical_pass": False,
            "truthful_non_execution": True,
        },
        "monte_carlo_invocation_policy": {
            "status": "MC_NOT_REQUIRED",
            "reason": "LEGACY_PACKAGE_ARTIFACT_CANNOT_AUTHORIZE_V12_DECISION",
        },
        "governance": {
            "production_package_decision_owner": "V12_PACKAGE_UTILITY",
            "native_package_utility_consumed": False,
            "native_package_utility_status": (
                "NOT_MATERIALIZED_THIS_OCCURRENCE"
            ),
            "legacy_package_optimizer_decision_authority": False,
            "legacy_package_optimizer_status": (
                "MIGRATION_REGRESSION_PERFORMANCE_REFERENCE_ONLY"
            ),
            "legacy_candidate_can_trigger_change_action": False,
            "optimizer_is_candidate_generator_only": True,
            "locked_composition_preserved": freeze,
            "manual_authority_wins": True,
            "team_state_authority_consumed": not legacy_fixture_fallback,
            "legacy_lock_fixture_fallback": legacy_fixture_fallback,
            "rejected_user_lock_cannot_freeze_package": (
                bool(baseline)
                and baseline.get("override_applied") is not True
            ),
            "scheduler_changed": False,
            "report_cadence_changed": False,
            "authority_added": False,
        },
    }


def lineup_summary(lineup: dict[str, Any]) -> dict[str, Any]:
    return {
        "formation": lineup.get("formation"),
        "captain": (lineup.get("captain") or {}).get("name"),
        "vice_captain": (lineup.get("vice_captain") or {}).get("name"),
        "battle": (lineup.get("main_starting_xi_battle") or {}).get("status"),
        "risk_adjustment": (lineup.get("lineup_score") or {}).get("risk_adjustment"),
        "bench_close_battles": len(((lineup.get("bench") or {}).get("close_battles") or [])),
    }


def package_summary(package: dict[str, Any]) -> dict[str, Any]:
    overlay = package.get("mini_league_overlay") or {}
    delta = overlay.get("decision_delta") or {}
    return {
        "selected_package_id": package.get("selected_package_id"),
        "football_baseline_selected_package_id": package.get(
            "football_baseline_selected_package_id"
        ),
        "mini_league_adjusted_package_id": package.get(
            "mini_league_adjusted_package_id"
        ),
        "mini_league_overlay_status": overlay.get("status"),
        "mini_league_decision_delta": delta.get("state"),
        "manual_authority_override": package.get("manual_authority_override"),
        "gate0_revalidated": package.get("gate0_revalidated"),
    }


def run() -> dict[str, Any]:
    projections = read_json(DATA / "projections.json", {})
    package_optimizer = read_json(DATA / "package_optimizer.json", {})
    lock = json.loads((CONFIG / "locked_squad.json").read_text(encoding="utf-8"))
    chips = read_json(DATA / "chips.json", {})
    team = read_json(DATA / "team.json", {})
    lineup = build_lineup_decision(projections, lock, chips, team=team)
    package_optimizer = _materialize_native_mini_league_overlay(
        package_optimizer,
        lock,
        data_root=DATA,
    )
    package = build_package_decision(package_optimizer, projections, lock, team)
    if not lineup.get("formation") or len(lineup.get("starting_xi") or []) != int(LINEUP_RULES.get("starting_xi_size") or 11):
        raise RuntimeError("lineup governance failed legal XI contract")
    if not package.get("gate0_revalidated"):
        raise RuntimeError("package governance failed post-optimizer Gate0 revalidation")
    atomic_json(LINEUP_OUT, lineup)
    atomic_json(PACKAGE_DECISION_OUT, package)
    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {}).update({"lineup_decision": "data/lineup_decision.json", "package_decision": "data/package_decision.json"})
    latest["lineup_decision_summary"] = lineup_summary(lineup)
    latest["package_decision_summary"] = package_summary(package)
    atomic_json(DATA / "latest.json", latest)
    print(json.dumps({"formation": lineup.get("formation"), "captain": lineup.get("captain"), "vice": lineup.get("vice_captain"), "package": package.get("selected_package_id"), "manual_override": package.get("manual_authority_override")}, ensure_ascii=False))
    return {"lineup": lineup, "package": package}


if __name__ == "__main__":
    run()
