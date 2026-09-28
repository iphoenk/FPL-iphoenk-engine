from __future__ import annotations

"""Canonical cold-vs-warm semantic oracle for V12 delivery."""

from collections.abc import Mapping
import hashlib
import json
from typing import Any

REQUIRED_REPORT_SECTIONS = ("S08", "S11", "S12", "S13", "S15B", "S19")
NON_SEMANTIC_KEYS = frozenset({
    "generated_at", "observed_at", "created_at", "updated_at", "published_at",
    "run_id", "workflow_run_id", "elapsed_seconds", "timing", "timings",
    "queue_seconds", "started_at", "finished_at",
})
DIRECT_SEMANTIC_KEYS = (
    "transfer_decision", "xi", "bench", "captain", "vice",
    "route", "package_decision", "p1_7", "p17", "monte_carlo", "mc",
    "final_decision_state", "stage3_action",
)


class SemanticOracleError(RuntimeError):
    pass


def _strip_nonsemantic(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _strip_nonsemantic(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            if str(k) not in NON_SEMANTIC_KEYS
        }
    if isinstance(value, list):
        return [_strip_nonsemantic(v) for v in value]
    if isinstance(value, tuple):
        return [_strip_nonsemantic(v) for v in value]
    return value


def _report_sections(payload: Mapping[str, Any]) -> dict[str, Any]:
    report = payload.get("report")
    if not isinstance(report, Mapping):
        report = payload.get("sections")
    if isinstance(report, Mapping):
        return {
            section: report[section]
            for section in REQUIRED_REPORT_SECTIONS
            if section in report
        }
    if isinstance(report, list):
        rows: dict[str, Any] = {}
        for item in report:
            if not isinstance(item, Mapping):
                continue
            sid = str(item.get("id") or item.get("section_id") or "")
            if sid in REQUIRED_REPORT_SECTIONS:
                rows[sid] = item
        return rows
    return {}


def semantic_surface(payload: Mapping[str, Any]) -> dict[str, Any]:
    explicit = payload.get("semantic_surface")
    if isinstance(explicit, Mapping):
        return _strip_nonsemantic(explicit)

    surface: dict[str, Any] = {}
    decision = payload.get("decision_surfaces")
    if isinstance(decision, Mapping):
        surface["decision_surfaces"] = dict(decision)

    sections = _report_sections(payload)
    if sections:
        surface["report_sections"] = sections

    for key in DIRECT_SEMANTIC_KEYS:
        if key in payload:
            surface[key] = payload[key]

    proof = payload.get("execution_proof")
    if isinstance(proof, Mapping) and "stage3_action" in proof:
        surface["stage3_action"] = proof["stage3_action"]

    if not surface:
        raise SemanticOracleError("no governed semantic surface found")
    return _strip_nonsemantic(surface)


def semantic_fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        semantic_surface(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def compare_warm_cold(
    *,
    warm: Mapping[str, Any],
    cold: Mapping[str, Any],
) -> dict[str, Any]:
    warm_surface = semantic_surface(warm)
    cold_surface = semantic_surface(cold)
    warm_fp = semantic_fingerprint(warm)
    cold_fp = semantic_fingerprint(cold)
    return {
        "equal": warm_fp == cold_fp and warm_surface == cold_surface,
        "warm_semantic_fingerprint": warm_fp,
        "canonical_cold_semantic_fingerprint": cold_fp,
        "warm_surface": warm_surface,
        "cold_surface": cold_surface,
    }
