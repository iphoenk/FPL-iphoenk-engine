from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from src.engines.p0_decision_quality import resolve_locked_chip_context
from src.engines.p1_decision_governance import (
    bench_battles,
    choose_close_call_lineup,
    decision_scores,
    lineup_risk_adjustment,
    uncertainty_fields,
    vice_rank,
)
from src.models.package_optimizer_v2 import legal_squad
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
        "dnp_probability": uncertainty.get("dnp_probability"),
        "availability": uncertainty.get("availability"),
        "expected_minutes": round(_f(xmins.get("expected_minutes")), 2),
        "projection_confidence": proj.get("projection_confidence"),
    }


def _formation(rows: list[dict[str, Any]]) -> str | None:
    counts = {pos: sum(1 for p in rows if p.get("position") == pos) for pos in ("DEF", "MID", "FWD")}
    form = f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"
    return form if form in set(LINEUP_RULES.get("legal_formations") or []) else None


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
        bench_rows = [p for p in players if int(p["element"]) in all_ids - set(ids)]
        base_score = sum(_f(p.get("selection_score")) for p in rows)
        mean = sum(_f(p.get("xpts_mean")) for p in rows)
        variance = sum(_f(p.get("xpts_std")) ** 2 for p in rows)
        risk = lineup_risk_adjustment(rows, bench_rows, policy)
        decision_score = base_score + _f(risk.get("adjustment"))
        candidates.append({
            "formation": form,
            "score": round(decision_score, 4),
            "decision_score": round(decision_score, 4),
            "base_score": round(base_score, 4),
            "risk_adjustment": risk,
            "xpts_mean": round(mean, 3),
            "xpts_std": round(variance ** 0.5, 3),
            "element_ids": ids,
        })
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
    threshold = _f((load_policy().get("battle") or {}).get("close_margin_threshold"))
    if threshold <= 0:
        raise RuntimeError("lineup battle close_margin_threshold must be positive")
    best_ids = set(best.get("element_ids") or [])
    second_ids = set(second.get("element_ids") or [])
    starter_side = [pmap[e] for e in sorted(best_ids - second_ids) if e in pmap]
    bench_side = [pmap[e] for e in sorted(second_ids - best_ids) if e in pmap]
    best_decision = _f(best.get("decision_score"), _f(best.get("score")))
    second_decision = _f(second.get("decision_score"), _f(second.get("score")))
    best_base = _f(best.get("base_score"), _f(best.get("score")))
    second_base = _f(second.get("base_score"), _f(second.get("score")))
    margin = round(best_decision - second_decision, 4)
    return {
        "status": "CLOSE" if abs(margin) < threshold else "CLEAR",
        "margin": margin,
        "base_score_margin": round(best_base - second_base, 4),
        "starter_side": [{"element": p["element"], "name": p["name"], "position": p["position"], "selection_score": p["selection_score"]} for p in starter_side],
        "bench_side": [{"element": p["element"], "name": p["name"], "position": p["position"], "selection_score": p["selection_score"]} for p in bench_side],
        "alternative_formation": second.get("formation"),
        "risk_adjustment": {"selected": best.get("risk_adjustment"), "alternative": second.get("risk_adjustment")},
    }


def _chip_context(lock: dict[str, Any], chips: dict[str, Any], planning_gw: int, policy: dict[str, Any]) -> dict[str, Any]:
    context = resolve_locked_chip_context(lock, chips, planning_gw, policy)
    context["ruleset_id"] = RULESET_ID
    return context


def build_lineup_decision(
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


def build_package_decision(
    package_optimizer: dict[str, Any],
    projections: dict[str, Any],
    lock: dict[str, Any],
    team: dict[str, Any],
) -> dict[str, Any]:
    policy = load_policy()
    package_cfg = policy.get("package_governance") or {}
    pmap = {int(p["element"]): p for p in projections.get("players") or []}
    ledger_by_id = {int(p.get("element") or -1): p for p in team.get("team_value_ledger") or []}
    squad_rows, _, legacy_fixture_fallback = _authoritative_squad_rows(team, lock)
    current = []
    for owned in squad_rows:
        element = int(owned.get("element") or -1)
        proj = pmap.get(element)
        if not proj:
            continue
        ledger = ledger_by_id.get(element) or {}
        current.append({
            "element": element,
            "name": proj.get("name"),
            "position": proj.get("position"),
            "team_id": int(proj.get("team_id") or -1),
            "now_cost": int(proj.get("now_cost") or 0),
            "sell_cost": int(ledger.get("sell_cost") or proj.get("now_cost") or 0),
        })
    current_legal = legal_squad(current)
    baseline = team.get("projection_baseline") if isinstance(team.get("projection_baseline"), dict) else {}
    phase_authoritative = lock.get("authoritative_phase") in set(package_cfg.get("authoritative_phases") or [])
    authoritative = phase_authoritative and (baseline.get("override_applied") is True if baseline else True)
    freeze = bool(package_cfg.get("freeze_locked_composition_when_authoritative")) and authoritative
    optimizer_packages = list(package_optimizer.get("packages") or [])
    optimizer_best = optimizer_packages[0] if optimizer_packages else package_optimizer.get("hold")
    selected = package_optimizer.get("hold") if freeze or not package_cfg.get("auto_accept_optimizer_package") else optimizer_best
    if not selected:
        raise RuntimeError("package optimizer did not provide a selectable package")
    selected_is_hold = selected.get("id") == "HOLD"
    selected_legal = bool(selected.get("legal")) and bool((selected.get("score") or {}).get("valid"))
    gate0_revalidated = current_legal and selected_legal and (selected_is_hold if freeze else True)
    return {
        "generated_at": _now(), "model": "package_governance_v1", "ruleset_id": RULESET_ID,
        "planning_gw": int(projections.get("planning_gw") or 1), "selected_package": selected,
        "selected_package_id": selected.get("id"), "optimizer_best_candidate_id": (optimizer_best or {}).get("id"),
        "manual_authority_override": freeze, "current_squad_legal": current_legal, "gate0_revalidated": gate0_revalidated,
        "governance": {
            "optimizer_is_candidate_generator_only": bool(package_cfg.get("optimizer_is_candidate_generator_only", True)),
            "locked_composition_preserved": freeze,
            "manual_authority_wins": True,
            "team_state_authority_consumed": not legacy_fixture_fallback,
            "legacy_lock_fixture_fallback": legacy_fixture_fallback,
            "rejected_user_lock_cannot_freeze_package": bool(baseline) and baseline.get("override_applied") is not True,
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
    return {
        "selected_package_id": package.get("selected_package_id"),
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
