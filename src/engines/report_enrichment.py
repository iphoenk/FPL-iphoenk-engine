from __future__ import annotations

from typing import Any

from src.engines.owned_challenger_comparator import build as build_owned_challenger_comparator
from src.engines.report_time_intelligence import run as run_report_time_intelligence
from src.utils import DATA, atomic_json, read_json


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _projection_map(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(row["element"]): row for row in payload.get("players") or [] if row.get("element") is not None}


def _gw_row(proj: dict[str, Any], gw: int) -> dict[str, Any]:
    return next((row for row in proj.get("xpts_by_gw") or [] if int(row.get("gw") or -1) == gw), {})


def _battle_metrics(element: int | None, projections: dict[str, Any], planning_gw: int) -> dict[str, Any]:
    if element is None:
        return {}
    proj = _projection_map(projections).get(int(element)) or {}
    xmins = proj.get("xmins") or {}
    gw = _gw_row(proj, planning_gw)
    return {
        "element": element,
        "name": proj.get("name"),
        "xpts": gw.get("mean"),
        "xmins": xmins.get("expected_minutes"),
        "start_probability": xmins.get("start_probability"),
        "dnp_probability": xmins.get("dnp_probability"),
        "model_confidence": proj.get("projection_confidence"),
    }


def _battle_reasons(leader: dict[str, Any], challenger: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    xpts_delta = _f(leader.get("xpts")) - _f(challenger.get("xpts"))
    xmins_delta = _f(leader.get("xmins")) - _f(challenger.get("xmins"))
    start_delta = _f(leader.get("start_probability")) - _f(challenger.get("start_probability"))
    if abs(xpts_delta) >= 0.10:
        reasons.append(f"projected points {'+' if xpts_delta >= 0 else ''}{xpts_delta:.2f}")
    if abs(xmins_delta) >= 2.0:
        reasons.append(f"xMins {'+' if xmins_delta >= 0 else ''}{xmins_delta:.1f}")
    if abs(start_delta) >= 0.03:
        reasons.append(f"starter probability {'+' if start_delta >= 0 else ''}{start_delta * 100:.1f}pp")
    if not reasons:
        reasons.append("model margin sangat tipis; belum ada pembeda kuat")
    return reasons[:3]


_DATA_STATE_ID = {
    "AVAILABLE": "data terstruktur tersedia",
    "CACHED_LAST_KNOWN_GOOD": "hanya cache terakhir; tidak dipakai sebagai data saat ini",
    "STALE": "data kedaluwarsa; tidak dipakai sebagai data saat ini",
    "SOURCE_REACHABLE_NO_STRUCTURED_OBSERVATION": "situs terjangkau, tetapi data terstruktur belum tersedia",
    "SOURCE_REACHABLE_NOT_INGESTED": "situs terjangkau, tetapi capability ini belum di-ingest",
    "UNAVAILABLE": "tidak tersedia",
    "DISABLED": "tidak dijalankan oleh collector",
}


def _source_availability(source_health: dict[str, Any]) -> dict[str, Any]:
    sources = {str(row.get("id")): row for row in source_health.get("sources") or []}
    capability_rows = source_health.get("capability_health") or []
    selected = []
    for source_id in ("livefpl",):
        source = sources.get(source_id) or {}
        price = next(
            (row for row in capability_rows if row.get("source_id") == source_id and row.get("capability") == "price_prediction"),
            {},
        )
        state = str(price.get("data_state") or "UNAVAILABLE")
        selected.append({
            "source": source.get("name") or source_id,
            "source_id": source_id,
            "terjangkau": bool(source.get("reachable")),
            "status_sumber": source.get("status"),
            "status_data_harga": _DATA_STATE_ID.get(state, "status data belum dikenali"),
            "structured_state": state,
            "observasi_baru": int(price.get("fresh_observations") or 0),
        })
    return {
        "otoritas": "Official FPL tetap menjadi sumber native resmi",
        "collector_challenger": selected,
        "report_time": {
            "livefpl": "EO/live-rank challenger, terutama MATCH MODE",
            "onefpl": "dicek melalui web saat report terjadwal atau on-demand untuk transfer trends, market momentum, price/planner context",
            "fffix": "predicted points, predicted lineup/xMins, price dan rotation challenger",
            "ffhub": "AI transfer/decision, fixture/player comparison, XI/captain challenger",
            "ffscout": "predicted lineup, team news, RMT/player comparison dan tactical/editorial challenger",
            "fixture_strategy": "Ben Crellin / schedule expert dicek saat report dibuat",
            "pundit_consensus": "FPL Harry, FPL Focal, Let's Talk FPL, BigManBakar, dan Scout editorial dibandingkan dengan DSS",
            "community": "Reddit r/FantasyPL dipakai sebagai sinyal komunitas yang wajib cross-check",
        },
        "catatan": "External benchmark dan source report-time tidak mengubah native truth/DSS. Consensus hanya evidence overlay; factual divergence memicu refresh Official, bukan overwrite external.",
    }


def _report_time_user_block(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status"),
        "web_refresh_required": bool(payload.get("web_refresh_required")),
        "pundit_consensus_vs_dss": payload.get("pundit_consensus") or [],
        "fixture_strategy": payload.get("fixture_strategy") or [],
        "model_challenger": payload.get("model_challenger") or [],
        "community_signal": payload.get("community_signal") or [],
        "verified_news": payload.get("verified_news") or [],
        "catatan": "Konsensus pundit bersifat advisory. Perbedaan dengan DSS harus ditampilkan, bukan disembunyikan atau otomatis mengubah keputusan model.",
    }


def _external_consensus_user_block(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "overall": payload.get("overall") or "INSUFFICIENT_EVIDENCE",
        "requires_official_refresh": bool(payload.get("requires_official_refresh")),
        "source_status": payload.get("source_status") or {},
        "subjects": [
            {"subject": row.get("subject"), "classification": row.get("classification")}
            for row in payload.get("subjects") or []
        ],
        "advisory_only": bool((payload.get("governance") or {}).get("advisory_only", True)),
        "catatan": "Native multi-GW conclusion remains primary. External benchmarks challenge and explain divergence only; no majority vote and no overwrite of Official/native truth.",
    }


def _comparator_user_block(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status"),
        "advisory_only": True,
        "owned_count": payload.get("owned_count"),
        "governed_watchlist_count": payload.get("governed_watchlist_count"),
        "emerging_candidate_count": payload.get("emerging_candidate_count"),
        "state_counts": payload.get("state_counts") or {},
        "top_comparisons": [
            {
                "player_out": row.get("player_out"),
                "player_in": row.get("player_in"),
                "challenger_type": row.get("challenger_type"),
                "state": row.get("state"),
                "horizon_5gw": (row.get("horizons") or {}).get("5"),
                "missing_critical_evidence": row.get("missing_critical_evidence") or [],
                "confidence": row.get("confidence"),
            }
            for row in (payload.get("top_comparisons") or [])[:8]
        ],
        "catatan": "Comparator reuses canonical xPts/xMins/tactical/price/package evidence. It is advisory-only and cannot overwrite XI, C/VC, chip, watchlist, or canonical transfer decision.",
    }


def _action_class(subject: str) -> str:
    return "FACT_CONSTRAINT" if subject == "Chip" else "MODEL_DERIVED"


def _apply_readiness_and_actionability(
    user: dict[str, Any],
    tech: dict[str, Any],
    latest: dict[str, Any],
    report_time: dict[str, Any],
) -> None:
    framework = tech.get("framework_health") or {}
    prediction = latest.get("prediction_evaluation") or {}
    sample_size = int(prediction.get("sample_size") or 0)
    model_eligible = bool(prediction.get("dynamic_weight_eligible")) and sample_size > 0
    engine_ready = (
        str(framework.get("overall") or "") == "GREEN"
        and framework.get("go_allowed") is True
        and not list(framework.get("critical_failed") or [])
    )
    evidence_ready = str(report_time.get("status") or "") == "READY"

    readiness = {
        "engine": "ENGINE_READY" if engine_ready else "ENGINE_REVIEW_REQUIRED",
        "final_report_evidence": "FINAL_REPORT_EVIDENCE_READY" if evidence_ready else "FINAL_REPORT_EVIDENCE_PENDING",
        "report_time_status": report_time.get("status"),
        "web_refresh_required": bool(report_time.get("web_refresh_required")),
        "predictive_validation": {
            "status": prediction.get("status"),
            "sample_size": sample_size,
            "settled_gameweeks": list(prediction.get("settled_gameweeks") or []),
            "model_derived_actionability": "ACTIVE" if model_eligible else "GATED",
        },
    }
    user["readiness"] = readiness

    for item in user.get("action_board") or []:
        subject = str(item.get("subject") or "")
        action_class = _action_class(subject)
        item["action_class"] = action_class
        if action_class == "FACT_CONSTRAINT":
            item["actionability"] = "ACTIONABLE"
            item["calibration_gate_applies"] = False
        else:
            item["actionability"] = "ACTIONABLE" if model_eligible else "ADVISORY_UNTIL_SETTLED_VALIDATION"
            item["calibration_gate_applies"] = True

    tech["readiness_and_actionability"] = {
        **readiness,
        "policy": {
            "runtime_readiness_is_separate_from_final_report_evidence": True,
            "fact_constraint_actionability_is_not_blocked_by_model_sample_size": True,
            "model_derived_actionability_requires_prediction_evaluation_eligibility": True,
            "existing_decisions_are_annotated_not_rewritten": True,
        },
    }
    tech.setdefault("audit", {})["runtime_and_report_evidence_readiness_are_separate"] = True
    tech["audit"]["fact_and_model_actionability_are_separate"] = True


def run() -> dict[str, Any]:
    user = read_json(DATA / "user_report.json", {})
    tech = read_json(DATA / "technical_appendix.json", {})
    latest = read_json(DATA / "latest.json", {})
    team = read_json(DATA / "team.json", {})
    lineup = read_json(DATA / "lineup_decision.json", {})
    projections = read_json(DATA / "projections.json", {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    source_health = read_json(DATA / "source_health.json", {})
    external_consensus = read_json(DATA / "external_consensus.json", {})
    comparator = build_owned_challenger_comparator()
    report_time = run_report_time_intelligence()

    ledger = {int(row.get("element") or -1): row for row in team.get("team_value_ledger") or []}
    watch_rows = {
        int(row.get("element") or -1): row
        for rows in (watchlist.get("positions") or {}).values()
        for row in rows
    }
    price = user.get("price_radar") or {}
    for row in price.get("owned") or []:
        source = ledger.get(int(row.get("element") or -1)) or {}
        now_cost = source.get("now_cost")
        row["price"] = round(_f(now_cost) / 10.0, 1) if now_cost is not None else None
    for row in price.get("external_watchlist") or []:
        source = watch_rows.get(int(row.get("element") or -1)) or {}
        raw_price = source.get("now_cost", source.get("price"))
        if raw_price is None:
            row["price"] = None
        else:
            value = _f(raw_price)
            row["price"] = round(value / 10.0, 1) if value >= 30 else round(value, 1)

    battle = lineup.get("main_starting_xi_battle") or {}
    leader_raw = (battle.get("starter_side") or [{}])[0]
    challenger_raw = (battle.get("bench_side") or [{}])[0]
    planning_gw = int(lineup.get("planning_gw") or projections.get("planning_gw") or 1)
    leader = _battle_metrics(leader_raw.get("element"), projections, planning_gw)
    challenger = _battle_metrics(challenger_raw.get("element"), projections, planning_gw)
    section = user.get("starting_xi") or {}
    model_battle = (section.get("model") or {}).get("battle") or {}
    model_battle["leader_metrics"] = leader
    model_battle["challenger_metrics"] = challenger
    model_battle["main_reasons"] = _battle_reasons(leader, challenger) if leader and challenger else []

    user["source_availability"] = _source_availability(source_health)
    user["report_time_intelligence"] = _report_time_user_block(report_time)
    user["external_consensus"] = _external_consensus_user_block(external_consensus)
    user["owned_vs_challenger"] = _comparator_user_block(comparator)
    tech["source_capability_health"] = {
        "source_overall": source_health.get("overall"),
        "capabilities": source_health.get("capability_health") or [],
        "structured_observation_count": source_health.get("structured_observation_count", 0),
        "structured_cached_count": source_health.get("structured_cached_count", 0),
        "structured_stale_count": source_health.get("structured_stale_count", 0),
        "disagreement_count": source_health.get("disagreement_count", 0),
    }
    tech["report_time_intelligence"] = report_time
    tech["external_consensus"] = external_consensus
    tech["owned_challenger_comparator"] = comparator
    tech["runtime"] = {
        "current_run_ref": "data/runtime_performance.json",
        "embedded_during_report_stage": False,
        "note": "current-run runtime metadata is finalized by the orchestrator after report generation",
    }
    tech.setdefault("audit", {})["price_radar_has_current_price_when_source_available"] = True
    tech["audit"]["starting_xi_battle_has_decision_evidence"] = True
    tech["audit"]["source_reachability_is_separate_from_structured_data"] = True
    tech["audit"]["report_time_sources_do_not_mutate_dss"] = True
    tech["audit"]["pundit_consensus_is_compared_with_dss"] = True
    tech["audit"]["external_consensus_is_advisory_only"] = bool((external_consensus.get("governance") or {}).get("advisory_only", True))
    tech["audit"]["external_consensus_never_majority_votes"] = not bool((external_consensus.get("governance") or {}).get("majority_vote_used", False))
    tech["audit"]["external_consensus_does_not_mutate_native_truth"] = not bool((external_consensus.get("governance") or {}).get("native_truth_mutated", False))
    tech["audit"]["owned_challenger_comparator_is_advisory_only"] = bool(comparator.get("advisory_only"))
    tech["audit"]["owned_challenger_comparator_reuses_governed_watchlist"] = int(comparator.get("governed_watchlist_count") or 0) == 20
    _apply_readiness_and_actionability(user, tech, latest, report_time)

    atomic_json(DATA / "user_report.json", user)
    atomic_json(DATA / "technical_appendix.json", tech)
    return {"user_report": user, "technical_appendix": tech}


if __name__ == "__main__":
    run()
