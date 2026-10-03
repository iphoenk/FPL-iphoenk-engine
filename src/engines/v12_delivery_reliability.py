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
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence

from src.engines.v12_section_resolver import resolve_section, validate_resolved_sections


CANONICAL_DEEP_BASE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("S01", "DECISION / CURRENT STATUS"),
    ("S02", "OUR15"),
    ("S03", "DECISION DELTA"),
    ("S04", "MATERIAL DEVELOPMENTS / CHANGES"),
    ("S05", "FIXTURES / REST / CONDITIONS"),
    ("S06", "FORMATION / XI / BENCH"),
    ("S06B", "XI BATTLE"),
    ("S07", "LINEUP RISK / AUTOSUB LOGIC"),
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
    ("S17", "SOURCE HEALTH / FRESHNESS / LINEAGE"),
    ("S18", "ACTION BOARD"),
    ("S19", "FINAL JUDGEMENT"),
)
CANONICAL_S16B_SECTION = ("S16B", "POST-MATCH REVIEW")
_S16B_INSERT_INDEX = next(
    index
    for index, (section_id, _) in enumerate(CANONICAL_DEEP_BASE_SECTIONS)
    if section_id == "S17"
)


def canonical_deep_sections(*, s16b_due: bool) -> tuple[tuple[str, str], ...]:
    if not s16b_due:
        return CANONICAL_DEEP_BASE_SECTIONS
    return tuple(
        list(CANONICAL_DEEP_BASE_SECTIONS[:_S16B_INSERT_INDEX])
        + [CANONICAL_S16B_SECTION]
        + list(CANONICAL_DEEP_BASE_SECTIONS[_S16B_INSERT_INDEX:])
    )


