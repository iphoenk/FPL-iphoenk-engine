from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from src.rules import ASSIST_POINTS, GOAL_POINTS
from src.utils import DATA, ROOT, atomic_json, read_json

POLICY_PATH = ROOT / "config" / "intelligence" / "dss_watchlist.json"
CORE_REGISTRY_PATH = ROOT / "config" / "dss_core_registry.json"
EXT_REGISTRY_PATH = ROOT / "config" / "dss_extension_registry.json"
OUT = DATA / "dss_watchlist.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_core_registry() -> dict[str, Any]:
    return json.loads(CORE_REGISTRY_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_extension_registry() -> dict[str, Any]:
    return json.loads(EXT_REGISTRY_PATH.read_text(encoding="utf-8"))


def _registry_audit(framework: dict[str, Any], key: str, registry: dict[str, Any]) -> dict[str, Any]:
    current = framework.get(key) or {}
    states = {str(row.get("id")): str(row.get("status") or "UNKNOWN") for row in current.get("items") or []}
    rows = []
    for module in registry.get("modules") or []:
        module_id = str(module.get("id"))
        rows.append({
            "id": module_id,
            "name": module.get("name"),
            "critical": bool(module.get("critical")),
            "category": module.get("category"),
            "framework_status": states.get(module_id, "MISSING"),
        })
    counts = Counter(row["framework_status"] for row in rows)
    critical_failed = [row["id"] for row in rows if row["critical"] and row["framework_status"] in {"FAILED", "MISSING"}]
    critical_partial = [row["id"] for row in rows if row["critical"] and row["framework_status"] == "PARTIAL"]
    return {
        "registry": registry.get("registry"),
        "declared": len(registry.get("modules") or []),
        "traversed": len(rows),
        "counts": dict(counts),
        "critical_failed": critical_failed,
        "critical_partial": critical_partial,
        "modules": rows,
    }


def _horizon(proj: dict[str, Any], horizon: int, field: str = "mean") -> float:
    return _f(((proj.get("horizons") or {}).get(str(horizon)) or {}).get(field))


def _owned_context(team: dict[str, Any], projections: dict[str, Any]) -> tuple[set[int], dict[str, list[dict[str, Any]]]]:
    pmap = {int(row["element"]): row for row in projections.get("players") or [] if row.get("element") is not None}
    owned_ids: set[int] = set()
    by_position: dict[str, list[dict[str, Any]]] = {p: [] for p in ("GK", "DEF", "MID", "FWD")}
    for ledger in team.get("team_value_ledger") or []:
        element = int(ledger.get("element") or -1)
        proj = pmap.get(element)
        if not proj:
            continue
        owned_ids.add(element)
        by_position.setdefault(str(proj.get("position")), []).append({
            "element": element,
            "name": proj.get("name"),
            "sell_cost": int(ledger.get("sell_cost") or proj.get("now_cost") or 0),
            "h5": _horizon(proj, 5),
            "h3": _horizon(proj, 3),
        })
    for rows in by_position.values():
        rows.sort(key=lambda row: (row["h5"], row["h3"], row["sell_cost"]))
    return owned_ids, by_position


def _package_map(package_optimizer: dict[str, Any]) -> dict[int, dict[str, Any]]:
    hold_score = _f((((package_optimizer.get("hold") or {}).get("score") or {}).get("robust_score")))
    best: dict[int, dict[str, Any]] = {}
    for package in package_optimizer.get("packages") or []:
        if package.get("legal") is not True or ((package.get("score") or {}).get("valid")) is not True:
            continue
        robust = _f((package.get("score") or {}).get("robust_score"))
        gain = robust - hold_score
        for incoming in package.get("ins") or []:
            element = int(incoming.get("element") or -1)
            row = {
                "package_id": package.get("id"),
                "robust_gain_vs_hold": round(gain, 3),
                "resulting_itb": (package.get("affordability") or {}).get("resulting_itb"),
                "changes": package.get("changes"),
            }
            if element not in best or gain > _f(best[element].get("robust_gain_vs_hold")):
                best[element] = row
    return best


def _price_map(prices: dict[str, Any], alerts: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in prices.get("players") or []:
        if row.get("element") is None:
            continue
        out[int(row["element"])] = {
            "official_progress_pct": row.get("official_progress_pct"),
            "official_hourly_rate_pct": row.get("official_hourly_rate_pct"),
            "risk_direction": row.get("risk_direction"),
            "urgency": row.get("urgency"),
            "predicted_change_deadline": row.get("predicted_change_deadline"),
        }
    for row in alerts.get("alerts") or []:
        if row.get("element") is None:
            continue
        element = int(row["element"])
        target = out.setdefault(element, {})
        target.update({
            "official_progress_pct": row.get("official_progress_pct", target.get("official_progress_pct")),
            "official_hourly_rate_pct": row.get("official_hourly_rate_pct", target.get("official_hourly_rate_pct")),
            "risk_direction": row.get("risk_direction", target.get("risk_direction")),
            "urgency": row.get("urgency", target.get("urgency")),
            "predicted_change_deadline": row.get("predicted_change_deadline", target.get("predicted_change_deadline")),
            "prediction_source": row.get("prediction_source"),
            "official_projection_health": row.get("official_projection_health"),
        })
    return out


def _explicit_role_evidence(proj: dict[str, Any]) -> dict[str, Any]:
    historical = proj.get("historical_prior") or {}
    found = {}
    for key in ("penalty_share", "penalty_role", "set_piece_share", "set_piece_role"):
        value = proj.get(key) if proj.get(key) is not None else historical.get(key)
        if value is not None:
            found[key] = value
    return found


def _dimension(status: str, evidence: str, credit: dict[str, float]) -> dict[str, Any]:
    status = status if status in credit else "MISSING"
    return {"status": status, "evidence_credit": round(_f(credit.get(status)), 3), "evidence": evidence}


def _candidate_dimensions(
    proj: dict[str, Any],
    package_context: dict[str, Any] | None,
    owned_position: list[dict[str, Any]],
    framework_core: dict[str, str],
) -> dict[str, dict[str, Any]]:
    cfg = load_policy()
    credit = cfg.get("evidence_credit") or {}
    xmins = proj.get("xmins") or {}
    historical = proj.get("historical_prior") or {}
    rates = proj.get("rates") or {}
    sources = rates.get("sources") or {}
    explicit_role = _explicit_role_evidence(proj)
    xmins_present = all(xmins.get(key) is not None for key in ("start_probability", "dnp_probability", "expected_minutes"))
    horizons_present = all(((proj.get("horizons") or {}).get(str(h)) or {}).get("mean") is not None for h in (3, 5))
    rates_present = rates.get("xg90") is not None and rates.get("xa90") is not None
    prior_present = bool(historical)
    tactical_state = framework_core.get("DSS-07", "MISSING")
    competition_state = framework_core.get("DSS-09", "MISSING")

    role_status = "SUPPORTED" if tactical_state == "ACTIVE" and (prior_present or _f((proj.get("current_season") or {}).get("minutes")) > 0) else "PROXY" if xmins_present else "MISSING"
    competition_status = "SUPPORTED" if competition_state == "ACTIVE" and xmins_present else "PROXY" if xmins_present else "MISSING"
    underlying_proxy = any("position_prior" in str(value) for value in sources.values()) and not prior_present and _f((proj.get("current_season") or {}).get("minutes")) <= 0
    underlying_status = "PROXY" if underlying_proxy and rates_present else "SUPPORTED" if rates_present else "MISSING"
    system_status = "PROXY" if xmins_present else "MISSING"
    setpiece_status = "SUPPORTED" if explicit_role else "MISSING"
    squad_fit_status = "SUPPORTED" if package_context else "PROXY" if owned_position else "MISSING"

    return {
        "role": _dimension(role_status, "xMins + current/previous-season usage; tactical-role registry state respected", credit),
        "xmins": _dimension("SUPPORTED" if xmins_present else "MISSING", "start, bench/DNP distribution and expected minutes", credit),
        "fixtures_3_5": _dimension("SUPPORTED" if horizons_present else "MISSING", "3-GW and 5-GW projection horizons", credit),
        "underlying": _dimension(underlying_status, "xG/xA/bonus/DefCon/save rate bundle with shrinkage-source provenance", credit),
        "system_fit": _dimension(system_status, "starter-security and usage proxy; no unsupported formation-role claim", credit),
        "competition": _dimension(competition_status, "bench and DNP probability proxy for positional competition/rotation", credit),
        "set_piece_penalty": _dimension(setpiece_status, "explicit set-piece/penalty evidence" if explicit_role else "no player-specific role evidence; not fabricated", credit),
        "price_value": _dimension("SUPPORTED" if int(proj.get("now_cost") or 0) > 0 and horizons_present else "MISSING", "current Official price against multi-GW projection", credit),
        "squad_fit": _dimension(squad_fit_status, "legal package evidence" if package_context else "same-position owned replacement proxy", credit),
    }


def _coverage(dimensions: dict[str, dict[str, Any]]) -> tuple[float, float]:
    cfg = load_policy()
    weights = cfg.get("dimension_weights") or {}
    total_weight = sum(_f(weights.get(key), 0.0) for key in dimensions) or 1.0
    weighted = sum(_f(weights.get(key), 0.0) * _f(value.get("evidence_credit")) for key, value in dimensions.items()) / total_weight
    critical = (cfg.get("admission") or {}).get("critical_dimensions") or []
    critical_score = min((_f((dimensions.get(key) or {}).get("evidence_credit")) for key in critical), default=0.0)
    return round(weighted, 4), round(critical_score, 4)


def _market_score(price: dict[str, Any]) -> float:
    direction = str(price.get("risk_direction") or "").upper()
    urgency = str(price.get("urgency") or "").upper()
    if direction == "RISE":
        return {"CRITICAL": 1.0, "HIGH": 0.85, "MEDIUM": 0.70, "LOW": 0.60}.get(urgency, 0.60)
    if direction == "FALL":
        return {"CRITICAL": 0.0, "HIGH": 0.15, "MEDIUM": 0.30, "LOW": 0.40}.get(urgency, 0.40)
    return 0.50


def _raw_candidate(
    proj: dict[str, Any],
    package_context: dict[str, Any] | None,
    owned_position: list[dict[str, Any]],
    price: dict[str, Any],
    framework_core: dict[str, str],
) -> dict[str, Any]:
    xmins = proj.get("xmins") or {}
    rates = proj.get("rates") or {}
    historical = proj.get("historical_prior") or {}
    start = _clamp(_f(xmins.get("start_probability")))
    dnp = _clamp(_f(xmins.get("dnp_probability")))
    minutes = _clamp(_f(xmins.get("expected_minutes")) / 90.0)
    prior_start = _clamp(_f(historical.get("start_probability"), start)) if historical else start
    role_security = 0.55 * start + 0.25 * minutes + 0.20 * prior_start
    xmins_security = start * (0.55 + 0.45 * minutes) * (1.0 - 0.65 * dnp)
    goal_points = _f(GOAL_POINTS.get(int(proj.get("element_type") or 4), 4), 4)
    underlying = (
        _f(rates.get("xg90")) * goal_points
        + _f(rates.get("xa90")) * _f(ASSIST_POINTS, 3.0)
        + _f(rates.get("bonus90"))
        + _f(rates.get("dc90"))
        + _f(rates.get("saves90")) / 3.0
    )
    h3, h5, h10, h15 = (_horizon(proj, h) for h in (3, 5, 10, 15))
    price_m = max(3.5, _f(proj.get("now_cost")) / 10.0)
    weakest = owned_position[0] if owned_position else None
    replacement_delta = h5 - _f((weakest or {}).get("h5")) if weakest else 0.0
    package_gain = _f((package_context or {}).get("robust_gain_vs_hold"))
    dimensions = _candidate_dimensions(proj, package_context, owned_position, framework_core)
    evidence_coverage, critical_coverage = _coverage(dimensions)
    return {
        "element": int(proj["element"]),
        "name": proj.get("name"),
        "team": proj.get("team"),
        "team_id": int(proj.get("team_id") or -1),
        "position": proj.get("position"),
        "now_cost": int(proj.get("now_cost") or 0),
        "price": round(price_m, 1),
        "status": proj.get("status"),
        "ownership_pct": proj.get("ownership_pct"),
        "projection_confidence": str(proj.get("projection_confidence") or "UNKNOWN").upper(),
        "xmins": {
            "expected_minutes": xmins.get("expected_minutes"),
            "start_probability": xmins.get("start_probability"),
            "bench_probability": xmins.get("bench_probability"),
            "dnp_probability": xmins.get("dnp_probability"),
        },
        "horizons": {str(h): {"mean": _horizon(proj, h), "std": _horizon(proj, h, "std")} for h in (3, 5, 10, 15)},
        "underlying": {
            "xg90": rates.get("xg90"), "xa90": rates.get("xa90"), "bonus90": rates.get("bonus90"),
            "dc90": rates.get("dc90"), "saves90": rates.get("saves90"), "sources": rates.get("sources"),
        },
        "historical_prior": {
            "available": bool(historical),
            "start_probability": historical.get("start_probability"),
            "minutes": historical.get("minutes"),
            "identity_match": historical.get("identity_match"),
        },
        "price_risk": price,
        "package_context": package_context,
        "direct_replacement_context": {
            "owned_element": (weakest or {}).get("element"),
            "owned_name": (weakest or {}).get("name"),
            "owned_h5": (weakest or {}).get("h5"),
            "candidate_h5_delta": round(replacement_delta, 3) if weakest else None,
        },
        "dimensions": dimensions,
        "evidence_coverage": evidence_coverage,
        "critical_dimension_score": critical_coverage,
        "raw_metrics": {
            "short_horizon": h3 / 3.0,
            "primary_horizon": h5 / 5.0,
            "strategic_horizon": ((h10 / 10.0) + (h15 / 15.0)) / 2.0,
            "xmins_security": xmins_security,
            "role_security": role_security,
            "underlying": underlying,
            "value": h5 / price_m,
            "squad_fit": package_gain + max(0.0, replacement_delta) * 0.25,
            "market_overlay": _market_score(price),
        },
    }


def _normalise(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    metric_names = list((rows[0].get("raw_metrics") or {}).keys())
    weights = load_policy().get("ranking_weights") or {}
    confidence_mult = load_policy().get("confidence_multiplier") or {}
    for metric in metric_names:
        values = [_f((row.get("raw_metrics") or {}).get(metric)) for row in rows]
        low, high = min(values), max(values)
        for row, value in zip(rows, values):
            norm = 0.5 if high <= low + 1e-9 else (value - low) / (high - low)
            row.setdefault("normalised_metrics", {})[metric] = round(_clamp(norm), 4)
    for row in rows:
        weighted = sum(_f(weights.get(metric)) * _f((row.get("normalised_metrics") or {}).get(metric)) for metric in metric_names)
        confidence = str(row.get("projection_confidence") or "UNKNOWN")
        conf_factor = _f(confidence_mult.get(confidence), _f(confidence_mult.get("UNKNOWN"), 0.88))
        evidence_factor = 0.85 + 0.15 * _f(row.get("evidence_coverage"))
        row["dss_score"] = round(100.0 * weighted * conf_factor * evidence_factor, 2)


def _admitted(row: dict[str, Any], blocked: bool) -> tuple[bool, list[str]]:
    cfg = load_policy().get("admission") or {}
    reasons = []
    if blocked:
        reasons.append("critical DSS framework failure")
    if str(row.get("status")) not in set(load_policy().get("allowed_statuses") or []):
        reasons.append("availability status outside watchlist policy")
    if _f((row.get("xmins") or {}).get("start_probability")) < _f(cfg.get("minimum_start_probability"), 0.45):
        reasons.append("starter probability below admission floor")
    if _f((row.get("xmins") or {}).get("dnp_probability")) > _f(cfg.get("maximum_dnp_probability"), 0.35):
        reasons.append("DNP risk above admission ceiling")
    if _f(row.get("evidence_coverage")) < _f(cfg.get("minimum_dimension_coverage"), 0.70):
        reasons.append("required evidence coverage insufficient")
    if _f(row.get("critical_dimension_score")) < _f(cfg.get("minimum_critical_dimension_score"), 0.60):
        reasons.append("critical evidence dimension insufficient")
    return not reasons, reasons


def _reasons(row: dict[str, Any]) -> tuple[list[str], list[str]]:
    labels = {
        "short_horizon": "proyeksi 3-GW kuat",
        "primary_horizon": "proyeksi 5-GW kuat",
        "strategic_horizon": "outlook 10–15 GW mendukung",
        "xmins_security": "starter security / xMins kuat",
        "role_security": "role-security proxy kuat",
        "underlying": "underlying profile kuat",
        "value": "value terhadap harga kuat",
        "squad_fit": "cocok dengan struktur/package legal",
        "market_overlay": "price pressure mendukung sebagai overlay",
    }
    contributions = []
    weights = load_policy().get("ranking_weights") or {}
    for metric, norm in (row.get("normalised_metrics") or {}).items():
        contributions.append((_f(norm) * _f(weights.get(metric)), metric))
    contributions.sort(reverse=True)
    why = [labels[metric] for _, metric in contributions[:3] if metric in labels]
    risks = []
    dims = row.get("dimensions") or {}
    if (dims.get("set_piece_penalty") or {}).get("status") == "MISSING":
        risks.append("evidence set-piece/penalty belum cukup")
    if (dims.get("role") or {}).get("status") == "PROXY" or (dims.get("competition") or {}).get("status") == "PROXY":
        risks.append("role/competition masih memakai proxy, bukan bukti taktis penuh")
    if str(row.get("projection_confidence")) == "LOW":
        risks.append("projection confidence LOW")
    if _f((row.get("xmins") or {}).get("dnp_probability")) >= 0.20:
        risks.append("DNP/rotation risk masih material")
    return why[:3], risks[:3]


def _previous_ranks(previous: dict[str, Any]) -> dict[int, tuple[str, int]]:
    out = {}
    for position, rows in (previous.get("positions") or {}).items():
        for idx, row in enumerate(rows, start=1):
            if row.get("element") is not None:
                out[int(row["element"])] = (str(position), idx)
    return out


def _lifecycle(element: int, position: str, rank: int, previous: dict[int, tuple[str, int]]) -> str:
    old = previous.get(element)
    if not old:
        return "NEW"
    old_position, old_rank = old
    if old_position != position:
        return "NEW"
    if rank < old_rank:
        return "UP"
    if rank > old_rank:
        return "DOWN"
    return "KEEP"


def build() -> dict[str, Any]:
    cfg = load_policy()
    projections = read_json(DATA / "projections.json", {})
    team = read_json(DATA / "team.json", {})
    package_optimizer = read_json(DATA / "package_optimizer.json", {})
    prices = read_json(DATA / "prices.json", {})
    price_alerts = read_json(DATA / "price_alerts.json", {})
    framework = read_json(DATA / "framework_health.json", {})
    previous = read_json(OUT, {})

    core_audit = _registry_audit(framework, "dss_core", load_core_registry())
    ext_audit = _registry_audit(framework, "dss_extensions", load_extension_registry())
    block = bool((cfg.get("admission") or {}).get("block_on_critical_dss_failure", True) and core_audit.get("critical_failed"))
    framework_core = {row["id"]: row["framework_status"] for row in core_audit.get("modules") or []}
    owned_ids, owned_by_position = _owned_context(team, projections)
    package_by_in = _package_map(package_optimizer)
    price_by_id = _price_map(prices, price_alerts)
    previous_rank = _previous_ranks(previous)
    allowed_positions = set(cfg.get("positions") or ["GK", "DEF", "MID", "FWD"])

    pools: dict[str, list[dict[str, Any]]] = {position: [] for position in allowed_positions}
    rejected: Counter[str] = Counter()
    universe_screened = 0
    for proj in projections.get("players") or []:
        position = str(proj.get("position") or "")
        if position not in allowed_positions:
            continue
        universe_screened += 1
        element = int(proj.get("element") or -1)
        if element in owned_ids:
            rejected["owned_excluded"] += 1
            continue
        row = _raw_candidate(
            proj,
            package_by_in.get(element),
            owned_by_position.get(position) or [],
            price_by_id.get(element) or {},
            framework_core,
        )
        admitted, reasons = _admitted(row, block)
        row["admitted"] = admitted
        row["rejection_reasons"] = reasons
        if admitted:
            pools[position].append(row)
        else:
            for reason in reasons:
                rejected[reason] += 1

    positions: dict[str, list[dict[str, Any]]] = {}
    max_per = int(cfg.get("max_per_position") or 5)
    for position in cfg.get("positions") or ["GK", "DEF", "MID", "FWD"]:
        rows = pools.get(position) or []
        _normalise(rows)
        rows.sort(key=lambda row: (row.get("dss_score", 0), _horizon(row, 5) if "horizons" in row else 0, -int(row.get("now_cost") or 0)), reverse=True)
        shortlisted = rows[:max_per]
        for rank, row in enumerate(shortlisted, start=1):
            row["rank"] = rank
            row["lifecycle"] = _lifecycle(int(row["element"]), position, rank, previous_rank)
            why, risks = _reasons(row)
            row["reasons"] = why
            row["risks"] = risks
            row["action"] = "WATCH"
            row.pop("raw_metrics", None)
            row.pop("normalised_metrics", None)
        positions[position] = shortlisted

    current_ids = {int(row["element"]) for rows in positions.values() for row in rows}
    removed = []
    for element, (position, old_rank) in previous_rank.items():
        if element not in current_ids:
            removed.append({"element": element, "position": position, "previous_rank": old_rank, "lifecycle": "REMOVE"})

    admitted_count = sum(len(rows) for rows in pools.values())
    shortlist_count = sum(len(rows) for rows in positions.values())
    if block:
        status = "BLOCKED"
    elif shortlist_count == 0:
        status = "INSUFFICIENT_EVIDENCE"
    else:
        status = "READY"
    confidence_cap = "MEDIUM" if core_audit.get("critical_partial") and (cfg.get("admission") or {}).get("cap_confidence_when_critical_dss_partial", True) else "HIGH"
    payload = {
        "generated_at": _now(),
        "model": cfg.get("model_id"),
        "screening_contract": cfg.get("screening_contract"),
        "status": status,
        "planning_gw": projections.get("planning_gw"),
        "positions": positions,
        "removed": removed,
        "screening_summary": {
            "projection_players": len(projections.get("players") or []),
            "universe_screened": universe_screened,
            "owned_excluded": len(owned_ids),
            "admitted_candidates": admitted_count,
            "published_candidates": shortlist_count,
            "max_per_position": max_per,
            "rejection_counts": dict(rejected),
            "confidence_cap": confidence_cap,
        },
        "screening_audit": {
            "dss_core": core_audit,
            "dss_extensions": ext_audit,
            "required_dimensions": list((cfg.get("dimension_weights") or {}).keys()),
            "full_registry_traversal": core_audit.get("traversed") == 50 and ext_audit.get("traversed") == 16,
            "critical_framework_failure_blocks_publication": block,
        },
        "governance": cfg.get("governance") or {},
    }
    return payload


def run() -> dict[str, Any]:
    payload = build()
    atomic_json(OUT, payload)
    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {})["dss_watchlist"] = "data/dss_watchlist.json"
    latest["dss_watchlist_summary"] = {
        "model": payload.get("model"),
        "screening_contract": payload.get("screening_contract"),
        "status": payload.get("status"),
        "published_candidates": (payload.get("screening_summary") or {}).get("published_candidates"),
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
        "positions": {position: len(rows) for position, rows in (result.get("positions") or {}).items()},
        "full_registry_traversal": (result.get("screening_audit") or {}).get("full_registry_traversal"),
    }, ensure_ascii=False))
