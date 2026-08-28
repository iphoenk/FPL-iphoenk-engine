from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.report_checkpoint import resolve_report_checkpoint

CONFIG = "config/v5_reporting_registry.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _starters(lineup: dict[str, Any]) -> list[dict[str, Any]]:
    native = lineup.get("starters")
    if isinstance(native, list):
        return [row for row in native if isinstance(row, dict)]
    legacy = lineup.get("starting_xi")
    return [row for row in legacy or [] if isinstance(row, dict)]


def _owned_count(truth: dict[str, Any]) -> int:
    team = truth.get("team") if isinstance(truth.get("team"), dict) else {}
    squad = team.get("squad")
    if isinstance(squad, list):
        return len(squad)
    owned_ids = team.get("owned_ids")
    if isinstance(owned_ids, list):
        return len(owned_ids)
    return 0


def _price_alerts(price: dict[str, Any]) -> list[dict[str, Any]]:
    alerts = price.get("alerts")
    rows = alerts.get("alerts") if isinstance(alerts, dict) else alerts
    return [row for row in rows or [] if isinstance(row, dict)]


def _allowed_price_urgencies() -> set[str]:
    cfg = load_json_config(CONFIG).get("price_radar") or {}
    return {str(value).upper() for value in cfg.get("allowed_urgencies") or []}


def _state(decision: dict[str, Any], price: dict[str, Any], governance: dict[str, Any]) -> dict[str, Any]:
    lineup = decision.get("lineup") or {}
    xi = sorted(int(x.get("element")) for x in _starters(lineup) if x.get("element") is not None)
    allowed = _allowed_price_urgencies()
    price_state = sorted(
        (int(x.get("element") or -1), str(x.get("risk_direction") or ""), str(x.get("urgency") or ""))
        for x in _price_alerts(price)
        if x.get("owned") and str(x.get("urgency") or "").upper() in allowed
    )
    return {
        "squad": decision.get("selected_package_id"),
        "starting_xi": xi,
        "formation": lineup.get("formation"),
        "captain": (lineup.get("captain") or {}).get("element"),
        "vice_captain": (lineup.get("vice_captain") or {}).get("element"),
        "chip": (lineup.get("chip_context") or {}).get("active_chip"),
        "price": price_state,
        "critical_health": {"overall": governance.get("overall"), "go_allowed": governance.get("go_allowed")},
    }


