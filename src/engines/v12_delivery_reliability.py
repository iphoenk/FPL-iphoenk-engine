from __future__ import annotations

"""Fail-operational delivery primitives for FPL Master V12.

This module is deliberately downstream of V6 facts and V12 analytics. It does
not schedule work, acquire facts, compute football probabilities, select
transfers, or own decision mathematics. Its responsibilities are limited to:

* occurrence-bound prefetch terminality checks;
* bounded wait/re-fetch coordination;
* truthful degraded DEEP assembly when upstream analytics cannot run;
* one canonical private serving snapshot for ChatGPT/web/mobile clients;
* atomic local serving-artifact writes and presentation-contract validation.
"""

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence


CANONICAL_DEEP_SECTIONS: tuple[tuple[str, str], ...] = (
    ("S01", "DECISION / CURRENT STATUS"),
    ("S02", "OUR15"),
    ("S03", "DECISION DELTA"),
    ("S04", "MATERIAL DEVELOPMENTS / CHANGES"),
    ("S05", "FIXTURES / REST / CONDITIONS"),
    ("S06", "FORMATION / XI / BENCH"),
    ("S06B", "FORMATION & MINI-LEAGUE STRATEGY"),
    ("S07", "XI BATTLE"),
    ("S08", "CAPTAIN / VICE CAPTAIN"),
    ("S09", "CHIP STRATEGY"),
    ("S10", "ACTIONABLE PRICE RADAR"),
    ("S11", "WATCHLIST20"),
    ("S12", "RISE20"),
    ("S13", "FALL20"),
    ("S14", "PACKAGE OPTIMIZER / TRANSFER FRONTIER"),
    ("S14B", "3-GW SQUAD STAGING"),
    ("S15", "EVIDENCE QUALITY"),
    ("S15B", "ICON+ MINI-LEAGUE"),
    ("S16", "ALL15 TACTICAL / PROBABILITY REVIEW"),
    ("S16B", "POST-MATCH REVIEW GW1 → NOW"),
    ("S17", "SOURCE HEALTH / FRESHNESS / LINEAGE"),
    ("S18", "ACTION BOARD"),
    ("S19", "FINAL JUDGEMENT"),
)

TERMINAL_SCOPE_STATES = {
    "AVAILABLE",
    "COMPLETE",
    "DEGRADED",
    "PARTIAL",
    "UNAVAILABLE",
    "NOT_APPLICABLE",
}
DELIVERY_STATES = {"READY_FULL", "READY_DEGRADED"}
UI_STATES = {"FRESH", "DEGRADED", "PRIOR", "BLOCKED", "FAILED", "UNAVAILABLE"}


class DeliveryReliabilityError(RuntimeError):
    pass


