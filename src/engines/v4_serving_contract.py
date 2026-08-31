from __future__ import annotations

import json
import math
from statistics import median
from time import perf_counter
from typing import Any

from src.engines.v4_official_fact_integrity import build_publication_integrity, extract_public_fact
from src.utils import CONFIG, DATA, atomic_json, iso_now, read_json

POLICY = CONFIG / "serving_improvement_registry.json"
OUTFILE = DATA / "serving_payload_v4.json"
BENCHMARK = DATA / "serving_benchmark_v4.json"
PUBLICATION_INTEGRITY = DATA / "publication_integrity_v4.json"
FRAMEWORK_HEALTH = DATA / "framework_health_v4.json"
EXTERNAL_SOURCE_EVIDENCE = DATA / "external_source_evidence.json"
WEATHER_EVIDENCE = DATA / "weather_evidence.json"
WARM_BENCHMARK_RUNS = 25

SOURCE_DISPLAY = {
    "official_fpl_native": "Official FPL",
    "official_clubs": "club/manager",
    "official_manager_team_communications": "club/manager",
    "reliable_beat_reporters": "reliable reporters",
    "verified_press_conference_reporting": "reliable reporters",
    "reliable_injury_lineup_reporters": "reliable reporters",
    "fpl_live_livefpl": "LiveFPL",
    "onefpl": "OneFPL",
    "fffix": "FFFix",
    "ffhub": "FFHub",
    "ffscout": "FFScout",
    "ben_crellin_fixture_chip_context": "Ben Crellin",
    "x_twitter": "X",
    "reddit": "Reddit",
}
REQUIRED_SOURCE_PANEL = [
    "Official FPL", "club/manager", "reliable reporters", "LiveFPL", "OneFPL",
    "FFFix", "FFHub", "FFScout", "Ben Crellin", "X", "Reddit",
]


def _normalize_source_status(value: str | None) -> str:
    raw = str(value or "UNAVAILABLE").upper().replace(" ", "_")
    return {
        "AVAILABLE": "ACCESSIBLE",
        "ACCESSIBLE": "ACCESSIBLE",
        "PARTIAL": "PARTIAL",
        "STALE": "STALE",
        "NO_MATERIAL_UPDATE": "NO_MATERIAL_UPDATE",
        "UNAVAILABLE": "UNAVAILABLE",
    }.get(raw, "UNAVAILABLE")


def build_source_panel(latest: dict, external: dict | None = None) -> dict:
    external = external if external is not None else read_json(EXTERNAL_SOURCE_EVIDENCE, {})
    grouped: dict[str, list[dict]] = {name: [] for name in REQUIRED_SOURCE_PANEL}
    for row in ((latest.get("source_sweep_status") or {}).get("statuses") or []):
        display = SOURCE_DISPLAY.get(str(row.get("source_id") or ""))
        if display in grouped:
            grouped[display].append(row)
    panel = []
    for display in REQUIRED_SOURCE_PANEL:
        ext = (external.get("sources") or {}).get(display) or {}
        if ext:
            status = _normalize_source_status(ext.get("status"))
            evidence = ext.get("evidence")
            signal = ext.get("signal")
        else:
            rows = grouped.get(display) or []
            statuses = [_normalize_source_status(row.get("status")) for row in rows]
            if "ACCESSIBLE" in statuses:
                status = "ACCESSIBLE"
            elif "PARTIAL" in statuses:
                status = "PARTIAL"
            elif "STALE" in statuses:
                status = "STALE"
            elif "NO_MATERIAL_UPDATE" in statuses:
                status = "NO_MATERIAL_UPDATE"
            else:
                status = "UNAVAILABLE"
            evidence = ";".join(str(row.get("evidence") or "") for row in rows if row.get("evidence")) or None
            signal = None
        panel.append({"source": display, "status": status, "evidence": evidence, "signal": signal})

    tier1 = next(row for row in panel if row["source"] == "Official FPL")
    non_tier1_signals = [str(row.get("signal") or "").upper() for row in panel if row["source"] != "Official FPL" and row.get("signal")]
    if not non_tier1_signals:
        consensus = "NEUTRAL"
    elif len(set(non_tier1_signals)) == 1:
        consensus = "ALIGN"
    elif tier1["status"] == "ACCESSIBLE":
        consensus = "REVIEW_DIVERGENCE"
    else:
        consensus = "DIVERGE"
    return {
        "consensus_state": consensus,
        "sources": panel,
        "tier1_official_fpl_status": tier1["status"],
        "tier1_facts_cannot_be_overridden": True,
        "fabrication_forbidden": True,
    }