def _changes(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    old = previous.get("state") if isinstance(previous.get("state"), dict) else {}
    if not old:
        return {"initial_report": True, "material_change": True, "changed": ["initial_baseline"]}
    changed = [key for key, value in current.items() if old.get(key) != value]
    return {"initial_report": False, "material_change": bool(changed), "changed": changed}


def _captaincy(lineup: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG).get("captaincy") or {}
    safe = lineup.get("captain_safe_pool") or []
    captain = lineup.get("captain") or {}
    vice = lineup.get("vice_captain") or {}
    if not captain:
        return {"decision": "OPEN", "confidence": "LOW", "reason": "captain candidate unavailable"}
    first_score = _f(safe[0].get("captain_score"), _f(safe[0].get("score"))) if safe else 0.0
    second_score = _f(safe[1].get("captain_score"), _f(safe[1].get("score"))) if len(safe) > 1 else first_score
    margin = first_score - second_score if len(safe) > 1 else 0.0
    start_p = _f(captain.get("start_probability"), _f(captain.get("xmins_start_probability")))
    mins = _f(captain.get("expected_minutes"), _f(captain.get("xmins")))
    dnp = _f(captain.get("dnp_probability"), max(0.0, 1.0 - start_p))
    checks = {
        "start_probability": start_p >= _f(cfg.get("minimum_start_probability_for_lock")),
        "expected_minutes": mins >= _f(cfg.get("minimum_expected_minutes_for_lock")),
        "dnp_risk": dnp <= _f(cfg.get("maximum_dnp_probability_for_lock")),
        "ranking_margin": margin >= _f(cfg.get("minimum_score_margin_for_lock")),
    }
    passed = sum(bool(x) for x in checks.values())
    decision = "LOCK" if all(checks.values()) else ("LEAN" if passed >= 3 else "OPEN")
    return {
        "decision": decision,
        "confidence": "HIGH" if decision == "LOCK" else ("MEDIUM" if decision == "LEAN" else "LOW"),
        "captain": captain,
        "vice_captain": vice,
        "candidate_margin": round(margin, 4),
        "checks": checks,
        "effective_authority": lineup.get("authority"),
    }


def _lineup(lineup: dict[str, Any], compact: bool) -> dict[str, Any]:
    cfg = load_json_config(CONFIG).get("starting_xi") or {}
    battle = lineup.get("main_starting_xi_battle") or {}
    margin = _f(battle.get("margin"))
    decision = "LOCK" if battle.get("status") == "CLEAR" and margin >= _f(cfg.get("lock_margin")) else "OPEN"
    return {
        "decision": decision,
        "formation": lineup.get("formation"),
        "battle": battle,
        "starting_xi": [] if compact else _starters(lineup),
        "bench": [] if compact else lineup.get("bench") or [],
        "effective_authority": lineup.get("authority"),
        "user_override": lineup.get("user_override") or {},
    }


def _price(price: dict[str, Any], watchlist: dict[str, Any]) -> dict[str, Any]:
    allowed = _allowed_price_urgencies()
    rows = [x for x in _price_alerts(price) if str(x.get("urgency") or "").upper() in allowed]
    external_ready = watchlist.get("status") == "READY"
    return {
        "owned": [x for x in rows if x.get("owned")],
        "external": [x for x in rows if not x.get("owned")] if external_ready else [],
        "external_status": "READY" if external_ready else "INSUFFICIENT_EVIDENCE",
    }


def _natural_presentation(
    *,
    decision_state: str,
    lineup: dict[str, Any],
    captaincy: dict[str, Any],
    price_section: dict[str, Any],
    checkpoint: dict[str, Any],
    truth: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    squad_text = {
        "HOLD": "Belum ada alasan kuat untuk mengubah komposisi skuad saat ini.",
        "CHANGE": "Ada perubahan skuad yang layak dipertimbangkan berdasarkan evidence terbaru.",
        "REVIEW": "Komposisi skuad masih perlu ditinjau sebelum keputusan final.",
    }.get(decision_state, "Status komposisi skuad sedang diperbarui.")

    formation = lineup.get("formation")
    lineup_authority = str(lineup.get("authority") or "")
    user_override = bool((decision.get("user_lineup_authority") or {}).get("active"))
    if user_override:
        xi_text = f"Pilihan XI pengguna menjadi baseline efektif untuk GW ini{f' dengan formasi {formation}' if formation else ''}. Engine tetap menyimpan rekomendasinya sebagai pembanding dan tidak menimpa pilihan pengguna."
    else:
        battle = lineup.get("main_starting_xi_battle") or {}
        if formation and battle.get("status") == "CLEAR":
            xi_text = f"Formasi {formation} saat ini menjadi susunan XI yang paling kuat menurut engine."
        elif formation:
            xi_text = f"Formasi {formation} menjadi baseline saat ini, tetapi battle starter-bench masih perlu dipantau."
        else:
            xi_text = "Susunan XI masih diperbarui."

    captain = lineup.get("captain") or {}
    vice = lineup.get("vice_captain") or {}
    captain_name = captain.get("name") or "kandidat utama"
    vice_name = vice.get("name")
    if user_override:
        captain_text = f"Kapten efektif adalah {captain_name} sesuai keputusan pengguna."
    elif captaincy.get("decision") == "LOCK":
        captain_text = f"{captain_name} saat ini menjadi pilihan kapten yang paling kuat."
    elif captaincy.get("decision") == "LEAN":
        captain_text = f"Pilihan kapten saat ini lebih condong ke {captain_name}, tetapi belum final."
    else:
        captain_text = f"{captain_name} memimpin kandidat kapten, tetapi evidence belum cukup untuk mengunci pilihan."
    if vice_name:
        captain_text += f" Wakil kapten saat ini {vice_name}."

    chip = str((lineup.get("chip_context") or {}).get("active_chip") or "").lower()
    chip_text = {
        "wildcard": "Wildcard aktif untuk GW target ini; chip tidak menambah poin langsung dan tidak boleh terbawa otomatis ke GW berikutnya.",
        "free_hit": "Free Hit aktif hanya untuk GW target ini dan komposisi akan kembali setelah Gameweek selesai.",
        "bench_boost": "Bench Boost aktif, sehingga kontribusi bench ikut dihitung.",
        "triple_captain": "Triple Captain aktif, sehingga multiplier kapten menjadi fokus utama.",
    }.get(chip, "Tidak ada chip aktif yang membutuhkan tindakan khusus saat ini.")

    owned_price = price_section.get("owned") or []
    price_text = (
        f"Ada {len(owned_price)} pemain milik sendiri dengan tekanan harga HIGH/CRITICAL yang perlu diperiksa."
        if owned_price
        else "Belum ada tekanan harga HIGH/CRITICAL pada pemain milik sendiri."
    )
    missed = checkpoint.get("missed_due") or []
    checkpoint_text = (
        f"Ada {len(missed)} checkpoint terjadwal yang terlewat dan harus ditinjau."
        if missed
        else "Checkpoint report yang sudah jatuh tempo tercatat lengkap."
    )
    baseline = ((truth.get("team") or {}).get("projection_baseline") or {})
    baseline_text = None
    if baseline.get("override_applied"):
        baseline_text = f"Komposisi planning memakai user lock khusus GW{baseline.get('planning_gw')}; lock ini tidak berlaku otomatis untuk GW berikutnya."
    elif baseline.get("stale_override_rejected"):
        baseline_text = "User lock dari GW sebelumnya sudah dianggap stale dan tidak lagi menjadi authority."

    return {
        "schema": "v5_user_report_presentation_v1",
        "language": "id-ID",
        "primary_human_surface": True,
        "headline": squad_text,
        "starting_xi": xi_text,
        "captaincy": captain_text,
        "chip": chip_text,
        "price": price_text,
        "planning_baseline": baseline_text,
        "checkpoint": checkpoint_text,
        "effective_lineup_authority": lineup_authority,
        "raw_machine_states_available_for_audit": True,
    }


def build_report(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    price = payload.get("price") if isinstance(payload.get("price"), dict) else {}
    governance = payload.get("governance") if isinstance(payload.get("governance"), dict) else {}
    previous = payload.get("previous_report_state") if isinstance(payload.get("previous_report_state"), dict) else {}
    report_request = payload.get("report_request") if isinstance(payload.get("report_request"), dict) else {}
    if not decision or not truth:
        raise ValueError("reporting requires decision and truth payloads")

    checkpoint, checkpoint_state = resolve_report_checkpoint(
        datetime.now(timezone.utc),
        previous,
        cfg.get("scheduled_report_checkpoints") if isinstance(cfg.get("scheduled_report_checkpoints"), dict) else {},
    )
    current = _state(decision, price, governance)
    changes = _changes(current, previous)
    force_full = bool(payload.get("force_full_report", False))
    compact = bool(
        not force_full
        and (cfg.get("stable_report") or {}).get("compact_when_no_material_change", True)
        and not changes["material_change"]
    )
    lineup = decision.get("lineup") or {}
    supplied_watchlist = payload.get("watchlist")
    watchlist = supplied_watchlist if isinstance(supplied_watchlist, dict) else decision.get("watchlist")
    if not isinstance(watchlist, dict):
        watchlist = {"status": "INSUFFICIENT_EVIDENCE", "positions": {}}
    selected = decision.get("selected_package") or {}
    trace = decision.get("decision_trace") or {}
    decision_state = "HOLD" if decision.get("selected_package_id") == "HOLD" else ("CHANGE" if selected else "REVIEW")
    lineup_section = _lineup(lineup, compact)
    captaincy_section = _captaincy(lineup)
    price_section = _price(price, watchlist)
    presentation = _natural_presentation(
        decision_state=decision_state,
        lineup=lineup,
        captaincy=captaincy_section,
        price_section=price_section,
        checkpoint=checkpoint,
        truth=truth,
        decision=decision,
    )
    user_report = {
        "layer": "USER_REPORT",
        "report_mode": "COMPACT_DELTA" if compact else "FULL_DECISION",
        "request_context": report_request,
        "presentation": presentation,
        "report_checkpoint": checkpoint,
        "decision": {
            "state": decision_state,
            "selected_package_id": decision.get("selected_package_id"),
            "confidence": trace.get("confidence"),
            "raw_machine_state_for_audit": True,
        },
        "changes_since_last_report": changes,
        "owned_squad": {
            "authority": (truth.get("team") or {}).get("authority"),
            "projection_baseline": (truth.get("team") or {}).get("projection_baseline") or {},
            "count": _owned_count(truth),
        },
        "starting_xi": lineup_section,
        "captaincy": captaincy_section,
        "chip": lineup.get("chip_context") or {},
        "price_radar": price_section,
        "external_watchlist": watchlist,
        "engine_line": {
            "status": governance.get("overall") or governance.get("status") or "UNKNOWN",
            "review_only": not bool(governance.get("go_allowed", False)),
        },
        "action_board": [],
    }
    actions = [
        {"action": user_report["decision"]["state"], "target": "SQUAD"},
        {"action": user_report["starting_xi"]["decision"], "target": "XI"},
        {"action": user_report["captaincy"]["decision"], "target": "CAPTAIN"},
    ]
    for pos, rows in (watchlist.get("positions") or {}).items():
        for row in rows[:1]:
            actions.append({"action": "WATCH", "target": row.get("name"), "position": pos})
    user_report["action_board"] = actions[: int((cfg.get("action_board") or {}).get("max_items") or len(actions))]
    technical = {
        "layer": "TECHNICAL_APPENDIX",
        "request_context": report_request,
        "decision_trace": trace,
        "dss": decision.get("dss") or {},
        "prediction_quality": prediction.get("prediction_quality") or {},
        "source_fusion": ((prediction.get("full_core_enrichment") or {}).get("source_fusion") if isinstance(prediction.get("full_core_enrichment"), dict) else {}),
        "gate0_preflight_pass": decision.get("gate0_preflight_pass"),
        "governance": governance,
        "performance": payload.get("performance") or {},
        "user_lineup_authority": decision.get("user_lineup_authority") or {},
        "engine_lineup_recommendation": decision.get("engine_lineup_recommendation") or {},
        "report_checkpoint": checkpoint,
        "provenance": {
            "ruleset_id": decision.get("ruleset_id"),
            "prediction_model": prediction.get("model_version"),
            "decision_model": decision.get("model"),
        },
    }
    state = {
        **checkpoint_state,
        "fingerprint": _fingerprint(current),
        "state": current,
    }
    return {
        "schema_version": int(cfg.get("schema_version") or 1),
        "model": cfg.get("model_id"),
        "user_report": user_report,
        "technical_appendix": technical,
        "report_state": state,
    }
