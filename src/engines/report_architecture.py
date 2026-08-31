from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from src.utils import DATA, ROOT, atomic_json, read_json

CONFIG_PATH = ROOT / "config" / "intelligence" / "reporting.json"
USER_OUT = DATA / "user_report.json"
TECH_OUT = DATA / "technical_appendix.json"
STATE_OUT = DATA / "report_state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _urgency_rank(value: str | None) -> int:
    return {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}.get(str(value or "").upper(), 0)


def _plain_price_confidence(alert: dict[str, Any]) -> str:
    health = str(alert.get("official_projection_health") or "")
    if health == "SUSPECT_STATIC_OFFSET0":
        return "proyeksi waktu perubahan harga belum cukup yakin"
    if alert.get("prediction_source") == "TRAJECTORY_RATE":
        return "arah tekanan harga jelas, waktu perubahan masih estimasi"
    return "sinyal harga tersedia"


def _projection_map(projections: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(p["element"]): p for p in projections.get("players") or [] if p.get("element") is not None}


def _owned_squad(team: dict[str, Any], projections: dict[str, Any], stable_mode: bool) -> dict[str, Any]:
    pmap = _projection_map(projections)
    rows = []
    relevant = []
    for owned in team.get("team_value_ledger") or []:
        element = int(owned.get("element") or -1)
        proj = pmap.get(element) or {}
        xmins = proj.get("xmins") or {}
        row = {
            "element": element,
            "name": owned.get("name") or proj.get("name"),
            "position": owned.get("position") or proj.get("position"),
            "price": round(_f(owned.get("now_cost")) / 10.0, 1),
            "status": owned.get("status") or proj.get("status"),
            "minutes_current_season": ((proj.get("current_season") or {}).get("minutes") if proj else None),
            "xmins": xmins.get("expected_minutes"),
            "start_probability": xmins.get("start_probability"),
            "model_confidence": proj.get("projection_confidence"),
        }
        rows.append(row)
        if row["status"] not in (None, "a") or str(row.get("model_confidence") or "").upper() == "LOW":
            relevant.append(row)
    return {
        "count": len(rows),
        "facts": rows if not stable_mode else relevant,
        "compact_summary": None if not stable_mode else {
            "unchanged_or_no_issue_count": max(0, len(rows) - len(relevant)),
            "players_needing_attention": len(relevant),
        },
        "decision": "HOLD" if not relevant else "REVIEW",
    }


def _state_payload(lineup: dict[str, Any], package: dict[str, Any], price_alerts: dict[str, Any], framework: dict[str, Any], prediction_quality: dict[str, Any]) -> dict[str, Any]:
    xi = sorted(int(x.get("element")) for x in lineup.get("starting_xi") or [])
    price_rows = sorted(
        (
            int(x.get("element") or -1),
            str(x.get("risk_direction") or ""),
            str(x.get("urgency") or ""),
            round(_f(x.get("official_progress_pct")), 1),
        )
        for x in price_alerts.get("alerts") or []
        if x.get("owned") and _urgency_rank(x.get("urgency")) >= 3
    )
    return {
        "squad": package.get("selected_package_id"),
        "starting_xi": xi,
        "formation": lineup.get("formation"),
        "captain": (lineup.get("captain") or {}).get("element"),
        "vice_captain": (lineup.get("vice_captain") or {}).get("element"),
        "chip": (lineup.get("chip_context") or {}).get("active_chip"),
        "price": price_rows,
        "critical_health": {
            "overall": framework.get("overall"),
            "critical_failed": sorted(framework.get("critical_failed") or []),
            "prediction_quality": prediction_quality.get("status"),
        },
    }