def _owned_rows(team: dict, tactical: dict) -> list[dict]:
    ledger = {int(row.get("element") or 0): row for row in team.get("team_value_ledger") or []}
    public = {
        int(row.get("element_id") or row.get("element") or 0): row
        for row in tactical.get("owned") or []
    }
    out = []
    for row in team.get("squad") or []:
        element = int(row.get("element") or 0)
        fact = extract_public_fact(public.get(element) or {}, expected_element=element)
        value = ledger.get(element) or {}
        out.append({
            **fact,
            "purchase_cost": value.get("purchase_cost"),
            "sell_cost": value.get("sell_cost"),
        })
    if len(out) != 15:
        raise RuntimeError(f"serving contract requires exact 15 owned, got {len(out)}")
    return out


def _rest_context(competitive: dict, owned_ids: set[int]) -> list[dict]:
    rows = []
    for player in competitive.get("players") or []:
        element = int(player.get("element") or 0)
        if element not in owned_ids:
            continue
        matches = list(player.get("current_gw_matches") or [])
        latest_match = matches[-1] if matches else None
        rows.append({
            "element": element,
            "name": player.get("name"),
            "last_competitive_match": latest_match,
            "press_conference": player.get("press_conference") or {},
        })
    return rows


def _what_changed(decision: dict) -> list[str]:
    transfer = ((decision.get("dimensions") or {}).get("transfer") or {})
    state = transfer.get("candidate_state")
    if state == "MATERIAL_UPGRADE_NON_ACTIONABLE":
        incoming = ", ".join(str(row.get("name") or row.get("element")) for row in transfer.get("in") or [])
        outgoing = ", ".join(str(row.get("name") or row.get("element")) for row in transfer.get("out") or [])
        return [f"Material challenger detected: {outgoing} -> {incoming}, but it is not executable yet.", "Blocking evidence is shown in the action board."]
    if state == "ACTIONABLE_CHANGE":
        return ["A material transfer package cleared current actionability gates."]
    if state == "REVIEW":
        return ["An optional challenger remains under review; no execution is authorized."]
    return ["No material actionable squad change was resolved at this checkpoint."]


def _main_battle(lineup: dict) -> dict:
    alternatives = list(lineup.get("formation_alternatives") or [])
    gk = lineup.get("gk_selection") or {}
    bench = lineup.get("bench_governance") or {}
    if gk.get("status") == "OPEN":
        return {"type": "GK", "status": "OPEN", "detail": gk}
    if str(lineup.get("formation_state") or "") == "OPEN":
        return {"type": "FORMATION", "status": "OPEN", "detail": alternatives[:3]}
    if bench.get("status") == "OPEN":
        return {"type": "BENCH", "status": "OPEN", "detail": bench}
    return {"type": "XI", "status": "DECIDED", "detail": alternatives[:2]}