# Backward-compatible import name now means the normal 22-section DEEP backbone.
CANONICAL_DEEP_SECTIONS = CANONICAL_DEEP_BASE_SECTIONS

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
    report_prefetch_artifacts = [
        row for row in latest.get("artifacts") or []
        if isinstance(row, Mapping)
        and str(row.get("artifact_class") or "").upper() == "REPORT_PREFETCH"
    ]
    occurrence_publication_proven = bool(
        report_prefetch_artifacts
        and all(
            str(row.get("status") or "").upper() == "PROVEN"
            and bool(row.get("publication_run_id"))
            and bool(row.get("published_at"))
            for row in report_prefetch_artifacts
        )
    )
    checks = {
        "report_slot_timezone_aware": requested is not None,
        "report_kind_full_master": str(latest.get("report_kind") or "") == "full_master",
        "target_report_slot_match": _same_instant(target, requested),
        "report_prefetch_run_id_available": bool(latest.get("report_prefetch_run_id")),
        "occurrence_publication_proven": occurrence_publication_proven,
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
        # Age is observability only. Exact occurrence identity plus the governed
        # fresh_for_target_report flag are the terminality authority. A hard
        # age threshold here could reject a valid T-15 precompute because of
        # normal release/publish jitter.
        checks["same_occurrence_age_observed"] = True

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


def _previous_visible_bundle_from_directory(
    directory: Path | None,
    *,
    current_report_slot: str,
) -> dict[str, Any] | None:
    """Load governed previous presentation state without scanning history."""
    if directory is None:
        return None
    legal_catalogs = {
        tuple(section_id for section_id, _ in canonical_deep_sections(s16b_due=False)),
        tuple(section_id for section_id, _ in canonical_deep_sections(s16b_due=True)),
    }
    try:
        current_dt = datetime.fromisoformat(
            str(current_report_slot or "").replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if current_dt.tzinfo is None or current_dt.utcoffset() is None:
        return None

    def strictly_older(value: Any) -> bool:
        try:
            previous_dt = datetime.fromisoformat(
                str(value or "").replace("Z", "+00:00")
            )
        except ValueError:
            return False
        return bool(
            previous_dt.tzinfo is not None
            and previous_dt.utcoffset() is not None
            and previous_dt < current_dt
        )

    compact = _read_json(directory / "previous_deep_baseline.json", None)
    if isinstance(compact, Mapping):
        sections = compact.get("sections")
        actual_ids = tuple(str(value) for value in compact.get("section_ids") or [])
        valid = bool(
            str(compact.get("artifact_kind") or "")
            == "V12_PREVIOUS_DEEP_BASELINE"
            and str(compact.get("report_mode") or "").upper() == "DEEP"
            and str(compact.get("delivery_status") or "").upper() == "READY_FULL"
            and str(compact.get("runner_status") or "").upper() == "PASS"
            and str(compact.get("pre_render_status") or "").upper() == "PASS"
            and str(compact.get("post_render_status") or "").upper() == "PASS"
            and str(compact.get("human_facing_status") or "").upper() == "PASS"
            and compact.get("math_recomputed") is False
            and strictly_older(compact.get("report_slot"))
            and actual_ids in legal_catalogs
            and isinstance(sections, Mapping)
            and tuple(sections) == actual_ids
        )
        if valid:
            return {
                "report_mode": "DEEP",
                "report_slot": compact.get("report_slot"),
                "occurrence_id": compact.get("occurrence_id"),
                "planning_gw": compact.get("planning_gw"),
                "canonical_bundle_sha256": compact.get(
                    "canonical_bundle_sha256"
                ),
                "canonical_body_sha256": compact.get(
                    "canonical_body_sha256"
                ),
                "math_recomputed": False,
                "report": {
                    "mode": "DEEP",
                    "sections": [
                        {
                            "section_id": section_id,
                            **deepcopy(dict(sections[section_id])),
                        }
                        for section_id in actual_ids
                    ],
                },
                "s16b_delivery_state": deepcopy(
                    compact.get("s16b_delivery_state") or {}
                ),
            }
        return None

    serving = _read_json(directory / "serving_report.json", None)
    digest = _read_json(directory / "deep.json", None)
    if isinstance(serving, Mapping) and isinstance(digest, Mapping):
        sections = serving.get("sections")
        actual_ids = tuple(sections) if isinstance(sections, Mapping) else ()
        valid = bool(
            str(serving.get("report_mode") or "").upper() == "DEEP"
            and str(serving.get("delivery_status") or "").upper() == "READY_FULL"
            and str(digest.get("report_mode") or "").upper() == "DEEP"
            and str(digest.get("runner_status") or "").upper() == "PASS"
            and str(digest.get("pre_render_status") or "").upper() == "PASS"
            and str(digest.get("post_render_status") or "").upper() == "PASS"
            and str(digest.get("human_facing_status") or "").upper() == "PASS"
            and digest.get("math_recomputed") is False
            and strictly_older(serving.get("report_slot"))
            and str(serving.get("report_slot") or "")
            == str(digest.get("report_slot") or "")
            and isinstance(sections, Mapping)
            and actual_ids in legal_catalogs
        )
        if valid:
            return {
                "report_mode": "DEEP",
                "report_slot": serving.get("report_slot"),
                "occurrence_id": serving.get("occurrence_id"),
                "planning_gw": serving.get("GW"),
                "canonical_bundle_sha256": digest.get(
                    "canonical_bundle_sha256"
                ),
                "canonical_body_sha256": digest.get(
                    "canonical_body_sha256"
                ),
                "math_recomputed": False,
                "report": {
                    "mode": "DEEP",
                    "sections": [
                        {
                            "section_id": section_id,
                            **deepcopy(dict(sections[section_id])),
                        }
                        for section_id in actual_ids
                    ],
                },
                "s16b_delivery_state": deepcopy(
                    serving.get("s16b_delivery_state") or {}
                ),
            }
        return None

    legacy = _read_json(directory / "report_bundle.json", None)
    if (
        isinstance(legacy, Mapping)
        and strictly_older(legacy.get("report_slot"))
    ):
        return dict(legacy)
    return None


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
    prior_candidate = (
        {"state": "DEGRADED", "content": dict(prior_content)}
        if prior_content
        else None
    )
    prior_occurrence = (
        str((prior_content or {}).get("prior_source_occurrence") or "").strip()
        or None
    )
    return resolve_section(
        section_id=section_id,
        label=label,
        prior=prior_candidate,
        prior_source_occurrence=prior_occurrence,
        unavailable_reason=root_failure,
    )


def assemble_degraded_deep_report(
    *,
    runtime_root: Path,
    report_slot: str,
    output_dir: Path,
    root_failure: str,
    root_stage: str | None = None,
    previous_visible_deep_dir: Path | None = None,
    s16b_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one usable conditional DEEP report without inventing analytics."""
    root_stage = str(
        root_stage
        or (
            "V6_REPORT_PREFETCH_BINDING"
            if root_failure == "PREFETCH_NOT_TERMINAL"
            else "ANALYTICS_PIPELINE"
        )
    )
    previous_bundle = _previous_visible_bundle_from_directory(
        previous_visible_deep_dir,
        current_report_slot=report_slot,
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
    lifecycle = dict(s16b_context or {})
    s16b_due = lifecycle.get("s16b_due") is True
    catalog = canonical_deep_sections(s16b_due=s16b_due)

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
        for section_id, label in catalog
    ]
    by_id = {row["section_id"]: row for row in sections}

    by_id["S01"] = {
        "section_id": "S01",
        "label": "DECISION / CURRENT STATUS",
        "state": "DEGRADED",
        "degradation_reason": root_failure,
        "source_state": "CURRENT",
        "content": {
            "presentation_status": "CURRENT",
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
        "source_state": "UNAVAILABLE",
        "content": {
            "presentation_status": "UNAVAILABLE",
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
        "source_state": "CURRENT" if facts_status == "FRESH" else "UNAVAILABLE",
        "content": {
            "presentation_status": "CURRENT" if facts_status == "FRESH" else "UNAVAILABLE",
            "fact_layer": facts_status,
            "facts_generated_at": facts_generated_at,
            "news_summary": (
                "CURRENT FACT PLANE AVAILABLE; MATERIAL NEWS EXTRACTION NOT RUN"
                if facts_status == "FRESH"
                else "NO MATERIAL NEW EXTERNAL NEWS SUPPORTABLE"
            ),
            "material_news": [],
            "news_groups": {
                "OUR15": [],
                "WATCHLIST / TARGETS": [],
                "TEAM / TACTICAL": [],
                "OTHER MATERIAL": [],
            },
            "model_developments": [],
            "decision_consequence": {
                "transfer_state": "UNAVAILABLE",
                "xi_state": "DEGRADED",
                "captain_state": "DEGRADED",
                "price_state": "UNAVAILABLE",
                "news_self_authorizes_act": False,
                "news_observation_is_model_update": False,
                "model_numbers_mutated_here": False,
                "optimizer_authority_remains_s14": True,
            },
            "source_policy": {
                "allowed_source_classes": [
                    "OFFICIAL",
                    "RELIABLE_REPORT",
                    "MULTIPLE_CREDIBLE_REPORTS",
                    "RUMOR / UNVERIFIED",
                    "MODEL_SIGNAL",
                    "INFERENCE",
                ],
                "rumor_is_fact": False,
                "rumor_may_authorize_act": False,
                "news_observation_equals_model_update": False,
            },
            "model_update": "NOT_RUN",
            "empty_is_truthful": True,
        },
    }
    by_id["S15"] = {
        "section_id": "S15",
        "label": "EVIDENCE QUALITY",
        "state": "DEGRADED",
        "degradation_reason": root_failure,
        "source_state": "CURRENT",
        "content": {
            "presentation_status": "CURRENT",
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
    if s16b_due:
        proven_review = lifecycle.get("post_match_review")
        if isinstance(proven_review, Mapping) and proven_review:
            s16b_content = deepcopy(dict(proven_review))
            s16b_content["presentation_status"] = "CURRENT"
            s16b_content["degradation_reason"] = root_failure
        else:
            s16b_content = {
                "presentation_status": "CURRENT",
                "gw": lifecycle.get("completed_gw"),
                "fixtures_expected": (
                    (lifecycle.get("gw_completion") or {}).get(
                        "expected_fixture_count"
                    )
                ),
                "fixtures_reviewed": 0,
                "unique_fixture_count": 0,
                "duplicate_fixture_count": 0,
                "match_by_match_review": [],
                "after_gw_reassessment": {
                    "owned15_review": [],
                    "watchlist_delta": [],
                    "summary": {},
                    "status": "DEGRADED",
                },
                "full_universe_denominator": "UNAVAILABLE",
                "degradation_reason": root_failure,
            }
        by_id["S16B"] = {
            "section_id": "S16B",
            "label": "POST-MATCH REVIEW",
            "state": "DEGRADED",
            "degradation_reason": root_failure,
            "source_state": "CURRENT",
            "content": s16b_content,
        }

    by_id["S17"] = {
        "section_id": "S17",
        "label": "SOURCE HEALTH / FRESHNESS / LINEAGE",
        "state": "DEGRADED",
        "degradation_reason": root_failure,
        "source_state": "CURRENT",
        "content": {
            "presentation_status": "CURRENT",
            "root_failure": root_failure,
            "root_stage": root_stage,
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
        "source_state": "CURRENT",
        "content": {
            "presentation_status": "CURRENT",
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
        "source_state": "CURRENT",
        "content": {
            "presentation_status": "CURRENT",
            "decision": "WAIT",
            "final_judgement": (
                "WAIT. Current facts may still be usable, but fresh analytical "
                "proof is incomplete. Do not act on historical model output as if it were current."
            ),
            "reversal_trigger": "same-occurrence fresh analytics validated",
        },
    }

    ordered = [by_id[section_id] for section_id, _ in catalog]
    resolver_failures = validate_resolved_sections(ordered)
    if resolver_failures:
        raise RuntimeError(
            "DEGRADED_SECTION_RESOLUTION_INVALID: " + ",".join(resolver_failures)
        )
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
            "stage": root_stage,
            "status": "FAILED",
            "required": True,
            "error_class": "DELIVERY_ROOT_FAILURE",
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
        if stage != root_stage
    ]

    report = {
        "mode": "DEEP",
        "sections": ordered,
        "numbered_headings": 19,
        "rendered_blocks_including_suffix_sections": len(ordered),
        "rendered_blocks_including_15B": len(ordered),
        "s16b_due": s16b_due,
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
        "canonical_expected_section_ids": [x[0] for x in catalog],
        "s16b_due": s16b_due,
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
        "s16b_due": s16b_due,
        "s16b_context": lifecycle,
        "s16b_delivery_state": dict(
            lifecycle.get("delivery_state_after")
            or lifecycle.get("delivery_state_before")
            or (previous_bundle or {}).get("s16b_delivery_state")
            or {}
        ),
        "stage_ledger": stage_ledger,
        "section_manifest": [
            {"section_id": row["section_id"], "status": row["state"]}
            for row in ordered
        ],
        "pre_render_qa": {
            "status": "DEGRADED_PRESENTATION_PASS",
            "section_count": len(ordered),
            "decision_first": True,
        },
        "post_render_qa": {
            "status": "DEGRADED_PRESENTATION_PASS",
            "section_count": len(ordered),
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
    s16b_due = bundle.get("s16b_due") is True
    expected = [
        section_id
        for section_id, _ in canonical_deep_sections(s16b_due=s16b_due)
    ]
    if ids != expected:
        failures.append("SECTION_ORDER_OR_COUNT")
    if len(sections) != len(expected):
        failures.append(f"SECTION_COUNT_NOT_EXPECTED:{len(sections)}/{len(expected)}")
    if not sections or sections[0].get("section_id") != "S01":
        failures.append("DECISION_NOT_FIRST")
    if not sections or sections[-1].get("section_id") != "S19":
        failures.append("FINAL_JUDGEMENT_NOT_LAST")
    s01 = next((row for row in sections if row.get("section_id") == "S01"), {})
    s19 = next((row for row in sections if row.get("section_id") == "S19"), {})
    s01_content = dict(s01.get("content") or {})
    if not str(
        s01_content.get("decision")
        or s01_content.get("operational_state")
        or s01_content.get("primary_decision")
        or ""
    ).strip():
        failures.append("DECISION_MISSING")
    if not str((s19.get("content") or {}).get("final_judgement") or "").strip():
        failures.append("FINAL_JUDGEMENT_MISSING")
    root_failures = [
        row
        for row in bundle.get("stage_ledger") or []
        if isinstance(row, Mapping) and str(row.get("status") or "").upper() == "FAILED"
    ]
    if (
        str(bundle.get("delivery_status") or "") == "READY_DEGRADED"
        and str((bundle.get("execution_proof") or {}).get("runner_state") or "")
        == "BLOCKED_UPSTREAM"
    ):
        if len(root_failures) != 1:
            failures.append("FALLBACK_ROOT_FAILURE_COUNT_NOT_ONE")
        elif not str(root_failures[0].get("stage") or "").strip():
            failures.append("ROOT_FAILURE_STAGE_MISSING")
    if not str(bundle.get("visible_body") or "").strip():
        failures.append("VISIBLE_BODY_EMPTY")
    return failures


def build_occurrence_state(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Materialize one occurrence identity and its fail-operational state path."""
    occurrence_id = str(
        bundle.get("occurrence_id")
        or f"{bundle.get('report_mode')}|{bundle.get('report_slot')}"
    )
    delivery_status = str(bundle.get("delivery_status") or "")
    runner_status = str(bundle.get("runner_status") or "").upper()
    execution = dict(bundle.get("execution_proof") or {})
    now = datetime.now().astimezone().isoformat()

    if delivery_status == "READY_FULL" or runner_status == "PASS":
        states = [
            "CREATED",
            "FACTS_REQUESTED",
            "FACTS_READY",
            "ANALYTICS_RUNNING",
            "ANALYTICS_READY",
            "RENDERING",
            "PUBLISHED_FULL",
        ]
    else:
        states = [
            "CREATED",
            "FACTS_REQUESTED",
            "BLOCKED_UPSTREAM",
            "ANALYTICS_FAILED",
            "FALLBACK_ASSEMBLY",
            "RENDERING",
            "PUBLISHED_DEGRADED",
        ]

    return {
        "schema_version": 1,
        "occurrence_id": occurrence_id,
        "report_slot": bundle.get("report_slot"),
        "report_mode": bundle.get("report_mode"),
        "current_state": states[-1],
        "delivery_status": delivery_status,
        "root_failure": bundle.get("root_failure"),
        "root_stage": execution.get("root_stage"),
        "transitions": [
            {
                "state": state,
                "at": now,
                "lineage": {
                    "runner_status": runner_status or "UNKNOWN",
                    "report_slot": bundle.get("report_slot"),
                },
            }
            for state in states
        ],
        "precompute_observability": {
            "PRECOMPUTE_REQUESTED": execution.get(
                "precompute_requested", "UNAVAILABLE"
            ),
            "PREFETCH_TERMINAL": (
                True
                if runner_status == "PASS"
                else execution.get("prefetch_terminal", False)
            ),
            "WARM_STATUS": execution.get("warm_status", "UNAVAILABLE"),
            "FREEZE_STATUS": execution.get("freeze_status", "UNAVAILABLE"),
        },
        "idempotent_occurrence_identity": True,
        "duplicate_user_report_allowed": False,
    }


def build_presentation_qa_manifest(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Machine-readable decision-first presentation acceptance."""
    sections = [
        dict(row)
        for row in ((bundle.get("report") or {}).get("sections") or [])
        if isinstance(row, Mapping)
    ]
    by_id = {str(row.get("section_id") or ""): row for row in sections}

    def state(section_id: str) -> str:
        return str((by_id.get(section_id) or {}).get("state") or "").upper()

    def content(section_id: str) -> dict[str, Any]:
        value = (by_id.get(section_id) or {}).get("content") or {}
        return dict(value) if isinstance(value, Mapping) else {}

    s02_rows = [
        row for row in content("S02").get("rows") or []
        if isinstance(row, Mapping)
    ]
    s11 = content("S11")
    s11_rows = [
        row for row in (s11.get("scanner20") or s11.get("rows") or [])
        if isinstance(row, Mapping)
    ]
    s12_rows = [
        row for row in content("S12").get("rows") or []
        if isinstance(row, Mapping)
    ]
    s13_rows = [
        row for row in content("S13").get("rows") or []
        if isinstance(row, Mapping)
    ]
    s16_rows = [
        row for row in content("S16").get("rows") or []
        if isinstance(row, Mapping)
    ]

    exact_ids = [
        section_id
        for section_id, _ in canonical_deep_sections(
            s16b_due=bundle.get("s16b_due") is True
        )
    ]
    actual_ids = [str(row.get("section_id") or "") for row in sections]
    prior_mislabelled = False
    for row in sections:
        payload = row.get("content") or {}
        if not isinstance(payload, Mapping):
            continue
        if str(payload.get("presentation_status") or "").upper() == "PRIOR":
            if not payload.get("prior_source_occurrence"):
                prior_mislabelled = True

    stage_ledger = [
        dict(row) for row in bundle.get("stage_ledger") or []
        if isinstance(row, Mapping)
    ]
    false_failed = [
        row for row in stage_ledger
        if str(row.get("status") or "").upper() == "FAILED"
        and str(row.get("error") or "").strip() == ""
        and str(row.get("error_class") or "").strip() == ""
    ]

    def rank20_eta_contract(rows: list[Mapping[str, Any]], section_state: str) -> bool:
        if section_state != "COMPLETE":
            return True
        if len(rows) != 20:
            return False
        for row in rows:
            eta = (
                row.get("eta_human")
                or row.get("estimated_change_window")
                or row.get("predicted_change_at")
                or row.get("date_state")
            )
            if eta in (None, ""):
                return False
        return True

    s11_exact = (
        state("S11") != "COMPLETE"
        or (
            len(s11_rows) == 20
            and len({
                int(row.get("element_id") or row.get("element") or 0)
                for row in s11_rows
            }) == 20
        )
    )
    all15_ok = (
        state("S16") != "COMPLETE"
        or len({
            int(row.get("element_id") or 0)
            for row in s16_rows
            if row.get("element_id") is not None
        }) == 15
    )
    our15_ok = (
        state("S02") != "COMPLETE"
        or len({
            int(row.get("element_id") or 0)
            for row in s02_rows
            if row.get("element_id") is not None
        }) == 15
    )

    return {
        "schema_version": 1,
        "section_count": len(sections),
        "expected_section_count": len(exact_ids),
        "s16b_due": bundle.get("s16b_due") is True,
        "section_order_exact": actual_ids == exact_ids,
        "our15_count": len(s02_rows),
        "our15_complete_when_claimed": our15_ok,
        "watchlist_state": state("S11") or "UNAVAILABLE",
        "watchlist_exact20_when_claimed": s11_exact,
        "rise20_state": state("S12") or "UNAVAILABLE",
        "rise20_eta_contract": rank20_eta_contract(s12_rows, state("S12")),
        "fall20_state": state("S13") or "UNAVAILABLE",
        "fall20_eta_contract": rank20_eta_contract(s13_rows, state("S13")),
        "all15_count": len(s16_rows),
        "all15_complete_when_claimed": all15_ok,
        "root_failure_count": sum(
            1 for row in stage_ledger
            if str(row.get("status") or "").upper() == "FAILED"
        ),
        "downstream_false_failures": len(false_failed),
        "prior_without_source_occurrence": prior_mislabelled,
        "decision_first": bool(sections and sections[0].get("section_id") == "S01"),
        "technical_health_in_s17": "S17" in actual_ids,
        "final_judgement_present": bool(
            str(content("S19").get("final_judgement") or "").strip()
            or str(content("S19").get("summary") or "").strip()
            or state("S19") == "COMPLETE"
        ),
        "visible_report_body_non_empty": bool(
            str(bundle.get("visible_body") or "").strip()
        ),
    }


def validate_presentation_qa_manifest(manifest: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    expected_true = (
        "section_order_exact",
        "our15_complete_when_claimed",
        "watchlist_exact20_when_claimed",
        "rise20_eta_contract",
        "fall20_eta_contract",
        "all15_complete_when_claimed",
        "decision_first",
        "technical_health_in_s17",
        "final_judgement_present",
        "visible_report_body_non_empty",
    )
    for key in expected_true:
        if manifest.get(key) is not True:
            failures.append(key.upper())
    if int(manifest.get("section_count") or 0) != int(
        manifest.get("expected_section_count") or 0
    ):
        failures.append("SECTION_COUNT_NOT_EXPECTED")
    if int(manifest.get("root_failure_count") or 0) > 1:
        failures.append("ROOT_FAILURE_COUNT_GT_1")
    if int(manifest.get("downstream_false_failures") or 0) != 0:
        failures.append("DOWNSTREAM_FALSE_FAILURES")
    if manifest.get("prior_without_source_occurrence") is True:
        failures.append("PRIOR_WITHOUT_SOURCE_OCCURRENCE")
    return failures


SERVING_MAX_SERIALIZED_BYTES = 5 * 1024 * 1024

_SERVING_PROVENANCE_KEYS: tuple[str, ...] = (
    "presentation_status",
    "prior_source_occurrence",
    "prior_reason",
    "authoritative_binding",
)

_SERVING_SECTION_KEYS: dict[str, tuple[str, ...]] = {
    "S01": (
        "decision_dashboard", "operational_state", "planning_gw",
        "primary_decision", "reason", "key_decision_driver",
        "current_blockers", "current_planning_gw",
    ),
    "S02": ("rows", "current15_authority"),
    "S03": ("decision_delta",),
    "S04": (
        "news_summary", "material_news", "news_groups",
        "model_developments", "decision_consequence", "source_policy",
        "changes", "stagec_universe_intelligence",
    ),
    "S05": (
        "state", "planning_gw", "gw_topology", "period_flags",
        "competition_coverage", "player_workload", "weather",
        "workload_feeds_p1_1_review_only", "static_fatigue_penalty_applied",
        "weather_mutates_football_model", "dgw_cross_fixture_covariance_claimed",
        "degradation_reason", "fixture_swing",
    ),
    "S06": (
        "formation", "starting_xi", "bench", "captain", "vice_captain",
        "lineup_score", "formation_comparison", "xi_base_xpts",
        "captain_adjusted_xpts", "lineup_route_utility", "score_semantics",
        "bgw_context", "bgw_lineup_review_required",
    ),
    "S06B": (
        "battle_rows", "battles", "empty_is_truthful", "current_winner",
        "battle_classification", "primary_alternative", "reason", "battle_summary",
    ),
    "S07": (
        "risk_rows", "lineup_implication", "bench_gk", "autosub_order",
        "empty_is_truthful",
    ),
    "S08": (
        "decision_state", "captain", "vice_captain", "captain_frontier",
        "captain_safe_pool", "candidate_universe_proof",
        "football_baseline_first", "mini_league_overlay_second",
        "mini_league_override_applied", "near_tie_authority",
        "reconciliation_reason", "authority", "raw_mean_is_not_sole_authority",
    ),
    "S09": (
        "chip", "chip_ledger", "chip_ledger_authority",
        "remaining_chip_set_required",
        "free_hit_optimization_required_when_fh_only", "considered_now",
        "horizon", "trigger", "hold_reason", "bgw_context",
        "bgw_chip_review_required",
    ),
    "S10": (
        "state", "available_count", "expected_count", "rows",
        "identity_complete", "predictor_complete_count",
        "date_state_complete_count", "degradation_reason",
        "price_alone_may_create_act", "bank", "bank_status",
        "sell_value_status",
    ),
    "S11": (
        "state", "available_count", "expected_count", "scanner20",
        "actionable_watchlist", "actionable_count", "position_counts",
        "universe_authority", "full_eligible_universe_scanned_count",
        "owned_excluded", "degradation_reason", "macro_weights",
        "position_formulae", "scope",
    ),
    "S12": (
        "state", "available_count", "expected_count", "rows",
        "predictor_health", "degradation_reason", "artifact_adapter",
        "sort_contract", "visible_contract_fields",
        "existing_eta_threshold_source", "predictor_payload_hash",
        "date_state_complete_count", "expected_change_date_count",
        "no_crossing_count",
    ),
    "S13": (
        "state", "available_count", "expected_count", "rows",
        "predictor_health", "degradation_reason", "artifact_adapter",
        "sort_contract", "visible_contract_fields",
        "existing_eta_threshold_source", "predictor_payload_hash",
        "date_state_complete_count", "expected_change_date_count",
        "no_crossing_count",
    ),
    "S14": (
        "universe_scan", "package_routes", "frontier",
        "package_search_proof", "funded_search_proof", "package_search_scope",
        "package_universe_challengers", "football_frontier_status",
        "execution_economics_status", "execution_economics_authority",
        "material_route_selection", "monte_carlo", "decision",
        "position_mechanisms", "mini_league_overlay", "bgw_context",
        "bgw_frontier_review_required", "bgw_is_context_not_second_optimizer",
        "mathematical_decision_stack",
    ),
    "S14B": (
        "squad_classification", "staging_rows", "free_transfers",
        "free_transfers_status", "ft_authority", "ft_saving_plan",
        "order_of_transfers", "budget_dependency", "price_dependency",
        "player_dependency", "contingency", "target_formation",
        "roadmap_is_not_transfer_commitment",
        "roadmap_reoptimizes_on_new_evidence", "bgw_context",
        "bgw_reoptimization_trigger",
    ),
    "S15": ("evidence_quality", "model_execution"),
    "S15B": (
        "schema_version", "snapshot_id", "league_id", "league_name",
        "league_kind", "planning_gw", "generated_at", "coverage_state",
        "league_scope", "expected_manager_count", "standings_manager_count",
        "submitted_picks_available_count", "submitted_picks_missing_count",
        "missing_entry_ids", "rival_exposure_denominator",
        "denominator_fingerprint", "eo_supported", "exposures", "chip_counts",
        "current_league_context", "provenance", "downstream_overlay",
        "football_baseline_precedes_leverage", "protection_players",
        "differential_opportunities", "disclosed_picks_gw",
        "disclosed_picks_are_baseline_not_gw_forecast",
        "disclosed_picks_label", "rank_battle", "denominator_scopes",
        "league_full_composition", "league_full_composition_complete",
        "league_unique_player_count", "league_our15_exposure",
        "rivals_our15_exposure", "our15_rival_exposure",
        "competitive_window", "competitive_rivals",
        "competitive_our15_exposure", "competitive_window_threats",
        "captain_leverage", "strategy_implication", "report_contract",
    ),
    "S16": ("rows", "why_not_duplicate_of_our15"),
    "S16B": (
        "gw", "fixtures_expected", "fixtures_reviewed", "unique_fixture_count",
        "duplicate_fixture_count", "match_by_match_review",
        "after_gw_reassessment", "full_universe_denominator",
        "recency_weighting", "bayesian_update", "candidate_traceability",
        "fixture_ids_expected", "fixture_ids_reviewed",
    ),
    "S17": (
        "engine_data_status", "source_health", "auth_authority", "lineage",
        "delivery_provenance",
    ),
    "S18": (
        "action_board", "NOW", "NEXT", "TRIGGER TO ACT",
        "LATEST SAFE DECISION POINT", "COST OF WAITING",
        "ABORT / REVERSAL", "BEST ALTERNATIVE",
    ),
    "S19": ("final_judgement",),
}

_SERVING_ROW_KEYS: dict[str, tuple[str, ...]] = {
    "S02": (
        "element_id", "player", "name", "position", "club",
        "current_price", "selling_price", "opponent", "home_away",
        "availability", "p_available", "p_start", "xmins",
        "projection_1gw", "gw_plus_1", "projection_3gw", "three_gw",
        "projection_5gw", "five_gw", "tactical_role_label",
        "tactical_role", "tactical_score", "injury_rotation_warning",
        "price_relevance", "ownership_source",
    ),
    "S06": (
        "element", "element_id", "name", "player", "position",
        "p_start", "xmins", "xpts_mean", "selection_score",
    ),
    "S10": (
        "element_id", "name", "player", "current_price",
        "authenticated_sell_value", "predictor_direction",
        "predictor_progress", "predictor_projected_percent",
        "prediction_strength", "next_official_price_cycle_uk",
        "next_official_price_cycle_wib", "cycles_to_expected_change",
        "estimated_change_date_uk", "estimated_change_date_wib",
        "estimated_change_window", "eta_context", "eta_reason",
        "date_state", "evidence_timestamp", "source_age_minutes",
        "freshness", "confidence", "decision_implication",
    ),
    "S11": (
        "element_id", "element", "name", "position", "current_price",
        "xmins", "p_start", "p_dnp", "position_specific_evidence",
        "admission_gate", "football_score", "watchlist_action", "action",
        "predictor_direction", "predictor_progress", "delta_state",
        "delta", "movement",
    ),
    "S12": (
        "element_id", "player", "player_name", "current_price",
        "selected_by_percent", "ownership_percent", "direction",
        "official_or_provider_progress", "current_progress_percent",
        "projected_percent", "projection_offset_0_percent",
        "cycles_to_expected_change", "predicted_change_cycle",
        "estimated_change_at_wib", "predicted_change_at", "eta_context",
        "eta_human", "estimated_change_window", "impact_on_our_decision",
        "model_urgency", "confidence", "estimate_source", "source",
        "evidence_timestamp", "observed_at", "source_age_minutes",
        "freshness", "date_state", "delta_progress", "progress_delta",
        "delta_rank", "rank_delta", "velocity", "progress_velocity",
        "target_relevance", "raw_payload_hash",
    ),
    "S13": (
        "element_id", "player", "player_name", "current_price",
        "selected_by_percent", "ownership_percent", "direction",
        "official_or_provider_progress", "current_progress_percent",
        "projected_percent", "projection_offset_0_percent",
        "cycles_to_expected_change", "predicted_change_cycle",
        "estimated_change_at_wib", "predicted_change_at", "eta_context",
        "eta_human", "estimated_change_window", "impact_on_our_decision",
        "model_urgency", "confidence", "estimate_source", "source",
        "evidence_timestamp", "observed_at", "source_age_minutes",
        "freshness", "date_state", "delta_progress", "progress_delta",
        "delta_rank", "rank_delta", "velocity", "progress_velocity",
        "target_relevance", "raw_payload_hash",
    ),
    "S16": (
        "element_id", "player", "name", "availability", "p_available",
        "p_start", "xmins", "probabilities", "projection_1gw", "gw_plus_1",
        "projection_3gw", "three_gw", "projection_5gw", "five_gw",
        "underlying", "role_detail", "defensive_contribution",
        "workload_context", "fixture_detail", "bayesian_state",
        "main_upside", "main_risk", "mini_league_relevance",
        "action", "decision",
    ),
}

_SERVING_OVERLAY_KEYS: tuple[str, ...] = (
    "schema_version", "model_owner", "model_id", "planning_gw",
    "football_baseline", "league_context", "mini_league_evidence_provenance",
    "coverage", "risk_posture", "relevant_rival_exposure",
    "route_screening_summary", "adjusted_decision", "decision_delta",
    "reversal_triggers", "rank_probability_boundary", "governance",
    "status", "generated_at", "model_version", "feature_version",
    "parameter_version", "run_fingerprint", "output_fingerprint",
    "model_evidence_binding",
)


def _serving_pick(
    value: Mapping[str, Any] | None,
    keys: Sequence[str],
) -> dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    return {
        key: deepcopy(source[key])
        for key in keys
        if key in source
    }


def _serving_project_rows(
    rows: Any,
    keys: Sequence[str],
) -> list[dict[str, Any]]:
    return [
        _serving_pick(row, keys)
        for row in (rows or [])
        if isinstance(row, Mapping)
    ]


def _serving_project_s16b(content: dict[str, Any]) -> None:
    """Keep the bounded, human-relevant S16B package; never ship raw universe dumps."""
    compact_matches: list[dict[str, Any]] = []
    for raw in content.get("match_by_match_review") or []:
        if not isinstance(raw, Mapping):
            continue
        match = _serving_pick(
            raw,
            (
                "fixture_id", "result", "venue", "home_team", "away_team",
                "formation_system", "coach_pattern", "tactical_takeaways",
            ),
        )
        match["our_players"] = _serving_project_rows(
            raw.get("our_players"),
            (
                "element_id", "player", "starter_sub_unused", "minutes",
                "fpl_points", "position_role", "xg", "xa", "xgi", "shots",
                "shots_on_target", "box_touches", "key_passes",
                "chances_created", "big_chances", "set_pieces", "penalties",
                "defensive_contribution", "substitution_timing",
                "analytical_read",
            ),
        )
        match["watch_candidates"] = _serving_project_rows(
            raw.get("watch_candidates"),
            (
                "fixture_id", "player_id", "player", "evidence_reason",
                "role_observation", "underlying_observation", "minutes_evidence",
                "classification",
            ),
        )
        compact_matches.append(match)
    content["match_by_match_review"] = compact_matches

    reassessment = content.get("after_gw_reassessment")
    if not isinstance(reassessment, Mapping):
        return
    compact = _serving_pick(
        reassessment,
        ("summary", "full_universe_scan", "decision_implications"),
    )
    compact["owned15_review"] = _serving_project_rows(
        reassessment.get("owned15_review"),
        (
            "element_id", "player", "pre_gw", "gw_evidence", "post_gw",
            "classification", "evidence_classification", "role_change",
            "minutes_change", "consequence", "act_authority",
        ),
    )
    compact["watchlist_delta"] = _serving_project_rows(
        reassessment.get("watchlist_delta"),
        (
            "element_id", "player", "previous_rank", "current_rank",
            "movement_state", "state",
        ),
    )
    compact["new_watch_candidates"] = _serving_project_rows(
        reassessment.get("new_watch_candidates"),
        (
            "fixture_id", "player_id", "player", "evidence_reason",
            "role_observation", "underlying_observation", "minutes_evidence",
            "classification", "full_universe_outcome",
        ),
    )
    content["after_gw_reassessment"] = compact


def _serving_project_content(
    section_id: str,
    raw_content: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Allowlist only presentation-required fields for one client section."""
    keys = _SERVING_SECTION_KEYS.get(section_id, ())
    content = _serving_pick(
        raw_content,
        (*keys, *_SERVING_PROVENANCE_KEYS),
    )

    row_keys = _SERVING_ROW_KEYS.get(section_id)
    if row_keys and "rows" in content:
        content["rows"] = _serving_project_rows(content.get("rows"), row_keys)

    if section_id == "S06" and "starting_xi" in content:
        content["starting_xi"] = _serving_project_rows(
            content.get("starting_xi"),
            _SERVING_ROW_KEYS["S06"],
        )

    if section_id == "S11":
        for key in ("scanner20", "actionable_watchlist"):
            if key in content:
                content[key] = _serving_project_rows(
                    content.get(key),
                    _SERVING_ROW_KEYS["S11"],
                )

    if section_id == "S14":
        decision = content.get("decision")
        if isinstance(decision, Mapping):
            content["decision"] = _serving_pick(
                decision,
                (
                    "status", "model_owner", "decision_layer",
                    "selected_route_id", "operational_action", "reason",
                    "sequential_decision", "action_contract", "governance",
                ),
            )
        overlay = content.get("mini_league_overlay")
        if isinstance(overlay, Mapping):
            content["mini_league_overlay"] = _serving_pick(
                overlay,
                _SERVING_OVERLAY_KEYS,
            )

    if section_id == "S15B":
        overlay = content.get("downstream_overlay")
        if isinstance(overlay, Mapping):
            content["downstream_overlay"] = _serving_pick(
                overlay,
                _SERVING_OVERLAY_KEYS,
            )

    if section_id == "S16B":
        _serving_project_s16b(content)

    return content


def build_serving_snapshot(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Build the stable compact client contract from one canonical bundle."""
    sections = [
        dict(row)
        for row in ((bundle.get("report") or {}).get("sections") or [])
        if isinstance(row, Mapping)
    ]
    by_id = {str(row.get("section_id") or ""): row for row in sections}
    s01 = dict((by_id.get("S01") or {}).get("content") or {})
    s19 = dict((by_id.get("S19") or {}).get("content") or {})
    execution = dict(bundle.get("execution_proof") or {})
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
        or s01.get("primary_decision")
        or ((s19.get("final_judgement") or {}).get("decision")
            if isinstance(s19.get("final_judgement"), Mapping)
            else None)
        or "UNAVAILABLE"
    )
    facts_status = (
        "FRESH"
        if delivery_status == "READY_FULL"
        else s01.get("facts_status", "PARTIAL")
    )
    analytics_status = (
        "FRESH"
        if delivery_status == "READY_FULL"
        else s01.get("analytics_status", "DEGRADED")
    )
    section_states = {
        str(row.get("section_id") or ""): {
            "state": str(row.get("state") or "UNAVAILABLE"),
            "source_state": str(
                row.get("source_state")
                or ((row.get("content") or {}).get("presentation_status")
                    if isinstance(row.get("content"), Mapping) else "")
                or "UNAVAILABLE"
            ),
        }
        for row in sections
    }
    prefetch_binding = (
        dict(execution.get("report_prefetch_binding") or {})
        if isinstance(execution.get("report_prefetch_binding"), Mapping)
        else {}
    )
    freeze_time = (
        bundle.get("freeze_time")
        or execution.get("freeze_time")
        or execution.get("freeze_at")
        or "UNAVAILABLE"
    )
    planning_gw = bundle.get("planning_gw")
    return {
        "schema_version": 3,
        "occurrence_id": str(
            bundle.get("occurrence_id")
            or f"{bundle.get('report_mode')}|{bundle.get('report_slot')}"
        ),
        "report_slot": bundle.get("report_slot"),
        "report_mode": bundle.get("report_mode"),
        "s16b_due": bundle.get("s16b_due") is True,
        "s16b_delivery_state": deepcopy(bundle.get("s16b_delivery_state") or {}),
        "GW": planning_gw if planning_gw not in (None, 0, "") else "UNAVAILABLE",
        "delivery_status": delivery_status,
        "decision": decision,
        "facts_status": facts_status,
        "analytics_status": analytics_status,
        "freeze_time": freeze_time,
        "source_freshness": {
            "facts": facts_status,
            "analytics": analytics_status,
            "sections": {
                section_id: meta["source_state"]
                for section_id, meta in section_states.items()
            },
        },
        "section_states": section_states,
        "root_failure": root_failure,
        "sections": {
            str(row.get("section_id") or ""): {
                "label": row.get("label"),
                "state": row.get("state"),
                "source_state": row.get("source_state"),
                "degradation_reason": row.get("degradation_reason"),
                "available_count": row.get("available_count"),
                "expected_count": row.get("expected_count"),
                "content": _serving_project_content(
                    str(row.get("section_id") or ""),
                    row.get("content") if isinstance(row.get("content"), Mapping) else {},
                ),
            }
            for row in sections
        },
        "generated_at": datetime.now().astimezone().isoformat(),
        "lineage": {
            "runner_status": bundle.get("runner_status"),
            "planning_gw": planning_gw,
            "model_sha": execution.get("model_sha"),
            "runtime_sha": execution.get("runtime_sha"),
            "report_prefetch_run_id": prefetch_binding.get("report_prefetch_run_id"),
            "target_logical_report_slot": prefetch_binding.get(
                "target_logical_report_slot"
            ),
            "projection_contract": "V12_CLIENT_PRESENTATION_PROJECTION_V1",
            "canonical_heavy_bundle_retained": True,
        },
        "supersedes": bundle.get("supersedes") or execution.get("supersedes"),
    }


def validate_serving_snapshot(snapshot: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if str(snapshot.get("delivery_status") or "") not in DELIVERY_STATES:
        failures.append("INVALID_DELIVERY_STATUS")
    sections = snapshot.get("sections")
    expected_ids = [
        section_id
        for section_id, _ in canonical_deep_sections(
            s16b_due=snapshot.get("s16b_due") is True
        )
    ]
    if not isinstance(sections, Mapping) or list(sections) != expected_ids:
        failures.append("SERVING_SECTION_ORDER_OR_COUNT")
    if not str(snapshot.get("decision") or "").strip():
        failures.append("SERVING_DECISION_MISSING")
    if str(snapshot.get("delivery_status") or "") == "READY_DEGRADED" and not str(
        snapshot.get("root_failure") or ""
    ).strip():
        failures.append("DEGRADED_ROOT_FAILURE_MISSING")

    try:
        schema_version = int(snapshot.get("schema_version") or 1)
    except (TypeError, ValueError):
        schema_version = 1
    if schema_version >= 2:
        required = (
            "occurrence_id",
            "report_slot",
            "GW",
            "delivery_status",
            "decision",
            "facts_status",
            "analytics_status",
            "freeze_time",
            "source_freshness",
            "section_states",
            "lineage",
            "supersedes",
            "s16b_due",
            "s16b_delivery_state",
        )
        for key in required:
            if key not in snapshot:
                failures.append(f"SERVING_CLIENT_FIELD_MISSING:{key}")
        section_states = snapshot.get("section_states")
        if (
            not isinstance(section_states, Mapping)
            or list(section_states) != expected_ids
        ):
            failures.append("SERVING_SECTION_STATES_ORDER_OR_COUNT")
        freshness = snapshot.get("source_freshness")
        if not isinstance(freshness, Mapping):
            failures.append("SERVING_SOURCE_FRESHNESS_INVALID")
        else:
            freshness_sections = freshness.get("sections")
            if (
                not isinstance(freshness_sections, Mapping)
                or list(freshness_sections) != expected_ids
            ):
                failures.append("SERVING_SOURCE_FRESHNESS_SECTION_ORDER_OR_COUNT")
        lineage = snapshot.get("lineage")
        if not isinstance(lineage, Mapping):
            failures.append("SERVING_LINEAGE_INVALID")

    if schema_version >= 3 and isinstance(sections, Mapping):
        s01 = ((sections.get("S01") or {}).get("content") or {})
        s19 = ((sections.get("S19") or {}).get("content") or {})
        judgement = (
            (s19.get("final_judgement") or {})
            if isinstance(s19, Mapping)
            else {}
        )
        dashboard = (
            (s01.get("decision_dashboard") or {})
            if isinstance(s01, Mapping)
            else {}
        )
        s01_decision = str(
            (s01.get("operational_state") if isinstance(s01, Mapping) else None)
            or (dashboard.get("TRANSFER") if isinstance(dashboard, Mapping) else None)
            or ""
        ).upper()
        s19_decision = str(
            (judgement.get("decision") if isinstance(judgement, Mapping) else None)
            or ""
        ).upper()
        if s01_decision and s19_decision and s01_decision != s19_decision:
            failures.append("SERVING_S01_S19_DECISION_MISMATCH")

        serialized_size = len(
            json.dumps(
                snapshot,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        if serialized_size > SERVING_MAX_SERIALIZED_BYTES:
            failures.append(
                f"SERVING_SIZE_EXCEEDS_CEILING:{serialized_size}:"
                f"{SERVING_MAX_SERIALIZED_BYTES}"
            )

        s11 = ((sections.get("S11") or {}).get("content") or {})
        scanner20 = (
            s11.get("scanner20")
            if isinstance(s11, Mapping)
            else None
        )
        if (
            str((s11 or {}).get("state") or "").upper() == "COMPLETE"
            and isinstance(scanner20, list)
            and len(scanner20) != 20
        ):
            failures.append("SERVING_S11_COMPLETE_NOT_EXACT_20")

        for section_id in ("S14", "S15B"):
            content = ((sections.get(section_id) or {}).get("content") or {})
            if not isinstance(content, Mapping):
                continue
            overlay = (
                content.get("mini_league_overlay")
                if section_id == "S14"
                else content.get("downstream_overlay")
            )
            if isinstance(overlay, Mapping) and "route_overlays" in overlay:
                failures.append(f"SERVING_HEAVY_FIELD_LEAK:{section_id}:route_overlays")
        s14 = ((sections.get("S14") or {}).get("content") or {})
        decision_payload = (
            s14.get("decision")
            if isinstance(s14, Mapping)
            else None
        )
        if isinstance(decision_payload, Mapping):
            for heavy_key in ("routes", "monte_carlo"):
                if heavy_key in decision_payload:
                    failures.append(
                        f"SERVING_HEAVY_FIELD_LEAK:S14.decision:{heavy_key}"
                    )
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
    if delivery_status == "READY_DEGRADED" and not str(
        bundle.get("root_failure") or ""
    ).strip():
        bundle["root_failure"] = "ANALYTICS_INCOMPLETE"
    bundle["occurrence_id"] = str(
        bundle.get("occurrence_id")
        or f"{bundle.get('report_mode')}|{bundle.get('report_slot')}"
    )
    execution = dict(bundle.get("execution_proof") or {})
    execution["delivery_status"] = delivery_status
    if delivery_status == "READY_DEGRADED":
        execution["root_failure"] = bundle.get("root_failure")
    bundle["execution_proof"] = execution

    # Delivery/QA/privacy are technical provenance and belong in S17, not
    # HEADER or S15. Finalize them only after delivery status is known, then
    # re-render the same canonical decision payload without recomputation.
    if str(bundle.get("report_mode") or "").upper() == "DEEP":
        report = dict(bundle.get("report") or {})
        report["reader_report_status"] = delivery_status
        report["report_slot"] = bundle.get("report_slot")
        report["planning_gw"] = bundle.get("planning_gw")
        sections = [
            dict(row)
            for row in report.get("sections") or []
            if isinstance(row, Mapping)
        ]
        qa_states = (
            str((bundle.get("pre_render_qa") or {}).get("status") or "").upper(),
            str((bundle.get("post_render_qa") or {}).get("status") or "").upper(),
            str((bundle.get("human_facing_qa") or {}).get("status") or "").upper(),
        )
        qa_pass = all(value == "PASS" for value in qa_states)
        for row in sections:
            if str(row.get("section_id") or "").upper() != "S17":
                continue
            content = dict(row.get("content") or {})
            content["delivery_provenance"] = {
                "private_delivery": (
                    "🟢 PASS · READY_FULL"
                    if delivery_status == "READY_FULL"
                    else "🟡 READY_DEGRADED"
                ),
                "presentation_qa": "🟢 PASS" if qa_pass else "🟡 DEGRADED",
                "privacy_boundary": "🟢 Private serving boundary enforced",
            }
            # S17 is governed like the other decision-critical sections.
            # Finalizing delivery provenance changes its payload, so refresh
            # only the presentation binding fingerprint; no analytics or
            # decision payload is recomputed.
            binding = dict(content.get("authoritative_binding") or {})
            if str(binding.get("status") or "").upper() == "BOUND":
                binding_payload = {
                    key: value
                    for key, value in content.items()
                    if key != "authoritative_binding"
                }
                binding["payload_fingerprint"] = hashlib.sha256(
                    json.dumps(
                        binding_payload,
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()
                content["authoritative_binding"] = binding
            row["content"] = content
        report["sections"] = sections
        from src.engines.v12_report_orchestration import render_deep_text
        bundle["report"] = report
        bundle["visible_body"] = render_deep_text(report)

    snapshot = build_serving_snapshot(bundle)
    occurrence_state = build_occurrence_state(bundle)
    presentation_qa = build_presentation_qa_manifest(bundle)
    failures = validate_serving_snapshot(snapshot)
    if str(bundle.get("report_mode") or "").upper() == "DEEP":
        failures.extend(validate_delivery_bundle(bundle))
        failures.extend(validate_presentation_qa_manifest(presentation_qa))
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
                "precompute_observability": occurrence_state[
                    "precompute_observability"
                ],
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        "delivery_state.json": json.dumps(
            occurrence_state, indent=2, ensure_ascii=False, default=str
        ) + "\n",
        "presentation_qa.json": json.dumps(
            presentation_qa, indent=2, ensure_ascii=False, default=str
        ) + "\n",
    }
    for name, payload in artifacts.items():
        target = output_dir / name
        tmp = target.with_name(f".{target.name}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(target)
    return snapshot