def _changes(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    previous_state = previous.get("state") or {}
    if not previous_state:
        return {"initial_report": True, "material_change": True, "changed": ["initial_baseline"]}
    changed = [key for key, value in current.items() if previous_state.get(key) != value]
    return {"initial_report": False, "material_change": bool(changed), "changed": changed}


def _preserved_state_extensions(previous: dict[str, Any]) -> dict[str, Any]:
    cfg = load_policy().get("state_persistence") or {}
    keys = list(cfg.get("preserve_across_rebuild") or [])
    if not keys or len(keys) != len(set(keys)) or any(not isinstance(key, str) or not key for key in keys):
        raise RuntimeError("report state persistence requires unique non-empty preserve_across_rebuild keys")
    if str(cfg.get("unknown_extension_policy") or "").upper() != "DROP":
        raise RuntimeError("report state persistence unknown_extension_policy must be DROP")
    if cfg.get("core_state_is_rebuilt_each_report") is not True:
        raise RuntimeError("report state persistence must rebuild core state each report")
    return {key: previous[key] for key in keys if key in previous}


def _lineup_section(lineup: dict[str, Any], changes: dict[str, Any], stable_mode: bool) -> dict[str, Any]:
    policy = load_policy().get("starting_xi") or {}
    battle = lineup.get("main_starting_xi_battle") or {}
    margin = _f(battle.get("margin"), 0.0)
    lock_margin = _f(policy.get("lock_margin"), 0.75)
    high_margin = _f(policy.get("high_confidence_margin"), 1.25)
    medium_margin = _f(policy.get("medium_confidence_margin"), 0.5)
    if margin >= high_margin:
        confidence = "HIGH"
    elif margin >= medium_margin:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    decision = "LOCK" if margin >= lock_margin and battle.get("status") == "CLEAR" else "OPEN"
    starter = (battle.get("starter_side") or [{}])[0]
    challenger = (battle.get("bench_side") or [{}])[0]
    full_xi = None
    publish_full = bool(changes.get("initial_report") or "starting_xi" in (changes.get("changed") or []))
    if publish_full and not stable_mode:
        full_xi = [{"element": x.get("element"), "name": x.get("name"), "position": x.get("position")} for x in lineup.get("starting_xi") or []]
    return {
        "facts": {"formation": lineup.get("formation"), "full_xi": full_xi},
        "model": {
            "battle": {
                "starter": starter.get("name"),
                "challenger": challenger.get("name"),
                "margin": battle.get("margin"),
                "alternative_formation": battle.get("alternative_formation"),
            },
            "confidence": confidence,
        },
        "decision": decision,
        "reason": "margin model cukup jelas" if decision == "LOCK" else "battle masih terlalu dekat untuk dikunci",
    }


def _captain_context(projections: dict[str, Any], element: int | None, planning_gw: int) -> dict[str, Any]:
    if element is None:
        return {}
    proj = _projection_map(projections).get(int(element)) or {}
    xmins = proj.get("xmins") or {}
    gw = next((x for x in proj.get("xpts_by_gw") or [] if int(x.get("gw") or -1) == planning_gw), {})
    mean = _f(gw.get("mean"))
    std = _f(gw.get("std"))
    historical = proj.get("historical_prior") or {}
    role_fields = {}
    for key in ("penalty_share", "penalty_role", "set_piece_share", "set_piece_role"):
        if proj.get(key) is not None:
            role_fields[key] = proj.get(key)
        elif historical.get(key) is not None:
            role_fields[key] = historical.get(key)
    return {
        "element": element,
        "name": proj.get("name"),
        "xpts_mean": round(mean, 3),
        "floor80": round(max(0.0, mean - 1.282 * std), 3),
        "ceiling80": round(mean + 1.282 * std, 3),
        "xpts_std": round(std, 3),
        "start_probability": xmins.get("start_probability"),
        "expected_minutes": xmins.get("expected_minutes"),
        "dnp_probability": xmins.get("dnp_probability"),
        "role_evidence": role_fields,
        "projection_confidence": proj.get("projection_confidence"),
        "fixture_count": len(gw.get("fixtures") or []),
    }


def _captaincy_section(lineup: dict[str, Any], projections: dict[str, Any]) -> dict[str, Any]:
    cfg = load_policy().get("captaincy") or {}
    planning_gw = int(lineup.get("planning_gw") or projections.get("planning_gw") or 1)
    cap = _captain_context(projections, (lineup.get("captain") or {}).get("element"), planning_gw)
    vice = _captain_context(projections, (lineup.get("vice_captain") or {}).get("element"), planning_gw)
    safe_pool = lineup.get("captain_safe_pool") or []
    margin = 0.0
    if len(safe_pool) >= 2:
        margin = _f(safe_pool[0].get("captain_score")) - _f(safe_pool[1].get("captain_score"))
    relative_vol = _f(cap.get("xpts_std")) / max(0.1, _f(cap.get("xpts_mean")))
    role_ok = bool(cap.get("role_evidence")) if cfg.get("require_role_evidence_for_lock") else True
    fixture_ok = int(cap.get("fixture_count") or 0) > 0 if cfg.get("require_positive_fixture_context") else True
    checks = {
        "start_probability": _f(cap.get("start_probability")) >= _f(cfg.get("minimum_start_probability_for_lock"), 0.85),
        "expected_minutes": _f(cap.get("expected_minutes")) >= _f(cfg.get("minimum_expected_minutes_for_lock"), 70),
        "dnp_risk": _f(cap.get("dnp_probability"), 1.0) <= _f(cfg.get("maximum_dnp_probability_for_lock"), 0.10),
        "volatility": relative_vol <= _f(cfg.get("maximum_relative_volatility_for_lock"), 0.70),
        "ranking_margin": margin >= _f(cfg.get("minimum_score_margin_for_lock"), 0.40),
        "role_evidence": role_ok,
        "fixture_context": fixture_ok,
    }
    passed = sum(bool(v) for v in checks.values())
    if all(checks.values()):
        decision, confidence = "LOCK", "HIGH"
    elif passed >= max(4, len(checks) - 2):
        decision, confidence = "LEAN", "MEDIUM"
    else:
        decision, confidence = "OPEN", "LOW"
    failed = [k for k, ok in checks.items() if not ok]
    return {
        "facts": {
            "model_candidate": cap.get("name"),
            "vice_candidate": vice.get("name"),
            "fixture_count": cap.get("fixture_count"),
        },
        "model": {
            "captain": cap,
            "vice": vice,
            "candidate_margin": round(margin, 4),
            "checks": checks,
        },
        "decision": decision,
        "confidence": confidence,
        "reason": "captaincy standard terpenuhi" if decision == "LOCK" else "kapten belum layak di-lock: " + ", ".join(failed),
    }


def _chip_section(lineup: dict[str, Any]) -> dict[str, Any]:
    chip = lineup.get("chip_context") or {}
    active = chip.get("active_chip")
    legal = chip.get("single_chip_rule_respected") is True
    return {
        "facts": {"active_chip": active, "used_this_gw": chip.get("used_this_gw") or []},
        "model": None,
        "decision": "HOLD" if legal else "REVIEW",
        "confidence": "HIGH" if legal else "LOW",
    }


def _price_section(price_alerts: dict[str, Any], team: dict[str, Any], watchlist: dict[str, Any]) -> dict[str, Any]:
    cfg = load_policy().get("price_radar") or {}
    allowed = set(cfg.get("allowed_urgencies") or ["HIGH", "CRITICAL"])
    owned_ids = {int(x.get("element") or -1) for x in team.get("team_value_ledger") or []}
    owned = []
    external = []
    watch_ids = {int(x.get("element") or -1) for rows in (watchlist.get("positions") or {}).values() for x in rows}
    full_dss = watchlist.get("screening_contract") == (load_policy().get("watchlist") or {}).get("required_contract")
    for alert in price_alerts.get("alerts") or []:
        urgency = str(alert.get("urgency") or "").upper()
        if urgency not in allowed:
            continue
        row = {
            "element": alert.get("element"),
            "name": alert.get("name"),
            "direction": alert.get("risk_direction"),
            "urgency": urgency,
            "progress_pct": alert.get("official_progress_pct"),
            "estimated_change_time": alert.get("predicted_change_deadline"),
            "confidence_note": _plain_price_confidence(alert),
        }
        if int(alert.get("element") or -1) in owned_ids:
            row["action"] = "HOLD" if alert.get("risk_direction") == "RISE" else "REVIEW"
            owned.append(row)
        elif full_dss and int(alert.get("element") or -1) in watch_ids:
            row["action"] = "WATCH"
            external.append(row)
    return {
        "owned": owned,
        "external_watchlist": external,
        "external_status": "READY" if full_dss else "INSUFFICIENT_EVIDENCE",
        "decision": "REVIEW" if any(x.get("action") == "REVIEW" for x in owned) else "HOLD",
    }


def _watchlist_section(watchlist: dict[str, Any]) -> dict[str, Any]:
    cfg = load_policy().get("watchlist") or {}
    required_contract = cfg.get("required_contract")
    positions = cfg.get("positions") or ["GK", "DEF", "MID", "FWD"]
    if watchlist.get("screening_contract") != required_contract:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "decision": "OPEN",
            "reason": "belum cukup evidence untuk menerbitkan ranking external berbasis DSS penuh",
            "positions": {p: [] for p in positions},
        }
    out = {}
    for position in positions:
        rows = list((watchlist.get("positions") or {}).get(position) or [])[: int(cfg.get("max_per_position") or 5)]
        out[position] = rows
    return {"status": "READY", "decision": "WATCH", "positions": out}