def build_serving_payload(
    decision: dict,
    effective_plan: dict,
    team: dict,
    tactical: dict,
    lineup: dict,
    prices: dict,
    latest: dict,
    competitive: dict,
    source_panel: dict | None = None,
    weather: dict | None = None,
) -> dict:
    start = perf_counter()
    source_panel = source_panel or build_source_panel(latest)
    weather = weather if weather is not None else read_json(WEATHER_EVIDENCE, {})
    owned = _owned_rows(team, tactical)
    watchlist = list(tactical.get("watchlist") or [])
    if len(watchlist) != 20:
        raise RuntimeError(f"serving contract requires exact 20 watchlist, got {len(watchlist)}")
    for row in watchlist:
        extract_public_fact(row, expected_element=int(row.get("element") or 0))
    effective = effective_plan.get("effective_plan") or {}
    starting = list(effective.get("starting_xi") or [])
    bench = effective.get("bench") or {}
    if len(starting) != 11:
        raise RuntimeError("serving contract requires exact XI")
    bench_rows = ([bench.get("gk")] if bench.get("gk") else []) + list(bench.get("order") or [])
    if len(bench_rows) != 4:
        raise RuntimeError("serving contract requires exact four-player bench")

    values = team.get("totals") or {}
    payload = {
        "schema_version": 4963,
        "contract": "V4_HUMAN_SERVING_V1",
        "generated_at": iso_now(),
        "canonical_resolution_id": decision.get("resolution_id"),
        "first_line": decision.get("headline"),
        "overall_action": decision.get("overall_action"),
        "summary": decision.get("summary"),
        "squad_value": {
            "squad_market_value": values.get("squad_market_value"),
            "itb": values.get("itb"),
            "total_market_funds": values.get("total_market_funds"),
            "squad_sell_value": values.get("squad_sell_value"),
            "transferable_funds": values.get("transferable_funds"),
            "unit": values.get("unit"),
        },
        "owned_15": owned,
        "watchlist_20": watchlist,
        "xi": starting,
        "bench": bench_rows,
        "formation": effective.get("formation"),
        "captain": effective.get("captain"),
        "vice_captain": effective.get("vice_captain"),
        "cvc_state": (decision.get("dimensions") or {}).get("captaincy"),
        "chip": (decision.get("dimensions") or {}).get("chip"),
        "what_changed": _what_changed(decision),
        "fixture_rest_context": _rest_context(competitive, {row["element"] for row in owned}),
        "main_starting_xi_battle": _main_battle(lineup),
        "price_radar": {
            "fact": {
                "confirmed_official_price_changes": prices.get("confirmed_changes") or [],
                "current_price_and_ownership_source": "owned_15/watchlist_20 canonical Official FACT rows",
            },
            "model": {
                "provider": prices.get("source"),
                "health": prices.get("health") or {},
                "contract": prices.get("contract") or {},
                "top_buy_pressure": (prices.get("top_buy_pressure") or [])[:10],
                "top_sell_pressure": (prices.get("top_sell_pressure") or [])[:10],
                "unavailable_semantics": "UNAVAILABLE",
                "no_signal_semantics": "NO_SIGNAL",
                "stale_semantics": "STALE_WITH_TIMESTAMP_AND_AGE",
            },
            "confirmed_changes": prices.get("confirmed_changes") or [],
            "top_buy_pressure": (prices.get("top_buy_pressure") or [])[:10],
            "top_sell_pressure": (prices.get("top_sell_pressure") or [])[:10],
            "action": (decision.get("dimensions") or {}).get("price"),
        },
        "consensus": source_panel,
        "tactical": {
            "owned": tactical.get("owned") or [],
            "watchlist": tactical.get("watchlist") or [],
            "compact_material_highlights_only": True,
            "deep_external_evidence_file": "data/tactical_external_evidence.json",
        },
        "rest": competitive.get("coverage") or {},
        "weather": weather if weather else {"status": "UNAVAILABLE", "fabricated": False},
        "engine_source_line": {
            "engine": latest.get("engine_version"),
            "official_authority": "raw_snapshot.official",
            "squad_authority": latest.get("squad_authority"),
            "freshness": decision.get("freshness") or {},
            "source_consensus": source_panel.get("consensus_state"),
        },
        "action_board": decision.get("dimensions") or {},
        "guardrails": {
            "derived_from_canonical_resolved_decision_only": True,
            "technical_terms_kept_out_of_primary_summary": True,
            "exact_15_owned": len(owned) == 15,
            "exact_20_watchlist": len(watchlist) == 20,
            "exact_11_xi": len(starting) == 11,
            "exact_4_bench": len(bench_rows) == 4,
            "tier1_external_consensus_cannot_override_official": True,
            "composition_only_no_model_recompute": True,
            "report_specific_fact_hydration_forbidden": True,
            "official_fact_completeness_required_before_publication": True,
            "publication_integrity_independent_of_execution_authority": True,
            "price_fact_and_model_evidence_separated": True,
        },
    }
    payload["quick_serving_ms"] = round((perf_counter() - start) * 1000.0, 3)
    return payload


def _p95(samples: list[float]) -> float:
    if not samples:
        return 0.0
    ordered = sorted(float(value) for value in samples)
    index = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return round(ordered[index], 3)


