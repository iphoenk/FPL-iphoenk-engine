from __future__ import annotations

from collections import Counter
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.decision.decision_trace import build_trace
from src.v5.decision.dss_evaluator import evaluate_dss
from src.v5.decision.lineup_optimizer import optimize_lineup
from src.v5.decision.package_governance import govern_packages
from src.v5.decision.package_optimizer import build_packages

CONFIG = "config/v5_decision_registry.json"
PACKAGE_CONFIG = "config/intelligence/package_optimizer.json"
DSS_POLICY = "config/v5_dss_policy_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    if not isinstance(data.get("capabilities"), list) or not isinstance(data.get("capability_activation"), dict):
        raise RuntimeError("invalid V5 decision registry capabilities")
    return data


def _package_cfg() -> dict[str, Any]:
    data = load_json_config(PACKAGE_CONFIG)
    if not isinstance(data.get("early_season_change_cap"), dict) or not isinstance(data.get("team_cluster_penalty"), dict):
        raise RuntimeError("package optimizer guardrail config is incomplete")
    return data


def _dss_policy() -> dict[str, Any]:
    data = load_json_config(DSS_POLICY)
    if not isinstance(data.get("registries"), dict) or not isinstance(data.get("governance"), dict):
        raise RuntimeError("invalid V5 DSS policy registry")
    return data