def _engine_line(framework: dict[str, Any], latest: dict[str, Any]) -> dict[str, Any]:
    overall = str(framework.get("overall") or "UNKNOWN")
    critical = list(framework.get("critical_failed") or [])
    freshness = (framework.get("data_freshness") or {}).get("status")
    fresh_text = "data fresh" if freshness == "PASS" else "freshness perlu dipantau"
    if critical:
        text = f"Engine: {overall}, {fresh_text}, ada critical failure yang bisa memengaruhi keputusan."
    else:
        text = f"Engine: {overall}, {fresh_text}, tidak ada critical failure."
    return {"text": text, "critical": bool(critical), "generated_at": latest.get("generated_at")}


def _action_board(user: dict[str, Any]) -> list[dict[str, Any]]:
    max_items = int((load_policy().get("action_board") or {}).get("max_items") or 8)
    items: list[dict[str, Any]] = []
    decision = user.get("decision") or {}
    items.append({"action": decision.get("squad"), "subject": "Squad", "trigger": "ubah hanya jika ada evidence baru yang material"})
    lineup = user.get("starting_xi") or {}
    battle = ((lineup.get("model") or {}).get("battle") or {})
    if battle.get("starter") or battle.get("challenger"):
        items.append({"action": lineup.get("decision"), "subject": f"{battle.get('starter')} vs {battle.get('challenger')}", "trigger": "press conference, role, xMins, atau margin model berubah"})
    cap = user.get("captaincy") or {}
    items.append({"action": cap.get("decision"), "subject": f"Captain: {(cap.get('facts') or {}).get('model_candidate')}", "trigger": cap.get("reason")})
    chip = user.get("chip") or {}
    items.append({"action": chip.get("decision"), "subject": "Chip", "trigger": "ubah hanya jika konteks chip atau legality berubah"})
    for row in (user.get("price_radar") or {}).get("owned") or []:
        if len(items) >= max_items:
            break
        items.append({"action": row.get("action"), "subject": f"Price: {row.get('name')}", "trigger": f"{row.get('direction')} {row.get('urgency')}"})
    watch = user.get("external_watchlist") or {}
    if len(items) < max_items and watch.get("status") != "READY":
        items.append({"action": "OPEN", "subject": "External watchlist", "trigger": "publish ranking hanya setelah full DSS evidence tersedia"})
    return items[:max_items]


