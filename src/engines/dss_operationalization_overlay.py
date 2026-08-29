from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from src.engines.p0_framework_health_overlay import _recount
from src.rules import LINEUP_RULES
from src.utils import DATA, ROOT, atomic_json, read_json

POLICY_PATH = ROOT / "config" / "intelligence" / "dss_operationalization.json"
HEALTH_PATH = DATA / "framework_health.json"
EVIDENCE_PATH = DATA / "dss_operational_evidence.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload.get("capabilities"), dict):
        raise RuntimeError("invalid DSS operationalization capability registry")
    return payload


def _projection_players() -> list[dict[str, Any]]:
    return list(read_json(DATA / "projections.json", {}).get("players") or [])


def _coverage(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]) -> tuple[int, float]:
    covered = sum(1 for row in rows if predicate(row))
    return covered, covered / max(1, len(rows))


def _minimum_ratio() -> float:
    return _f((load_policy().get("coverage") or {}).get("minimum_player_ratio"), 0.95)


def _projection_role_proxy(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    rows = _projection_players()
    covered, ratio = _coverage(
        rows,
        lambda p: all((p.get("xmins") or {}).get(k) is not None for k in ("start_probability", "bench_probability", "dnp_probability", "expected_minutes")),
    )
    contextual = sum(
        bool(p.get("historical_prior")) or _f((p.get("current_season") or {}).get("minutes")) > 0
        for p in rows
    )
    ok = bool(rows) and ratio >= _minimum_ratio()
    return ok, {
        "evidence_state": "AVAILABLE_PROXY" if ok else "INSUFFICIENT",
        "players": len(rows),
        "covered": covered,
        "coverage_ratio": round(ratio, 4),
        "contextual_usage_players": contextual,
        "fallback": spec.get("fallback"),
        "no_unsupported_role_claim": True,
    }


def _optional_player_role(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    rows = _projection_players()
    keys = [str(k) for k in spec.get("keys") or []]
    assigned = 0
    for player in rows:
        prior = player.get("historical_prior") or {}
        if any(player.get(key) is not None or prior.get(key) is not None for key in keys):
            assigned += 1
    if not rows:
        return False, {"evidence_state": "INSUFFICIENT", "reason": "projection players missing"}
    state = "AVAILABLE" if assigned else "UNAVAILABLE_WITH_SAFE_FALLBACK"
    return True, {
        "evidence_state": state,
        "players": len(rows),
        "explicit_role_players": assigned,
        "keys_checked": keys,
        "fallback": spec.get("fallback"),
        "missing_role_evidence_fabricated": False,
    }


def _projection_rates(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    rows = _projection_players()
    fields = [str(x) for x in spec.get("required_rate_fields") or []]
    covered, ratio = _coverage(
        rows,
        lambda p: all((p.get("rates") or {}).get(field) is not None for field in fields)
        and all((p.get("rates") or {}).get("sources", {}).get(field) for field in fields),
    )
    ok = bool(rows) and ratio >= _minimum_ratio()
    return ok, {
        "evidence_state": "AVAILABLE" if ok else "INSUFFICIENT",
        "players": len(rows),
        "covered": covered,
        "coverage_ratio": round(ratio, 4),
        "rate_fields": fields,
        "fallback": spec.get("fallback"),
    }


def _neutral_schedule_guard(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    rows = _projection_players()
    covered, ratio = _coverage(rows, lambda p: (p.get("xmins") or {}).get("congestion_factor") is not None)
    adjusted = sum(_f((p.get("xmins") or {}).get("congestion_factor"), 1.0) < 0.999 for p in rows)
    ok = bool(rows) and ratio >= _minimum_ratio()
    return ok, {
        "evidence_state": "AVAILABLE" if adjusted else "UNAVAILABLE_WITH_SAFE_FALLBACK",
        "players": len(rows),
        "covered": covered,
        "coverage_ratio": round(ratio, 4),
        "players_with_verified_adjustment": adjusted,
        "fallback": spec.get("fallback"),
        "neutral_factor_is_not_negative_evidence": True,
    }


def _fixture_schedule(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    rows = _projection_players()
    fixtures = [
        fixture
        for player in rows
        for gw in (player.get("xpts_by_gw") or [])
        for fixture in (gw.get("fixtures") or [])
    ]
    kickoff = sum(bool(row.get("kickoff_time")) for row in fixtures)
    ok = bool(rows) and bool(fixtures)
    state = "AVAILABLE" if kickoff else "UNAVAILABLE_WITH_SAFE_FALLBACK"
    return ok, {
        "evidence_state": state,
        "projected_fixtures": len(fixtures),
        "kickoff_time_rows": kickoff,
        "fallback": spec.get("fallback"),
    }


def _optional_prior(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    rows = _projection_players()
    historical = sum(bool(p.get("historical_prior")) for p in rows)
    current = sum(_f((p.get("current_season") or {}).get("minutes")) > 0 for p in rows)
    ok = bool(rows)
    return ok, {
        "evidence_state": "UNAVAILABLE_WITH_SAFE_FALLBACK",
        "players": len(rows),
        "historical_prior_players": historical,
        "current_season_usage_players": current,
        "fallback": spec.get("fallback"),
        "preseason_evidence_fabricated": False,
    }


def _historical_context(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    prior = read_json(DATA / "prior_season.json", {})
    rows = _projection_players()
    matched = sum(bool(p.get("historical_prior")) for p in rows)
    coverage = _f((prior.get("coverage") or {}).get("coverage_ratio"))
    ok = bool(prior.get("players")) and bool(rows) and matched > 0 and coverage > 0
    return ok, {
        "evidence_state": "AVAILABLE" if ok else "INSUFFICIENT",
        "prior_model": prior.get("model"),
        "prior_season": prior.get("season"),
        "projection_players": len(rows),
        "matched_players": matched,
        "source_coverage_ratio": coverage,
        "fallback": spec.get("fallback"),
    }


def _prediction_quality(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    quality = read_json(DATA / "prediction_quality.json", {})
    rows = _projection_players()
    guarded = sum((p.get("xmins") or {}).get("small_sample_guard") is not None for p in rows)
    ok = quality.get("status") == "HEALTHY" and bool(rows) and guarded == len(rows)
    return ok, {
        "evidence_state": "AVAILABLE" if ok else "INSUFFICIENT",
        "prediction_quality": quality.get("status"),
        "failed_checks": quality.get("failed_checks"),
        "small_sample_guard_coverage": guarded,
        "players": len(rows),
        "fallback": spec.get("fallback"),
    }


def _price_value(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    rows = _projection_players()
    covered, ratio = _coverage(
        rows,
        lambda p: int(p.get("now_cost") or 0) > 0
        and all(((p.get("horizons") or {}).get(str(h)) or {}).get("mean") is not None for h in (3, 5)),
    )
    ok = bool(rows) and ratio >= _minimum_ratio()
    return ok, {
        "evidence_state": "AVAILABLE" if ok else "INSUFFICIENT",
        "players": len(rows),
        "covered": covered,
        "coverage_ratio": round(ratio, 4),
        "fallback": spec.get("fallback"),
    }


def _ownership_context(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    rows = _projection_players()
    covered, ratio = _coverage(rows, lambda p: p.get("ownership_pct") is not None)
    ok = bool(rows) and ratio >= _minimum_ratio()
    return ok, {
        "evidence_state": "AVAILABLE" if ok else "INSUFFICIENT",
        "players": len(rows),
        "covered": covered,
        "coverage_ratio": round(ratio, 4),
        "fallback": spec.get("fallback"),
        "effective_ownership_invented": False,
    }


def _transfer_momentum(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    universe = read_json(DATA / "universe.json", {})
    price_cache = read_json(DATA / "price_cache.json", {})
    rows = list(universe.get("players") or [])
    cache = price_cache.get("players") or {}

    covered, ratio = _coverage(
        rows,
        lambda p: p.get("element") is not None
        and p.get("transfers_in_event") is not None
        and p.get("transfers_out_event") is not None,
    )
    linked = 0
    price_matches = 0
    total_in = 0
    total_out = 0
    active_momentum = 0
    for player in rows:
        element = player.get("element")
        if element is None:
            continue
        cache_row = cache.get(str(element)) or cache.get(element)
        if isinstance(cache_row, dict):
            linked += 1
            if cache_row.get("now_cost") is not None and player.get("now_cost") is not None:
                if int(cache_row.get("now_cost")) == int(player.get("now_cost")):
                    price_matches += 1
        if player.get("transfers_in_event") is None or player.get("transfers_out_event") is None:
            continue
        transfers_in = int(player.get("transfers_in_event") or 0)
        transfers_out = int(player.get("transfers_out_event") or 0)
        total_in += transfers_in
        total_out += transfers_out
        if transfers_in != transfers_out:
            active_momentum += 1

    linked_ratio = linked / max(1, len(rows))
    price_match_ratio = price_matches / max(1, len(rows))
    minimum = _minimum_ratio()
    ok = bool(rows) and ratio >= minimum and linked_ratio >= minimum and price_match_ratio >= minimum
    return ok, {
        "evidence_state": "AVAILABLE" if ok else "INSUFFICIENT",
        "players": len(rows),
        "transfer_count_covered": covered,
        "transfer_count_coverage_ratio": round(ratio, 4),
        "price_cache_linked": linked,
        "price_cache_linkage_ratio": round(linked_ratio, 4),
        "current_price_matches": price_matches,
        "current_price_match_ratio": round(price_match_ratio, 4),
        "players_with_nonzero_net_momentum": active_momentum,
        "total_transfers_in_event": total_in,
        "total_transfers_out_event": total_out,
        "net_transfers_event": total_in - total_out,
        "source": "Official FPL universe transfer counts + governed market-state price cache",
        "fallback": spec.get("fallback"),
        "external_threshold_invented": False,
        "predicted_price_change_invented": False,
    }


def _learning_loop(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    accuracy = read_json(DATA / "prediction_accuracy.json", {})
    ledger = read_json(DATA / "prediction_ledger.json", {})
    records = ledger.get("records") or {}
    settled = list(accuracy.get("settled_gameweeks") or [])
    freeze_ok = accuracy.get("freeze_policy") == "last_pre_deadline_snapshot"
    ok = bool(records) and freeze_ok
    return ok, {
        "evidence_state": "AVAILABLE" if settled else "ARMED_NO_SETTLED_SAMPLE",
        "ledger_records": len(records),
        "settled_gameweeks": settled,
        "collecting_gameweeks": list(accuracy.get("collecting_gameweeks") or []),
        "sample_size": (accuracy.get("overall") or {}).get("sample_size", 0),
        "freeze_policy": accuracy.get("freeze_policy"),
        "fallback": spec.get("fallback"),
        "zero_settled_samples_is_not_module_failure": True,
    }


def _lineup_output(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    lineup = read_json(DATA / "lineup_decision.json", {})
    xi = list(lineup.get("starting_xi") or [])
    xi_ids = {int(row.get("element")) for row in xi if row.get("element") is not None}
    captain = int((lineup.get("captain") or {}).get("element") or -1)
    vice = int((lineup.get("vice_captain") or {}).get("element") or -1)
    bench = lineup.get("bench") or {}
    safe = {int(row.get("element")) for row in lineup.get("captain_safe_pool") or [] if row.get("element") is not None}
    ok = (
        len(xi) == int(LINEUP_RULES.get("starting_xi_size") or 0)
        and lineup.get("formation") in set(LINEUP_RULES.get("legal_formations") or [])
        and captain in xi_ids and vice in xi_ids and captain != vice
        and captain in safe and vice in safe
        and bool(bench.get("gk"))
        and len(bench.get("order") or []) == int((LINEUP_RULES.get("bench") or {}).get("outfield") or 0)
    )
    return ok, {
        "evidence_state": "AVAILABLE" if ok else "INSUFFICIENT",
        "formation": lineup.get("formation"),
        "starting_xi": len(xi),
        "safe_pool": len(safe),
        "captain": (lineup.get("captain") or {}).get("name"),
        "vice_captain": (lineup.get("vice_captain") or {}).get("name"),
        "fallback": spec.get("fallback"),
    }


def _package_guardrail(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    package = read_json(DATA / "package_optimizer.json", {})
    governance = package.get("governance") or {}
    key = str(spec.get("guardrail") or "")
    enabled = governance.get(key) is True
    return enabled, {
        "evidence_state": "AVAILABLE" if enabled else "INSUFFICIENT",
        "guardrail": key,
        "enabled": enabled,
        "package_status": package.get("status"),
        "package_count": package.get("package_count"),
        "governance": governance,
    }


EVALUATORS: dict[str, Callable[[dict[str, Any]], tuple[bool, dict[str, Any]]]] = {
    "projection_role_proxy": _projection_role_proxy,
    "optional_player_role": _optional_player_role,
    "projection_rates": _projection_rates,
    "neutral_schedule_guard": _neutral_schedule_guard,
    "fixture_schedule": _fixture_schedule,
    "optional_prior": _optional_prior,
    "historical_context": _historical_context,
    "prediction_quality": _prediction_quality,
    "price_value": _price_value,
    "ownership_context": _ownership_context,
    "transfer_momentum": _transfer_momentum,
    "learning_loop": _learning_loop,
    "lineup_output": _lineup_output,
    "package_guardrail": _package_guardrail,
}


def _evaluate_probe(probe: str, spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    evaluator_name = str(spec.get("evaluator") or "")
    evaluator = EVALUATORS.get(evaluator_name)
    if evaluator is None:
        return False, {"evidence_state": "INSUFFICIENT", "reason": f"unknown evaluator {evaluator_name}"}
    ok, detail = evaluator(spec)
    detail = {
        "operationalized_by": "dss_operationalization_overlay_v1",
        "owner": spec.get("owner"),
        "evaluator": evaluator_name,
        "probe": probe,
        **detail,
    }
    return ok and bool(detail), detail


def run(strict: bool = True) -> dict[str, Any]:
    health = read_json(HEALTH_PATH, {})
    if not health:
        raise RuntimeError("framework_health.json missing before DSS operationalization")
    policy = load_policy()
    capabilities = policy.get("capabilities") or {}
    evidence_rows: list[dict[str, Any]] = []

    for group in ("dss_core", "dss_extensions", "enhancements"):
        for item in (health.get(group) or {}).get("items") or []:
            if item.get("status") != "PARTIAL":
                continue
            probe = str(item.get("probe") or "")
            spec = capabilities.get(probe)
            if not isinstance(spec, dict):
                evidence_rows.append({
                    "group": group, "id": item.get("id"), "probe": probe,
                    "status": "UNRESOLVED", "reason": "no evidence contract registered",
                })
                continue
            ok, detail = _evaluate_probe(probe, spec)
            evidence_rows.append({
                "group": group, "id": item.get("id"), "probe": probe,
                "status": "ACTIVE" if ok else "UNRESOLVED", "detail": detail,
            })
            item["detail"] = detail
            if ok:
                item["status"] = "ACTIVE"

    _recount(health)
    unresolved = []
    for group in ("dss_core", "dss_extensions", "enhancements"):
        for item in (health.get(group) or {}).get("items") or []:
            if item.get("status") != "ACTIVE":
                unresolved.append({"group": group, "id": item.get("id"), "probe": item.get("probe"), "status": item.get("status")})

    evidence = {
        "generated_at": _now(),
        "model": policy.get("model_id"),
        "policy": policy.get("policy"),
        "evaluated": evidence_rows,
        "unresolved": unresolved,
        "counts": {
            "core": (health.get("dss_core") or {}).get("counts"),
            "extensions": (health.get("dss_extensions") or {}).get("counts"),
            "enhancements": (health.get("enhancements") or {}).get("counts"),
        },
        "gate0": (health.get("gate0") or {}).get("counts"),
    }
    atomic_json(EVIDENCE_PATH, evidence)

    health["dss_operationalization"] = {
        "status": "ACTIVE" if not unresolved else "INCOMPLETE",
        "model": policy.get("model_id"),
        "evidence_file": "data/dss_operational_evidence.json",
        "unresolved": unresolved,
        "module_health_separate_from_signal_availability": True,
        "missing_external_evidence_is_never_fabricated": True,
    }
    health.setdefault("governance", {}).update({
        "all_active_dss_requires_runtime_evidence_contract": True,
        "module_health_is_not_equivalent_to_external_signal_availability": True,
        "unavailable_external_signal_requires_explicit_safe_fallback": True,
    })
    _recount(health)
    atomic_json(HEALTH_PATH, health)

    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {})["dss_operational_evidence"] = "data/dss_operational_evidence.json"
    latest["dss_operationalization_summary"] = {
        "status": health["dss_operationalization"]["status"],
        "core": (health.get("dss_core") or {}).get("counts"),
        "extensions": (health.get("dss_extensions") or {}).get("counts"),
        "enhancements": (health.get("enhancements") or {}).get("counts"),
        "overall": health.get("overall"),
        "go_allowed": health.get("go_allowed"),
    }
    atomic_json(DATA / "latest.json", latest)

    if strict:
        gate_fail = int(((health.get("gate0") or {}).get("counts") or {}).get("FAIL", 0))
        if unresolved or gate_fail or health.get("overall") != "GREEN" or health.get("go_allowed") is not True:
            raise RuntimeError(
                "DSS operationalization strict gate failed: "
                + json.dumps({"unresolved": unresolved, "gate_fail": gate_fail, "overall": health.get("overall"), "go_allowed": health.get("go_allowed")}, ensure_ascii=False)
            )

    print(json.dumps({
        "status": health["dss_operationalization"]["status"],
        "core": (health.get("dss_core") or {}).get("counts"),
        "extensions": (health.get("dss_extensions") or {}).get("counts"),
        "enhancements": (health.get("enhancements") or {}).get("counts"),
        "overall": health.get("overall"),
        "go_allowed": health.get("go_allowed"),
    }, ensure_ascii=False))
    return health


if __name__ == "__main__":
    run(strict=True)
