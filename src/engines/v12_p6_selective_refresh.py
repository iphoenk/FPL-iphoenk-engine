from __future__ import annotations

"""Governed selective serving for P6/PERF-F precomputed V12 scenarios.

This module does not create a second model or optimizer.  It consumes decision
surfaces produced by the canonical V12 P4 evaluator, rebinds them to the current
report occurrence, rematerializes the canonical DEEP report, and reruns the
same delivery QA barriers used by the integrated runner.
"""

from collections.abc import Mapping
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from src.engines.v12_integrated_report_runner import (
    CANONICAL_PATH,
    IntegratedRunnerError,
    _fingerprint,
    _parse_sections,
    _qa_compute_contract,
)
from src.engines.v12_report_orchestration import (
    build_deep_human_facing_manifest,
    materialize_deep_report,
    render_deep_text,
    validate_deep_human_facing_manifest,
    validate_human_facing_body,
)
from src.engines.v12_final_delivery_barrier import validate_final_delivery_barrier
from src.runtime_v6.domains.report_plane.report_qa import (
    validate_post_render_qa,
    validate_pre_render_qa,
)


class SelectiveRefreshError(RuntimeError):
    pass


def _section_map(bundle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    report = bundle.get("report")
    if not isinstance(report, Mapping):
        raise SelectiveRefreshError("selective refresh requires a canonical DEEP report")
    out: dict[str, dict[str, Any]] = {}
    for raw in report.get("sections") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("section_id") or "")
        if not sid:
            continue
        out[sid] = {
            "state": raw.get("state"),
            "content": deepcopy(raw.get("content")),
            "degradation_reason": raw.get("degradation_reason"),
            "available_count": raw.get("available_count"),
            "expected_count": raw.get("expected_count"),
        }
    return out


def _rebind_content(
    *,
    current: Mapping[str, Any] | None,
    replacement: Mapping[str, Any],
    report_slot: str,
) -> dict[str, Any]:
    out = deepcopy(dict(replacement))
    existing_binding = dict(out.pop("authoritative_binding", None) or {})
    if not existing_binding and isinstance(current, Mapping):
        existing_binding = dict(current.get("authoritative_binding") or {})
    producer = str(existing_binding.get("producer") or "").strip()
    if producer:
        out["authoritative_binding"] = {
            "status": "BOUND",
            "producer": producer,
            "payload_fingerprint": _fingerprint(out),
            "report_slot": report_slot,
        }
    return out