def build() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    latest = read_json(DATA / "latest.json", {})
    team = read_json(DATA / "team.json", {})
    lineup = read_json(DATA / "lineup_decision.json", {})
    package = read_json(DATA / "package_decision.json", {})
    projections = read_json(DATA / "projections.json", {})
    price_alerts = read_json(DATA / "price_alerts.json", {})
    prediction_quality = read_json(DATA / "prediction_quality.json", {})
    framework = read_json(DATA / "framework_health.json", {})
    runtime = read_json(DATA / "runtime_performance.json", {})
    challenger = read_json(DATA / "challenger_scorecard.json", {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    previous = read_json(STATE_OUT, {})

    current_state = _state_payload(lineup, package, price_alerts, framework, prediction_quality)
    delta = _changes(current_state, previous)
    stable_mode = bool((load_policy().get("stable_report") or {}).get("enabled")) and not delta.get("material_change")

    package_id = str(package.get("selected_package_id") or "HOLD")
    squad_decision = "HOLD" if package_id == "HOLD" else "CHANGE"
    lineup_section = _lineup_section(lineup, delta, stable_mode)
    captaincy = _captaincy_section(lineup, projections)
    chip = _chip_section(lineup)
    prices = _price_section(price_alerts, team, watchlist)
    watch = _watchlist_section(watchlist)
    engine_line = _engine_line(framework, latest)

    overall = squad_decision
    if engine_line["critical"] or prediction_quality.get("status") not in (None, "HEALTHY"):
        overall = "REVIEW"
    elif lineup_section.get("decision") == "OPEN" or captaincy.get("decision") == "OPEN":
        overall = "REVIEW"
    elif squad_decision == "CHANGE":
        overall = "CHANGE"

    user = {
        "decision": {
            "overall": overall,
            "squad": squad_decision,
            "starting_xi": lineup_section.get("decision"),
            "captaincy": captaincy.get("decision"),
            "chip": chip.get("decision"),
            "price": prices.get("decision"),
            "confidence": "HIGH" if overall == "HOLD" and captaincy.get("decision") == "LOCK" and lineup_section.get("decision") == "LOCK" else "MEDIUM" if overall != "REVIEW" else "LOW",
        },
        "owned_squad": _owned_squad(team, projections, stable_mode),
        "changes_since_last_report": delta,
        "starting_xi": lineup_section,
        "captaincy": captaincy,
        "chip": chip,
        "price_radar": prices,
        "external_watchlist": watch,
        "engine_line": engine_line,
        "action_board": [],
        "report_mode": "COMPACT_STABLE" if stable_mode else "FULL_OR_DELTA",
        "generated_at": _now(),
        "planning_gw": projections.get("planning_gw") or lineup.get("planning_gw"),
        "horizon_policy": {"primary": [3, 5], "strategic": [10, 15]},
    }
    user["action_board"] = _action_board(user)

    forbidden = (load_policy().get("language") or {}).get("forbidden_user_report_tokens") or []
    serialized = json.dumps(user, ensure_ascii=False)
    leaked = [token for token in forbidden if token in serialized]
    if leaked:
        raise RuntimeError(f"technical term leaked into USER_REPORT: {leaked}")

    tech = {
        "generated_at": _now(),
        "report_model": load_policy().get("model_id"),
        "snapshot": {
            "snapshot_id": latest.get("snapshot_id"),
            "engine_version": latest.get("engine_version"),
            "schema_version": latest.get("schema_version"),
            "ruleset": latest.get("ruleset"),
        },
        "framework_health": {
            "overall": framework.get("overall"),
            "decision_engine": framework.get("decision_engine"),
            "go_allowed": framework.get("go_allowed"),
            "critical_failed": framework.get("critical_failed"),
            "critical_partial": framework.get("critical_partial"),
            "gate0": framework.get("gate0"),
            "dss_core": framework.get("dss_core"),
            "dss_extensions": framework.get("dss_extensions"),
            "enhancements": framework.get("enhancements"),
            "prediction_quality": framework.get("prediction_quality"),
        },
        "runtime": runtime,
        "raw_decision_refs": {
            "lineup": "data/lineup_decision.json",
            "package": "data/package_decision.json",
            "projections": "data/projections.json",
            "price_alerts": "data/price_alerts.json",
            "challenger": "data/challenger_scorecard.json",
        },
        "challenger_scorecard": challenger,
        "audit": {
            "facts_models_decisions_separated": True,
            "raw_model_ranking_not_final_recommendation": True,
            "technical_terms_confined_to_appendix": True,
            "full_dss_watchlist_required_before_external_ranking": True,
            "single_gw_overreaction_guard": {"primary_horizon_gws": [3, 5], "strategic_horizon_gws": [10, 15]},
            "current_state_fingerprint": _fingerprint(current_state),
            "previous_state_fingerprint": previous.get("fingerprint"),
        },
    }
    state = {
        **_preserved_state_extensions(previous),
        "generated_at": _now(),
        "fingerprint": _fingerprint(current_state),
        "state": current_state,
        "last_report_mode": user.get("report_mode"),
        "last_decision": user.get("decision"),
    }
    return user, tech, state


def run() -> dict[str, Any]:
    user, tech, state = build()
    atomic_json(USER_OUT, user)
    atomic_json(TECH_OUT, tech)
    atomic_json(STATE_OUT, state)
    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {}).update({
        "user_report": "data/user_report.json",
        "technical_appendix": "data/technical_appendix.json",
        "report_state": "data/report_state.json",
    })
    latest["report_summary"] = {
        "model": load_policy().get("model_id"),
        "overall": (user.get("decision") or {}).get("overall"),
        "report_mode": user.get("report_mode"),
        "material_change": (user.get("changes_since_last_report") or {}).get("material_change"),
        "captaincy": (user.get("captaincy") or {}).get("decision"),
        "starting_xi": (user.get("starting_xi") or {}).get("decision"),
        "external_watchlist": (user.get("external_watchlist") or {}).get("status"),
    }
    atomic_json(DATA / "latest.json", latest)
    return {"user_report": user, "technical_appendix": tech, "report_state": state}


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "decision": out["user_report"].get("decision"),
        "report_mode": out["user_report"].get("report_mode"),
        "material_change": (out["user_report"].get("changes_since_last_report") or {}).get("material_change"),
        "actions": len(out["user_report"].get("action_board") or []),
    }, ensure_ascii=False))