def _inputs(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    price = payload.get("price") if isinstance(payload.get("price"), dict) else {}
    rules = truth.get("rules") if isinstance(truth.get("rules"), dict) else {}
    team = truth.get("team") if isinstance(truth.get("team"), dict) else {}
    if not rules or not team or not prediction:
        raise ValueError("decision service requires truth rules/team and prediction payload")
    return truth, prediction, price, rules, team


def _effective_change_cap(planning_gw: int) -> tuple[int, dict[str, Any]]:
    cfg = _package_cfg()
    base = max(0, int(cfg.get("max_changes") or 0))
    guard = cfg["early_season_change_cap"]
    enabled = bool(guard.get("enabled"))
    through_gw = max(0, int(guard.get("through_gw") or 0))
    early_cap = max(0, int(guard.get("max_changes") if guard.get("max_changes") is not None else base))
    effective = min(base, early_cap) if enabled and int(planning_gw) <= through_gw else base
    return effective, {
        "early_season_change_cap_enabled": enabled,
        "early_season_through_gw": through_gw,
        "configured_max_changes": base,
        "effective_max_changes": effective,
    }


def _apply_package_guardrails(
    packages: dict[str, Any],
    prediction: dict[str, Any],
    team: dict[str, Any],
    planning_gw: int,
) -> dict[str, Any]:
    if packages.get("status") != "READY":
        return packages

    cfg = _package_cfg()
    effective_cap, early_guard = _effective_change_cap(planning_gw)
    cluster = cfg["team_cluster_penalty"]
    cluster_enabled = bool(cluster.get("enabled"))
    free_players = max(0, int(cluster.get("free_players_per_club") or 0))
    points_per_extra = max(0.0, float(cluster.get("points_per_extra_player") or 0.0))

    pmap = {
        int(player["element"]): int(player["team_id"])
        for player in prediction.get("players") or []
        if isinstance(player, dict) and player.get("element") is not None and player.get("team_id") is not None
    }
    baseline = {
        int(row["element"]): int(row["team_id"])
        for row in team.get("squad") or []
        if isinstance(row, dict) and row.get("element") is not None and row.get("team_id") is not None
    }

    rows: list[dict[str, Any]] = []
    rejected_over_cap = 0
    for raw in packages.get("packages") or []:
        if not isinstance(raw, dict):
            continue
        changes = int(raw.get("changes") or 0)
        if changes > effective_cap:
            rejected_over_cap += 1
            continue

        row = {**raw}
        score = dict(row.get("score") or {})
        squad = dict(baseline)
        for outgoing in row.get("outs") or []:
            if isinstance(outgoing, dict) and outgoing.get("element") is not None:
                squad.pop(int(outgoing["element"]), None)
        for incoming in row.get("ins") or []:
            if isinstance(incoming, dict) and incoming.get("element") is not None:
                element = int(incoming["element"])
                team_id = pmap.get(element)
                if team_id is not None:
                    squad[element] = team_id

        counts = Counter(squad.values())
        excess = sum(max(0, count - free_players) for count in counts.values()) if cluster_enabled else 0
        penalty = round(excess * points_per_extra, 3) if cluster_enabled else 0.0
        raw_robust = score.get("robust_score")
        if raw_robust is not None:
            score["raw_robust_score"] = raw_robust
            score["team_cluster_penalty_points"] = penalty
            score["robust_score"] = round(float(raw_robust) - penalty, 3)
        score["guardrails"] = {
            **early_guard,
            "team_cluster_penalty_enabled": cluster_enabled,
            "free_players_per_club": free_players,
            "points_per_extra_player": points_per_extra,
            "cluster_excess_players": excess,
            "cluster_penalty_points": penalty,
        }
        row["score"] = score
        row["team_cluster"] = {
            "club_counts": dict(sorted(counts.items())),
            "excess_players": excess,
            "penalty": penalty,
        }
        rows.append(row)

    rows.sort(key=lambda row: float(((row.get("score") or {}).get("robust_score") or -1e9)), reverse=True)
    out = {
        **packages,
        "packages": rows,
        "package_count": len(rows),
        "early_season_change_cap_applied": True,
        "team_cluster_penalty_applied": cluster_enabled,
        "guardrails": {
            **early_guard,
            "over_cap_packages_rejected": rejected_over_cap,
            "team_cluster_penalty_enabled": cluster_enabled,
            "free_players_per_club": free_players,
            "points_per_extra_player": points_per_extra,
        },
    }
    hold = next((row for row in rows if row.get("id") == "HOLD"), None)
    if hold is not None:
        out["hold"] = hold
    return out


def _active_local_capabilities(
    packages: dict[str, Any],
    package_governance: dict[str, Any],
    lineup: dict[str, Any],
) -> list[str]:
    cfg = _cfg()
    configured = {str(value) for value in cfg["capabilities"]}
    activation = cfg["capability_activation"]
    active: set[str] = set()
    if packages.get("status") == "READY" and bool(packages.get("local_legality_prevalidated")) and package_governance.get("status") == "READY":
        active.update(configured & {str(value) for value in activation.get("package_ready") or []})
        if not bool(packages.get("team_cluster_penalty_applied")):
            active.discard("team_cluster_penalty")
        if not bool(packages.get("early_season_change_cap_applied")):
            active.discard("early_season_change_cap")
        perf_ready = all(
            isinstance((row.get("score") or {}).get("performance"), dict)
            for row in packages.get("packages") or []
            if isinstance(row, dict) and (row.get("score") or {}).get("valid")
        )
        if not perf_ready:
            active.discard("runtime_observability")
    if lineup.get("status") == "READY":
        active.update(configured & {str(value) for value in activation.get("lineup_ready") or []})
    return sorted(active)


def _prepare(payload: dict[str, Any]) -> dict[str, Any]:
    truth, prediction, price, rules, team = _inputs(payload)
    planning_gw = int(prediction.get("planning_gw") or 1)
    packages = _apply_package_guardrails(build_packages(prediction, team, rules), prediction, team, planning_gw)
    package_governance = govern_packages(packages, truth)
    lineup = optimize_lineup(team, prediction, rules)
    capabilities = _active_local_capabilities(packages, package_governance, lineup)
    ready = packages.get("status") == "READY" and package_governance.get("status") == "READY" and lineup.get("status") == "READY"
    return {
        "status": "READY" if ready else "BLOCKED",
        "model": _cfg().get("model_id"),
        "ruleset_id": rules.get("ruleset_id"),
        "packages": packages,
        "package_governance": package_governance,
        "lineup": lineup,
        "capabilities": capabilities,
        "price_context": {"alert_count": len(((price.get("alerts") or {}).get("alerts") or []))},
    }


def _blocked_trace(reason: str, gate0_preflight: dict[str, Any]) -> dict[str, Any]:
    items = gate0_preflight.get("items") if isinstance(gate0_preflight.get("items"), list) else []
    return {
        "decision_type": "BLOCKED",
        "action": reason,
        "confidence": "LOW",
        "evidence": [
            {
                "source": "governance-service",
                "field": "gate0_preflight",
                "authority": "governance-service",
                "freshness": None,
                "provenance": {"model": gate0_preflight.get("model"), "pass": gate0_preflight.get("pass")},
            }
        ] if gate0_preflight else [],
        "constraints_checked": [str(item.get("id")) for item in items if item.get("id")],
        "production_recommendation": None,
    }


def _dss_full_active(dss: dict[str, Any]) -> bool:
    policy = _dss_policy()
    strict = bool((policy.get("governance") or {}).get("all_modules_active_for_unqualified_go", True))
    if not strict:
        return True
    for section in ("core", "extensions"):
        block = dss.get(section) if isinstance(dss.get(section), dict) else {}
        expected = int(block.get("expected") or 0)
        active = int((block.get("counts") or {}).get("ACTIVE") or 0)
        if expected <= 0 or active != expected or not bool(block.get("integrity_ok")):
            return False
    return True


def _finalize(payload: dict[str, Any], prepared: dict[str, Any] | None = None) -> dict[str, Any]:
    truth, prediction, price, rules, _ = _inputs(payload)
    prepared = prepared if isinstance(prepared, dict) else _prepare(payload)
    packages = prepared.get("packages") if isinstance(prepared.get("packages"), dict) else {}
    package_governance = prepared.get("package_governance") if isinstance(prepared.get("package_governance"), dict) else {}
    lineup = prepared.get("lineup") if isinstance(prepared.get("lineup"), dict) else {}
    local_capabilities = prepared.get("capabilities") if isinstance(prepared.get("capabilities"), list) else []
    evaluation = payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else {}
    evaluation_capabilities = evaluation.get("capabilities") if isinstance(evaluation.get("capabilities"), list) else []
    gate0_preflight = payload.get("gate0_preflight") if isinstance(payload.get("gate0_preflight"), dict) else {}
    dss = evaluate_dss(
        truth,
        price,
        prediction,
        local_capabilities=local_capabilities,
        external_capability_sources={"evaluation": evaluation_capabilities},
    )
    local_ready = packages.get("status") == "READY" and package_governance.get("status") == "READY" and lineup.get("status") == "READY"
    preflight_ready = bool(gate0_preflight.get("pass"))
    dss_full_active = _dss_full_active(dss)
    decision_ready = bool(local_ready and preflight_ready)

    if local_ready:
        trace = build_trace(
            truth=truth,
            prediction=prediction,
            price=price,
            packages=packages,
            package_governance=package_governance,
            lineup=lineup,
            dss=dss,
            gate0_preflight=gate0_preflight,
        )
    else:
        trace = _blocked_trace(
            "BLOCK decision output until package, package-governance and lineup authorities are READY",
            gate0_preflight,
        )

    return {
        "status": "READY" if decision_ready else "BLOCKED",
        "model": _cfg().get("model_id"),
        "package_model": packages.get("model"),
        "package_governance_model": package_governance.get("model"),
        "ruleset_id": rules.get("ruleset_id"),
        "gate0_preflight_pass": preflight_ready,
        "strict_postflight_dss_active": dss_full_active,
        "local_legality_prevalidated": bool(packages.get("local_legality_prevalidated", False)),
        "package_count": packages.get("package_count", 0),
        "hold": packages.get("hold"),
        "packages": packages.get("packages", []),
        "candidate_pool": packages.get("candidate_pool", {}),
        "package_governance": package_governance,
        "selected_package": package_governance.get("selected_package"),
        "selected_package_id": package_governance.get("selected_package_id"),
        "optimizer_best_candidate": package_governance.get("optimizer_best_candidate"),
        "optimizer_best_challenger": package_governance.get("optimizer_best_challenger"),
        "lineup": lineup,
        "dss": dss,
        "decision_trace": trace,
        "capabilities": local_capabilities,
        "price_context": prepared.get("price_context", {}),
        "governance": {
            **(packages.get("governance") or {}),
            **(package_governance.get("governance") or {}),
            "manual_authority_override": bool(package_governance.get("manual_authority_override")),
            "lineup_authority": lineup.get("authority"),
            "dss_evaluation_model": dss.get("evaluation_model"),
            "evaluation_capabilities_consumed": sorted(str(value) for value in evaluation_capabilities),
            "gate0_preflight_model": gate0_preflight.get("model"),
            "strict_postflight_requires_all_dss_active": bool((_dss_policy().get("governance") or {}).get("all_modules_active_for_unqualified_go", True)),
            "strict_postflight_dss_active": dss_full_active,
            "decision_trace_required": True,
            "production_recommendation_enabled": bool((_cfg().get("trace") or {}).get("production_recommendation_enabled", False)),
        },
        "production_recommendation": None,
    }


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE",
            "bridge_only": False,
            "production_recommendation": False,
            "model": _cfg().get("model_id"),
            "capabilities": list(_cfg().get("capabilities") or []),
            "operations": ["prepare", "finalize", "build"],
        }
    if operation == "prepare":
        return _prepare(payload)
    if operation == "finalize":
        return _finalize(payload, payload.get("prepared") if isinstance(payload.get("prepared"), dict) else None)
    if operation == "build":
        return _finalize(payload, _prepare(payload))
    raise KeyError(f"unsupported decision operation: {operation}")