def _finalize_deep_state(
    *,
    state: Mapping[str, Any],
    section_payloads: Mapping[str, Mapping[str, Any]],
    report_slot: str,
    change_class: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    refreshed = deepcopy(dict(state))
    bundle = deepcopy(dict(refreshed.get("bundle") or {}))
    warm = deepcopy(dict(refreshed.get("warm_state") or {}))
    if str(bundle.get("report_mode") or "").upper() != "DEEP":
        raise SelectiveRefreshError("selective refresh requires DEEP state")
    owned = [
        dict(row) for row in warm.get("owned") or [] if isinstance(row, Mapping)
    ]
    lineup = dict(warm.get("lineup") or {})
    watchlist = dict(warm.get("watchlist") or {})
    rise = dict(warm.get("rise") or {})
    fall = dict(warm.get("fall") or {})
    if len(owned) != 15 or not lineup:
        raise SelectiveRefreshError("frozen canonical OUR15/lineup is incomplete")

    canonical = CANONICAL_PATH.read_text(encoding="utf-8")
    new_report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads=section_payloads,
    )
    section_manifest = [
        {
            "section_id": str(row.get("section_id") or ""),
            "status": str(row.get("state") or ""),
        }
        for row in new_report.get("sections") or []
    ]
    human_manifest = build_deep_human_facing_manifest(new_report)
    compute_contract = _qa_compute_contract(
        owned=owned,
        lineup=lineup,
        watchlist=watchlist,
        rise=rise,
        fall=fall,
        sections=section_payloads,
        human_manifest=human_manifest,
    )

    mini = dict(warm.get("mini") or {})
    mini_complete = bool(
        mini and str(mini.get("coverage_state") or "").upper() == "FULL"
    )
    calendar_context = dict(warm.get("calendar_context") or {})
    weather_bound = any(
        str(row.get("fpl_impact") or "UNAVAILABLE").upper()
        in {"NORMAL", "LOW", "MATERIAL"}
        for row in calendar_context.get("weather") or []
        if isinstance(row, Mapping)
    )
    weather_contract_state = (
        "REPORT_TIME_BOUND" if weather_bound else "SOURCE_DEGRADED"
    )

    pre_render_qa = validate_pre_render_qa(
        compute_contract=compute_contract,
        section_manifest=section_manifest,
        mini_league_denominator_complete=mini_complete,
        report_mode="DEEP",
        weather_contract_state=weather_contract_state,
    )
    body = render_deep_text(new_report)
    final_delivery_barrier = validate_final_delivery_barrier(
        report_mode="DEEP",
        report=new_report,
        body=body,
    )
    human_failures = list(
        dict.fromkeys(
            validate_human_facing_body(body)
            + validate_deep_human_facing_manifest(human_manifest)
            + list(final_delivery_barrier.get("failures") or [])
        )
    )
    parsed_ids, _, _ = _parse_sections(body)
    rendered_states = {
        str(row.get("section_id") or ""): str(row.get("state") or "")
        for row in new_report.get("sections") or []
    }
    post_render_qa = validate_post_render_qa(
        pre_render_qa=pre_render_qa,
        rendered_body=body,
        rendered_section_ids=parsed_ids,
        rendered_section_states=rendered_states,
        rendered_compute_fingerprint=compute_contract["compute_fingerprint"],
        render_contract_token=pre_render_qa.get("render_contract_token"),
        rendered_counts=dict(pre_render_qa.get("expected_counts") or {}),
        rendered_fact_keys=list(pre_render_qa.get("expected_fact_keys") or []),
        rendered_model_keys=list(pre_render_qa.get("expected_model_keys") or []),
        rendered_mini_league_denominator_complete=mini_complete,
        rendered_weather_contract_state=weather_contract_state,
        truncated=False,
    )
    if (
        str(pre_render_qa.get("status") or "").upper() != "PASS"
        or str(post_render_qa.get("status") or "").upper() != "PASS"
        or human_failures
        or str(final_delivery_barrier.get("status") or "").upper() != "PASS"
    ):
        raise SelectiveRefreshError(
            "selective refresh failed canonical delivery QA: "
            + json.dumps(
                {
                    "pre_render": {
                        "status": pre_render_qa.get("status"),
                        "failures": pre_render_qa.get("hard_failures")
                        or pre_render_qa.get("failures")
                        or [],
                    },
                    "post_render": {
                        "status": post_render_qa.get("status"),
                        "failures": post_render_qa.get("hard_failures")
                        or post_render_qa.get("failures")
                        or [],
                    },
                    "human_facing_failures": human_failures,
                    "final_delivery": {
                        "status": final_delivery_barrier.get("status"),
                        "failures": final_delivery_barrier.get("failures") or [],
                    },
                },
                sort_keys=True,
                ensure_ascii=True,
            )
        )

    execution_proof = deepcopy(dict(bundle.get("execution_proof") or {}))
    execution_proof["warm_selective_refresh"] = {
        "change_class": str(change_class).upper(),
        "status": "PASS",
        "canonical_precomputed_surfaces_only": True,
        "qa_relaxed": False,
        **deepcopy(dict(evidence)),
    }
    bundle.update(
        {
            "runner_status": "PASS",
            "section_manifest": section_manifest,
            "human_facing_manifest": human_manifest,
            "compute_contract": compute_contract,
            "pre_render_qa": pre_render_qa,
            "post_render_qa": post_render_qa,
            "human_facing_qa": {"status": "PASS", "failures": []},
            "final_delivery_barrier": final_delivery_barrier,
            "execution_proof": execution_proof,
            "report": new_report,
            "visible_body": body,
        }
    )
    governance = deepcopy(dict(bundle.get("governance") or {}))
    governance.update(
        {
            "p6_selective_refresh": str(change_class).upper(),
            "canonical_precomputed_surface_authority": True,
            "qa_relaxed": False,
            "second_methodology_created": False,
        }
    )
    bundle["governance"] = governance
    refreshed["bundle"] = bundle
    refreshed["execution_proof"] = execution_proof

    output_dir = Path(str(refreshed.get("output_dir") or ""))
    if not str(output_dir):
        raise SelectiveRefreshError("selective refresh output_dir unavailable")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report_bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "execution_proof.json").write_text(
        json.dumps(
            execution_proof,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "report_body.md").write_text(body, encoding="utf-8")
    return refreshed


def refresh_p4_scenario_state(
    *,
    state: Mapping[str, Any],
    report_slot: str,
    scenario_row: Mapping[str, Any],
    change_class: str,
    package_fingerprint: str,
    extra_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Serve an exact canonical P4 counterfactual through full delivery QA."""
    decision_surfaces = scenario_row.get("decision_surfaces")
    if not isinstance(decision_surfaces, Mapping):
        raise SelectiveRefreshError("P4 scenario has no canonical decision surfaces")
    required = {"S06", "S08", "S09", "S14", "S19"}
    missing = sorted(required - set(str(k) for k in decision_surfaces))
    if missing:
        raise SelectiveRefreshError(
            "P4 scenario missing canonical surfaces: " + ",".join(missing)
        )

    bundle = deepcopy(dict(state.get("bundle") or {}))
    sections = _section_map(bundle)
    for sid in required:
        if sid not in sections:
            raise SelectiveRefreshError(f"baseline report missing {sid}")
        replacement = decision_surfaces[sid]
        if not isinstance(replacement, Mapping):
            raise SelectiveRefreshError(f"P4 scenario {sid} is not an object")
        current = sections[sid].get("content")
        sections[sid]["content"] = _rebind_content(
            current=current if isinstance(current, Mapping) else None,
            replacement=replacement,
            report_slot=report_slot,
        )
        sections[sid]["state"] = "COMPLETE"
        sections[sid]["degradation_reason"] = None

    return _finalize_deep_state(
        state=state,
        section_payloads=sections,
        report_slot=report_slot,
        change_class=change_class,
        evidence={
            "scenario_id": str(scenario_row.get("scenario_id") or ""),
            "scenario_output_fingerprint": str(
                scenario_row.get("output_fingerprint") or ""
            ),
            "package_fingerprint": str(package_fingerprint or ""),
            "decision_surfaces_rebound": sorted(required),
            **deepcopy(dict(extra_evidence or {})),
        },
    )


def refresh_revalidated_base_state(
    *,
    state: Mapping[str, Any],
    report_slot: str,
    change_class: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Revalidate an unchanged canonical DEEP surface without copying it.

    CAPTAIN_CHANGE / VICE_CAPTAIN_CHANGE and rejected wrong-base P4 lookups may
    require cache invalidation/revalidation while the canonical cold oracle
    proves that the governed human-facing decision surface itself is unchanged.
    Re-running delivery QA is mandatory, but deep-copying and reserializing the
    multi-megabyte canonical bundle is not.  This path therefore validates the
    existing immutable report/body/compute contract in-place, records a small
    execution-proof receipt, and leaves the canonical bundle bytes untouched.
    """
    bundle_source = state.get("bundle")
    if not isinstance(bundle_source, Mapping):
        raise SelectiveRefreshError("canonical base bundle unavailable")
    bundle = dict(bundle_source)
    if str(bundle.get("report_mode") or "").upper() != "DEEP":
        raise SelectiveRefreshError("selective refresh requires DEEP state")
    if str(bundle.get("report_slot") or "") != str(report_slot):
        raise SelectiveRefreshError("canonical base report_slot mismatch")

    report = bundle.get("report")
    if not isinstance(report, Mapping):
        raise SelectiveRefreshError("canonical base has no DEEP report")
    section_manifest = list(bundle.get("section_manifest") or [])
    if not section_manifest:
        raise SelectiveRefreshError("canonical base section manifest unavailable")
    compute_contract = bundle.get("compute_contract")
    if not isinstance(compute_contract, Mapping):
        raise SelectiveRefreshError("canonical base compute contract unavailable")
    human_manifest = bundle.get("human_facing_manifest")
    if not isinstance(human_manifest, Mapping):
        raise SelectiveRefreshError("canonical human-facing manifest unavailable")
    body = str(bundle.get("visible_body") or "")
    if not body:
        raise SelectiveRefreshError("canonical visible body unavailable")

    warm = state.get("warm_state")
    if not isinstance(warm, Mapping):
        raise SelectiveRefreshError("canonical warm state unavailable")
    mini = warm.get("mini")
    mini_complete = bool(
        isinstance(mini, Mapping)
        and str(mini.get("coverage_state") or "").upper() == "FULL"
    )
    calendar_context = warm.get("calendar_context")
    if not isinstance(calendar_context, Mapping):
        calendar_context = {}
    weather_bound = any(
        str(row.get("fpl_impact") or "UNAVAILABLE").upper()
        in {"NORMAL", "LOW", "MATERIAL"}
        for row in calendar_context.get("weather") or []
        if isinstance(row, Mapping)
    )
    weather_contract_state = (
        "REPORT_TIME_BOUND" if weather_bound else "SOURCE_DEGRADED"
    )

    pre_render_qa = validate_pre_render_qa(
        compute_contract=compute_contract,
        section_manifest=section_manifest,
        mini_league_denominator_complete=mini_complete,
        report_mode="DEEP",
        weather_contract_state=weather_contract_state,
    )
    final_delivery_barrier = validate_final_delivery_barrier(
        report_mode="DEEP",
        report=report,
        body=body,
    )
    human_failures = list(
        dict.fromkeys(
            validate_human_facing_body(body)
            + validate_deep_human_facing_manifest(human_manifest)
            + list(final_delivery_barrier.get("failures") or [])
        )
    )
    parsed_ids, _, _ = _parse_sections(body)
    rendered_states = {
        str(row.get("section_id") or ""): str(row.get("state") or "")
        for row in report.get("sections") or []
        if isinstance(row, Mapping)
    }
    post_render_qa = validate_post_render_qa(
        pre_render_qa=pre_render_qa,
        rendered_body=body,
        rendered_section_ids=parsed_ids,
        rendered_section_states=rendered_states,
        rendered_compute_fingerprint=str(
            compute_contract.get("compute_fingerprint") or ""
        ),
        render_contract_token=pre_render_qa.get("render_contract_token"),
        rendered_counts=dict(pre_render_qa.get("expected_counts") or {}),
        rendered_fact_keys=list(pre_render_qa.get("expected_fact_keys") or []),
        rendered_model_keys=list(pre_render_qa.get("expected_model_keys") or []),
        rendered_mini_league_denominator_complete=mini_complete,
        rendered_weather_contract_state=weather_contract_state,
        truncated=False,
    )
    if (
        str(pre_render_qa.get("status") or "").upper() != "PASS"
        or str(post_render_qa.get("status") or "").upper() != "PASS"
        or human_failures
        or str(final_delivery_barrier.get("status") or "").upper() != "PASS"
    ):
        raise SelectiveRefreshError(
            "canonical base revalidation failed delivery QA: "
            + json.dumps(
                {
                    "pre_render": pre_render_qa.get("status"),
                    "post_render": post_render_qa.get("status"),
                    "human_facing_failures": human_failures,
                    "final_delivery": final_delivery_barrier.get("status"),
                },
                sort_keys=True,
                ensure_ascii=True,
            )
        )

    execution_proof = dict(state.get("execution_proof") or {})
    execution_proof["warm_selective_refresh"] = {
        "change_class": str(change_class).upper(),
        "status": "PASS",
        "canonical_precomputed_surfaces_only": True,
        "canonical_bundle_bytes_reused": True,
        "canonical_base_rematerialized": False,
        "stale_scenario_reused": False,
        "pre_render_qa_rerun": True,
        "post_render_qa_rerun": True,
        "human_facing_qa_rerun": True,
        "final_delivery_qa_rerun": True,
        "qa_relaxed": False,
        **dict(evidence),
    }

    refreshed = dict(state)
    bundle["pre_render_qa"] = pre_render_qa
    bundle["post_render_qa"] = post_render_qa
    bundle["human_facing_qa"] = {"status": "PASS", "failures": []}
    bundle["final_delivery_barrier"] = final_delivery_barrier
    bundle["execution_proof"] = execution_proof
    governance = dict(bundle.get("governance") or {})
    governance.update(
        {
            "p6_selective_refresh": str(change_class).upper(),
            "canonical_precomputed_surface_authority": True,
            "canonical_bundle_bytes_reused": True,
            "qa_relaxed": False,
            "second_methodology_created": False,
        }
    )
    bundle["governance"] = governance
    refreshed["bundle"] = bundle
    refreshed["execution_proof"] = execution_proof

    # Persist only the small execution proof.  The canonical report bundle/body
    # bytes are unchanged and remain the exact already-QA'd cold-equivalent
    # surface consumed by the thin private publisher.
    output_dir = Path(str(refreshed.get("output_dir") or ""))
    if not str(output_dir):
        raise SelectiveRefreshError("selective refresh output_dir unavailable")
    (output_dir / "execution_proof.json").write_text(
        json.dumps(
            execution_proof,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return refreshed