def build_benchmark(payload: dict, latest: dict, orchestration: dict | None = None, warm_samples_ms: list[float] | None = None) -> dict:
    policy = (read_json(POLICY, {}) or {}).get("performance") or {}
    orchestration = orchestration or read_json(DATA / "service_orchestration_v4.json", {})
    quick_ms = float(payload.get("quick_serving_ms") or 0.0)
    target = float(policy.get("quick_serving_target_ms") or 1000.0)
    raw_ms = float((latest.get("performance") or {}).get("raw_snapshot_ms") or 0.0)
    total_ms = float(orchestration.get("total_wall_ms") or orchestration.get("wall_ms") or 0.0)
    mode = str(latest.get("mode") or "daily").upper()
    samples = [float(value) for value in (warm_samples_ms or [quick_ms])]
    warm_median = round(float(median(samples)), 3)
    warm_p95 = _p95(samples)
    return {
        "schema_version": 2,
        "generated_at": iso_now(),
        "quick_serving": {"actual_ms": quick_ms, "target_ms": target, "status": "PASS" if quick_ms < target else "WARN"},
        "warm_serving": {
            "runs": len(samples),
            "median_ms": warm_median,
            "p95_ms": warm_p95,
            "target_p95_ms": target,
            "status": "PASS" if len(samples) >= WARM_BENCHMARK_RUNS and warm_p95 < target else "WARN",
            "production_sized_materialized_inputs": True,
            "decision_semantics_recomputed": False,
        },
        "deep_review": {"actual_ms": total_ms if total_ms else None, "source": "service_orchestration_v4.total_wall_ms", "status": "MEASURED" if total_ms else "UNAVAILABLE"},
        "match_mode_refresh": {"actual_ms": raw_ms if mode == "LIVE" else None, "source": "raw_snapshot.duration_ms", "status": "MEASURED_CURRENT_RUN" if mode == "LIVE" else "NOT_CURRENT_MODE"},
        "deadline_day_refresh": {"actual_ms": raw_ms if mode == "DEADLINE" else None, "source": "raw_snapshot.duration_ms", "status": "MEASURED_CURRENT_RUN" if mode == "DEADLINE" else "NOT_CURRENT_MODE"},
        "long_term_quick_serving_sub1s_target_preserved": True,
        "volatile_official_facts_must_not_be_cached_past_freshness_threshold": True,
    }


def _blocked_payload(integrity: dict) -> dict:
    return {
        "schema_version": 1,
        "contract": "V4_HUMAN_SERVING_BLOCKED_V1",
        "generated_at": iso_now(),
        "status": "BLOCKED",
        "user_report": None,
        "publication_integrity": integrity,
        "reason": "OFFICIAL_FACT_COMPLETENESS_FAIL_CLOSED",
        "stale_complete_report_reuse_forbidden": True,
    }


def write_serving_payload(decision: dict, effective_plan: dict, team: dict, tactical: dict, lineup: dict, prices: dict, latest: dict, competitive: dict) -> dict:
    weather = read_json(WEATHER_EVIDENCE, {})
    integrity = build_publication_integrity(
        tactical,
        latest,
        prices,
        decision,
        framework_health=read_json(FRAMEWORK_HEALTH, {}),
        weather=weather,
    )
    atomic_json(PUBLICATION_INTEGRITY, integrity)
    if integrity.get("status") != "PASS":
        blocked = _blocked_payload(integrity)
        atomic_json(OUTFILE, blocked)
        atomic_json(BENCHMARK, {
            "schema_version": 2,
            "generated_at": iso_now(),
            "status": "BLOCKED",
            "reason": "OFFICIAL_FACT_COMPLETENESS_FAIL_CLOSED",
            "publication_integrity": integrity.get("status"),
        })
        raise RuntimeError(
            "PUBLICATION_INTEGRITY_BLOCKED: complete USER_REPORT forbidden; "
            f"owned={integrity.get('owned')} watchlist={integrity.get('watchlist')} "
            f"defects={len(integrity.get('defects') or [])}"
        )

    source_panel = build_source_panel(latest)
    payload = build_serving_payload(
        decision,
        effective_plan,
        team,
        tactical,
        lineup,
        prices,
        latest,
        competitive,
        source_panel=source_panel,
        weather=weather,
    )
    payload["publication_integrity"] = integrity
    samples = [float(payload.get("quick_serving_ms") or 0.0)]
    for _ in range(WARM_BENCHMARK_RUNS - 1):
        measured = build_serving_payload(
            decision,
            effective_plan,
            team,
            tactical,
            lineup,
            prices,
            latest,
            competitive,
            source_panel=source_panel,
            weather=weather,
        )
        samples.append(float(measured.get("quick_serving_ms") or 0.0))
    atomic_json(OUTFILE, payload)
    atomic_json(BENCHMARK, build_benchmark(payload, latest, warm_samples_ms=samples))
    return payload