class PrefetchNotTerminal(DeliveryReliabilityError):
    pass


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists() or path.stat().st_size <= 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _parse_aware(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _same_instant(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return False
    return left.astimezone(right.tzinfo) == right


def inspect_prefetch_terminal(
    runtime_root: Path,
    *,
    report_slot: str,
) -> dict[str, Any]:
    """Return mechanical permission for a full analytical runner to start.

    The gate is intentionally stricter than "a file exists". It binds the
    exact report occurrence and requires the runtime-data publication visible
    to this checkout to be terminal. A terminal degraded mini-league scope is
    recorded but does not make a stale or cross-occurrence prefetch current.
    """
    latest = _read_json(runtime_root / "data/v6/report_prefetch/latest.json", {}) or {}
    health = _read_json(runtime_root / "data/v6/health/report_prefetch.json", {}) or {}
    publish = _read_json(runtime_root / "data/v6/health/publish_integrity.json", {}) or {}

    requested = _parse_aware(report_slot)
    target = _parse_aware(
        latest.get("target_logical_report_slot") or latest.get("logical_slot")
    )
    generated = _parse_aware(latest.get("generated_at"))

    mini_state = str(latest.get("mini_league_status") or "").upper()
    personal_state = str(
        latest.get("public_personal_status")
        or latest.get("personal_status")
        or ""
    ).upper()
    public_first_acceptable = bool(
        latest.get("public_core_complete") is True
        and str(health.get("public_core_status") or "").upper() == "GREEN"
        and latest.get("authenticated_personal_required_for_public_green") is False
        and personal_state in TERMINAL_SCOPE_STATES
        and mini_state in TERMINAL_SCOPE_STATES
        and not (latest.get("public_control_failures") or [])
    )
    prefetch_health_acceptable = bool(
        str(health.get("prefetch_status") or "").upper() == "GREEN"
        or public_first_acceptable
    )
    checks = {
        "report_slot_timezone_aware": requested is not None,
        "report_kind_full_master": str(latest.get("report_kind") or "") == "full_master",
        "target_report_slot_match": _same_instant(target, requested),
        "personal_requested": latest.get("personal_requested") is True,
        "mini_league_requested": latest.get("mini_league_requested") is True,
        "required_mini_league_scope_terminal": mini_state in TERMINAL_SCOPE_STATES,
        "public_core_complete": latest.get("public_core_complete") is True,
        "fresh_for_target_report": latest.get("fresh_for_target_report") is True,
        "prefetch_health_acceptable": prefetch_health_acceptable,
        "runtime_publication_terminal": str(publish.get("status") or "").upper() == "PASS",
        "generated_at_available": generated is not None,
    }
    failed = [name for name, passed in checks.items() if not passed]
    age_minutes = None
    if requested is not None and generated is not None:
        age_minutes = abs(
            (requested - generated.astimezone(requested.tzinfo)).total_seconds()
        ) / 60.0
        if age_minutes > 15.0:
            failed.append("same_occurrence_age")
            checks["same_occurrence_age"] = False
        else:
            checks["same_occurrence_age"] = True

    return {
        "terminal": not failed,
        "checks": checks,
        "failed_checks": list(dict.fromkeys(failed)),
        "report_slot": report_slot,
        "target_logical_report_slot": latest.get("target_logical_report_slot"),
        "report_prefetch_run_id": latest.get("report_prefetch_run_id"),
        "generated_at": latest.get("generated_at"),
        "age_minutes": round(age_minutes, 3) if age_minutes is not None else None,
        "mini_league_status": mini_state or "UNAVAILABLE",
        "personal_status": personal_state or "UNAVAILABLE",
        "publish_integrity": publish.get("status"),
        "latest": latest,
        "health": health,
        "publish": publish,
    }


def wait_for_prefetch_terminal(
    runtime_root: Path,
    *,
    report_slot: str,
    refresh_fn: Callable[[], Any] | None = None,
    timeout_seconds: float | None = None,
    poll_seconds: float | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Bounded terminal-prefetch wait with re-fetch before each retry."""
    timeout = float(
        timeout_seconds
        if timeout_seconds is not None
        else os.getenv("V12_PREFETCH_WAIT_SECONDS", "90")
    )
    poll = float(
        poll_seconds
        if poll_seconds is not None
        else os.getenv("V12_PREFETCH_POLL_SECONDS", "5")
    )
    timeout = max(0.0, min(timeout, 300.0))
    poll = max(0.1, min(poll, 30.0))

    started = monotonic_fn()
    attempts = 0
    last = inspect_prefetch_terminal(runtime_root, report_slot=report_slot)
    while not last["terminal"]:
        elapsed = monotonic_fn() - started
        if elapsed >= timeout:
            raise PrefetchNotTerminal(
                "PREFETCH_NOT_TERMINAL: " + ",".join(last["failed_checks"])
            )
        attempts += 1
        if refresh_fn is not None:
            refresh_fn()
        remaining = timeout - (monotonic_fn() - started)
        if remaining <= 0:
            continue
        sleep_fn(min(poll, remaining))
        last = inspect_prefetch_terminal(runtime_root, report_slot=report_slot)

    return {
        **last["latest"],
        "prefetch_health": last["health"],
        "publish_integrity": last["publish"],
        "same_occurrence_bound": True,
        "report_slot": report_slot,
        "age_minutes": last["age_minutes"],
        "scope_checks": last["checks"],
        "defensive_wait": {
            "attempts": attempts,
            "elapsed_seconds": round(monotonic_fn() - started, 3),
            "bounded": True,
        },
    }


def _extract_previous_section(
    previous_bundle: Mapping[str, Any] | None,
    section_id: str,
) -> dict[str, Any] | None:
    for row in ((previous_bundle or {}).get("report") or {}).get("sections") or []:
        if (
            isinstance(row, Mapping)
            and str(row.get("section_id") or "").upper() == section_id
        ):
            return dict(row)
    return None


def _planning_gw_from_runtime(runtime_root: Path) -> int:
    official = _read_json(runtime_root / "data/v6/current/official_fpl.json", {}) or {}
    bootstrap = ((official.get("official") or {}).get("bootstrap") or {})
    events = [
        dict(row)
        for row in bootstrap.get("events") or []
        if isinstance(row, Mapping)
    ]
    next_rows = [row for row in events if row.get("is_next") is True]
    if next_rows:
        return int(next_rows[0].get("id") or 0)
    current = [row for row in events if row.get("is_current") is True]
    if current:
        return int(current[0].get("id") or 0) + 1
    return 0


def _official_fact_status(runtime_root: Path) -> tuple[str, str | None]:
    official = _read_json(runtime_root / "data/v6/current/official_fpl.json", {}) or {}
    bootstrap = ((official.get("official") or {}).get("bootstrap") or {})
    fixtures = ((official.get("official") or {}).get("fixtures") or [])
    if isinstance(bootstrap, Mapping) and bootstrap.get("elements") and fixtures:
        return "FRESH", official.get("generated_at")
    return "UNAVAILABLE", official.get("generated_at")


def _prior_payload(
    previous_bundle: Mapping[str, Any] | None,
    section_id: str,
    *,
    previous_slot: str | None,
) -> dict[str, Any] | None:
    prior = _extract_previous_section(previous_bundle, section_id)
    if not prior:
        return None
    content = deepcopy(prior.get("content") or {})
    if not isinstance(content, dict):
        content = {"prior_content": content}
    content["presentation_status"] = "PRIOR"
    content["prior_source_occurrence"] = previous_slot
    content["prior_reason"] = (
        "fresh analytical recomputation was blocked; this object is historical context only"
    )
    return content


def _fallback_section(
    section_id: str,
    label: str,
    *,
    root_failure: str,
    prior_content: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if prior_content:
        return {
            "section_id": section_id,
            "label": label,
            "state": "DEGRADED",
            "degradation_reason": "PRIOR_ANALYTICS_EXPLICITLY_LABELLED",
            "content": dict(prior_content),
        }
    return {
        "section_id": section_id,
        "label": label,
        "state": "UNAVAILABLE",
        "degradation_reason": root_failure,
        "content": {
            "presentation_status": "BLOCKED",
            "delivery_stage": "BLOCKED_UPSTREAM",
            "root_failure": root_failure,
            "empty_is_truthful": True,
        },
    }


def assemble_degraded_deep_report(
    *,
    runtime_root: Path,
    report_slot: str,
    output_dir: Path,
    root_failure: str,
    previous_visible_deep_dir: Path | None = None,
) -> dict[str, Any]:
    """Create one usable 23-section DEEP report without inventing analytics."""
    previous_bundle = None
    if previous_visible_deep_dir is not None:
        previous_bundle = _read_json(
            previous_visible_deep_dir / "report_bundle.json", None
        )
    previous_slot = (
        str((previous_bundle or {}).get("report_slot") or "") or None
    )
    planning_gw = _planning_gw_from_runtime(runtime_root)
    if planning_gw <= 0:
        try:
            planning_gw = int((previous_bundle or {}).get("planning_gw") or 0)
        except (TypeError, ValueError):
            planning_gw = 0

    facts_status, facts_generated_at = _official_fact_status(runtime_root)
    prefetch = inspect_prefetch_terminal(runtime_root, report_slot=report_slot)

    sections = [
        _fallback_section(
            section_id,
            label,
            root_failure=root_failure,
            prior_content=_prior_payload(
                previous_bundle,
                section_id,
                previous_slot=previous_slot,
            ),
        )
        for section_id, label in CANONICAL_DEEP_SECTIONS
    ]
    by_id = {row["section_id"]: row for row in sections}

    by_id["S01"] = {
        "section_id": "S01",
        "label": "DECISION / CURRENT STATUS",
        "state": "DEGRADED",
        "degradation_reason": root_failure,
        "content": {
            "presentation_status": "DEGRADED",
            "decision": "WAIT",
            "operational_state": "WAIT",
            "reason": (
                "Fresh analytical execution is blocked upstream. Preserve the "
                "current squad state and do not execute a transfer from stale or fabricated evidence."
            ),
            "transfer_action": "NO EXECUTION FROM DEGRADED ANALYTICS",
            "chip_action": "NO CHIP EXECUTION FROM DEGRADED ANALYTICS",
            "facts_status": facts_status,
            "analytics_status": "BLOCKED_UPSTREAM",
            "delivery_status": "READY_DEGRADED",
        },
    }
    by_id["S03"] = {
        "section_id": "S03",
        "label": "DECISION DELTA",
        "state": "DEGRADED",
        "degradation_reason": "FRESH_ANALYTICAL_DELTA_NOT_RUN",
        "content": {
            "presentation_status": "BLOCKED",
            "summary": "NO FRESH ANALYTICAL DELTA",
            "prior_source_occurrence": previous_slot,
            "empty_is_truthful": True,
        },
    }
    by_id["S04"] = {
        "section_id": "S04",
        "label": "MATERIAL DEVELOPMENTS / CHANGES",
        "state": "DEGRADED" if facts_status == "FRESH" else "UNAVAILABLE",
        "degradation_reason": (
            "ANALYTICS_BLOCKED; FACTS_REMAIN_AVAILABLE"
            if facts_status == "FRESH"
            else "CURRENT_FACTS_UNAVAILABLE"
        ),
        "content": {
            "presentation_status": "DEGRADED" if facts_status == "FRESH" else "UNAVAILABLE",
            "fact_layer": facts_status,
            "facts_generated_at": facts_generated_at,
            "model_update": "NOT_RUN",
            "empty_is_truthful": True,
        },
    }
    by_id["S15"] = {
        "section_id": "S15",
        "label": "EVIDENCE QUALITY",
        "state": "DEGRADED",
        "degradation_reason": root_failure,
        "content": {
            "presentation_status": "DEGRADED",
            "evidence_summary": {
                "Facts": facts_status,
                "Analytics": "BLOCKED",
                "Decision confidence": "PARTIAL",
                "Delivery": "DEGRADED REPORT AVAILABLE",
            },
            "root_issue": root_failure,
            "false_downstream_failures": 0,
        },
    }
    by_id["S17"] = {
        "section_id": "S17",
        "label": "SOURCE HEALTH / FRESHNESS / LINEAGE",
        "state": "DEGRADED",
        "degradation_reason": root_failure,
        "content": {
            "presentation_status": "DEGRADED",
            "root_failure": root_failure,
            "runner_state": "BLOCKED_UPSTREAM",
            "report_slot": report_slot,
            "prefetch_terminal": prefetch["terminal"],
            "prefetch_failed_checks": prefetch["failed_checks"],
            "target_logical_report_slot": prefetch.get("target_logical_report_slot"),
            "facts_generated_at": facts_generated_at,
            "previous_valid_deep": previous_slot,
        },
    }
    by_id["S18"] = {
        "section_id": "S18",
        "label": "ACTION BOARD",
        "state": "COMPLETE",
        "content": {
            "presentation_status": "FRESH",
            "NOW": "WAIT; do not execute a transfer/chip from incomplete analytical evidence.",
            "NEXT": "Use the same occurrence if exact analytics recover; otherwise keep degraded delivery.",
            "TRIGGERS": "Exact occurrence-bound prefetch + fresh analytics become available.",
            "REVERSAL": "Rerender the same occurrence to READY_FULL; do not mint a duplicate report.",
        },
    }
    by_id["S19"] = {
        "section_id": "S19",
        "label": "FINAL JUDGEMENT",
        "state": "DEGRADED",
        "degradation_reason": root_failure,
        "content": {
            "presentation_status": "DEGRADED",
            "decision": "WAIT",
            "final_judgement": (
                "WAIT. Current facts may still be usable, but fresh analytical "
                "proof is incomplete. Do not act on historical model output as if it were current."
            ),
            "reversal_trigger": "same-occurrence fresh analytics validated",
        },
    }

    ordered = [by_id[section_id] for section_id, _ in CANONICAL_DEEP_SECTIONS]
    downstream_stages = (
        "V6_OFFICIAL_FACTS",
        "OUR15_IDENTITY",
        "P1_1_P1_3_FULL_UNIVERSE",
        "WATCHLIST20",
        "P1_7_LINEUP",
        "P1_2_PACKAGE_UTILITY",
        "P1_4_MONTE_CARLO",
        "P1_8_MINI_LEAGUE_OVERLAY",
        "PRE_RENDER_QA",
        "POST_RENDER_QA",
    )
    stage_ledger = [
        {
            "stage": "V6_REPORT_PREFETCH_BINDING",
            "status": "FAILED",
            "required": True,
            "error_class": "UPSTREAM_DELIVERY_ROOT_FAILURE",
            "error": root_failure,
        }
    ] + [
        {
            "stage": stage,
            "status": "NOT_RUN",
            "required": False,
            "reason": "BLOCKED_BY_ROOT_FAILURE",
        }
        for stage in downstream_stages
    ]

    report = {
        "mode": "DEEP",
        "sections": ordered,
        "numbered_headings": 19,
        "rendered_blocks_including_suffix_sections": 23,
        "rendered_blocks_including_15B": 23,
        "exact_canonical_order": True,
    }
    body = render_degraded_deep_text(
        report=report,
        report_slot=report_slot,
        planning_gw=planning_gw,
        facts_status=facts_status,
        root_failure=root_failure,
    )
    execution_proof = {
        "schema_version": 3,
        "runner": "V12_INTEGRATED_REPORT_RUNNER",
        "report_slot": report_slot,
        "report_mode": "DEEP",
        "planning_gw": planning_gw,
        "runner_status": "DEGRADED",
        "delivery_status": "READY_DEGRADED",
        "root_failure": root_failure,
        "runner_state": "BLOCKED_UPSTREAM",
        "canonical_expected_section_ids": [x[0] for x in CANONICAL_DEEP_SECTIONS],
        "rendered_section_ids": [x["section_id"] for x in ordered],
        "canonical_catalog_complete": True,
        "pre_render_qa_status": "DEGRADED_PRESENTATION_PASS",
        "post_render_qa_status": "DEGRADED_PRESENTATION_PASS",
        "human_facing_qa_status": "PASS",
        "stage3_internal_pass": False,
        "stage3_action": None,
        "stages": stage_ledger,
        "downstream_false_failures": 0,
        "monte_carlo_fabricated": False,
        "prior_analytics_relabelled_fresh": False,
    }
    bundle = {
        "schema": "FPL_MASTER_V12_INTEGRATED_REPORT_BUNDLE_V3",
        "authority": "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt",
        "state_authority": False,
        "occurrence_id": f"DEEP|{report_slot}",
        "report_mode": "DEEP",
        "report_slot": report_slot,
        "planning_gw": planning_gw,
        "runner_status": "DEGRADED",
        "delivery_status": "READY_DEGRADED",
        "root_failure": root_failure,
        "stage_ledger": stage_ledger,
        "section_manifest": [
            {"section_id": row["section_id"], "status": row["state"]}
            for row in ordered
        ],
        "pre_render_qa": {
            "status": "DEGRADED_PRESENTATION_PASS",
            "section_count": 23,
            "decision_first": True,
        },
        "post_render_qa": {
            "status": "DEGRADED_PRESENTATION_PASS",
            "section_count": 23,
            "final_judgement_present": True,
        },
        "human_facing_qa": {"status": "PASS", "failures": []},
        "execution_proof": execution_proof,
        "report": report,
        "visible_body": body,
        "governance": {
            "scheduler_created": False,
            "v6_mutated": False,
            "legacy_runtime_executed": False,
            "second_methodology_created": False,
            "qa_relaxed": False,
            "fail_operational_delivery": True,
            "private_serving_snapshot": True,
        },
    }
    failures = validate_delivery_bundle(bundle)
    if failures:
        raise DeliveryReliabilityError(
            "degraded presentation contract failed: " + ",".join(failures)
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report_bundle.json").write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report_body.md").write_text(body, encoding="utf-8")
    (output_dir / "execution_proof.json").write_text(
        json.dumps(execution_proof, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return bundle


def render_degraded_deep_text(
    *,
    report: Mapping[str, Any],
    report_slot: str,
    planning_gw: int,
    facts_status: str,
    root_failure: str,
) -> str:
    lines = [
        f"# FPL MASTER V12 — GW{planning_gw if planning_gw > 0 else '?'} DEEP",
        f"{report_slot}",
        "",
        "DECISION: WAIT",
        f"Data: {facts_status}",
        "Analytics: BLOCKED UPSTREAM",
        "Report: DEGRADED BUT USABLE",
        "",
        "Fresh analytics are incomplete. No transfer or chip is executed from stale or fabricated evidence.",
    ]
    for section in report.get("sections") or []:
        sid = str(section.get("section_id") or "")
        label = str(section.get("label") or "")
        state = str(section.get("state") or "UNAVAILABLE")
        content = dict(section.get("content") or {})
        presentation = str(content.get("presentation_status") or state)
        lines.extend(["", f"## {sid} — {label}", f"Status: {presentation}"])
        if section.get("degradation_reason"):
            lines.append(f"Reason: {section.get('degradation_reason')}")
        if sid == "S01":
            lines.append(f"Decision: {content.get('decision')}")
            lines.append(f"Why: {content.get('reason')}")
            lines.append(f"Transfer: {content.get('transfer_action')}")
            lines.append(f"Chip: {content.get('chip_action')}")
        elif sid == "S15":
            summary = dict(content.get("evidence_summary") or {})
            for key in ("Facts", "Analytics", "Decision confidence", "Delivery"):
                lines.append(f"- {key}: {summary.get(key, 'UNAVAILABLE')}")
            lines.append(f"Root issue: {content.get('root_issue')}")
        elif sid == "S17":
            lines.append(f"Root failure: {content.get('root_failure')}")
            lines.append(f"Runner: {content.get('runner_state')}")
            lines.append(f"Prefetch terminal: {content.get('prefetch_terminal')}")
            lines.append(
                "Failed checks: "
                + ", ".join(content.get("prefetch_failed_checks") or [])
            )
        elif sid == "S18":
            for key in ("NOW", "NEXT", "TRIGGERS", "REVERSAL"):
                lines.append(f"- {key}: {content.get(key)}")
        elif sid == "S19":
            lines.append(str(content.get("final_judgement") or "WAIT"))
        elif presentation == "PRIOR":
            lines.append(
                f"PRIOR source: {content.get('prior_source_occurrence') or 'UNAVAILABLE'}"
            )
            lines.append("Historical analytical context only; not relabelled as current.")
        else:
            lines.append(
                "Current analytical detail is not available for this section; "
                "the section remains visible and truthfully classified."
            )
    return "\n".join(lines).rstrip() + "\n"


def validate_delivery_bundle(bundle: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    sections = [
        dict(row)
        for row in ((bundle.get("report") or {}).get("sections") or [])
        if isinstance(row, Mapping)
    ]
    ids = [str(row.get("section_id") or "") for row in sections]
    expected = [section_id for section_id, _ in CANONICAL_DEEP_SECTIONS]
    if ids != expected:
        failures.append("SECTION_ORDER_OR_COUNT")
    if len(sections) != 23:
        failures.append("SECTION_COUNT_NOT_23")
    if not sections or sections[0].get("section_id") != "S01":
        failures.append("DECISION_NOT_FIRST")
    if not sections or sections[-1].get("section_id") != "S19":
        failures.append("FINAL_JUDGEMENT_NOT_LAST")
    s01 = next((row for row in sections if row.get("section_id") == "S01"), {})
    s19 = next((row for row in sections if row.get("section_id") == "S19"), {})
    if not str((s01.get("content") or {}).get("decision") or "").strip():
        failures.append("DECISION_MISSING")
    if not str((s19.get("content") or {}).get("final_judgement") or "").strip():
        failures.append("FINAL_JUDGEMENT_MISSING")
    root_failures = [
        row
        for row in bundle.get("stage_ledger") or []
        if isinstance(row, Mapping) and str(row.get("status") or "").upper() == "FAILED"
    ]
    if str(bundle.get("delivery_status") or "") == "READY_DEGRADED":
        if len(root_failures) > 1:
            failures.append("MULTIPLE_ROOT_FAILURES")
        false_downstream = [
            row
            for row in root_failures
            if str(row.get("stage") or "") != "V6_REPORT_PREFETCH_BINDING"
        ]
        if false_downstream:
            failures.append("DOWNSTREAM_FALSE_FAILURES")
    if not str(bundle.get("visible_body") or "").strip():
        failures.append("VISIBLE_BODY_EMPTY")
    return failures


def build_serving_snapshot(bundle: Mapping[str, Any]) -> dict[str, Any]:
    sections = [
        dict(row)
        for row in ((bundle.get("report") or {}).get("sections") or [])
        if isinstance(row, Mapping)
    ]
    by_id = {str(row.get("section_id") or ""): row for row in sections}
    s01 = dict((by_id.get("S01") or {}).get("content") or {})
    s19 = dict((by_id.get("S19") or {}).get("content") or {})
    delivery_status = str(bundle.get("delivery_status") or "")
    if delivery_status not in DELIVERY_STATES:
        delivery_status = (
            "READY_FULL"
            if str(bundle.get("runner_status") or "").upper() == "PASS"
            else "READY_DEGRADED"
        )
    root_failure = bundle.get("root_failure")
    decision = (
        s01.get("decision")
        or s01.get("operational_state")
        or ((s19.get("final_judgement") or {}).get("transfer_action")
            if isinstance(s19.get("final_judgement"), Mapping)
            else None)
        or "UNAVAILABLE"
    )
    return {
        "schema_version": 1,
        "occurrence_id": str(
            bundle.get("occurrence_id")
            or f"{bundle.get('report_mode')}|{bundle.get('report_slot')}"
        ),
        "report_slot": bundle.get("report_slot"),
        "report_mode": bundle.get("report_mode"),
        "delivery_status": delivery_status,
        "decision": decision,
        "facts_status": (
            "FRESH"
            if delivery_status == "READY_FULL"
            else s01.get("facts_status", "PARTIAL")
        ),
        "analytics_status": (
            "FRESH"
            if delivery_status == "READY_FULL"
            else s01.get("analytics_status", "DEGRADED")
        ),
        "root_failure": root_failure,
        "sections": {
            str(row.get("section_id") or ""): {
                "label": row.get("label"),
                "state": row.get("state"),
                "content": deepcopy(row.get("content") or {}),
            }
            for row in sections
        },
        "generated_at": datetime.now().astimezone().isoformat(),
        "lineage": {
            "runner_status": bundle.get("runner_status"),
            "planning_gw": bundle.get("planning_gw"),
        },
        "supersedes": None,
    }


def validate_serving_snapshot(snapshot: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if str(snapshot.get("delivery_status") or "") not in DELIVERY_STATES:
        failures.append("INVALID_DELIVERY_STATUS")
    sections = snapshot.get("sections")
    if not isinstance(sections, Mapping) or list(sections) != [
        section_id for section_id, _ in CANONICAL_DEEP_SECTIONS
    ]:
        failures.append("SERVING_SECTION_ORDER_OR_COUNT")
    if not str(snapshot.get("decision") or "").strip():
        failures.append("SERVING_DECISION_MISSING")
    if str(snapshot.get("delivery_status") or "") == "READY_DEGRADED" and not str(
        snapshot.get("root_failure") or ""
    ).strip():
        failures.append("DEGRADED_ROOT_FAILURE_MISSING")
    return failures


def write_serving_artifacts(
    *,
    bundle: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Finalize canonical + serving files with atomic local replacement."""
    delivery_status = (
        "READY_FULL"
        if str(bundle.get("runner_status") or "").upper() == "PASS"
        else "READY_DEGRADED"
    )
    bundle["delivery_status"] = delivery_status
    bundle["occurrence_id"] = str(
        bundle.get("occurrence_id")
        or f"{bundle.get('report_mode')}|{bundle.get('report_slot')}"
    )
    execution = dict(bundle.get("execution_proof") or {})
    execution["delivery_status"] = delivery_status
    bundle["execution_proof"] = execution

    snapshot = build_serving_snapshot(bundle)
    failures = validate_serving_snapshot(snapshot)
    if str(bundle.get("report_mode") or "").upper() == "DEEP":
        failures.extend(validate_delivery_bundle(bundle))
    if failures:
        raise DeliveryReliabilityError(
            "serving snapshot validation failed: " + ",".join(dict.fromkeys(failures))
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "report_bundle.json": json.dumps(
            bundle, indent=2, ensure_ascii=False, default=str
        ) + "\n",
        "execution_proof.json": json.dumps(
            execution, indent=2, ensure_ascii=False, default=str
        ) + "\n",
        "serving_report.json": json.dumps(
            snapshot, indent=2, ensure_ascii=False, default=str
        ) + "\n",
        "serving_report.md": str(bundle.get("visible_body") or ""),
        "delivery_status.json": json.dumps(
            {
                "schema_version": 1,
                "occurrence_id": snapshot["occurrence_id"],
                "report_slot": snapshot["report_slot"],
                "report_mode": snapshot["report_mode"],
                "delivery_status": snapshot["delivery_status"],
                "root_failure": snapshot.get("root_failure"),
                "generated_at": snapshot["generated_at"],
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
    }
    for name, payload in artifacts.items():
        target = output_dir / name
        tmp = target.with_name(f".{target.name}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(target)
    return snapshot
