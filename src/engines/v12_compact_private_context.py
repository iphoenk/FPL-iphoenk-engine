from __future__ import annotations

"""D-P7 read-only compact private context over canonical V12 output.

This module never scores, optimizes, selects captaincy, or mutates decision state.
It only validates lineage and projects already-canonical private output into a
small consumer payload for ChatGPT/web/mobile readers.
"""

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any


class CompactPrivateContextError(RuntimeError):
    pass


DEEP_SECTION_IDS = (
    "S01", "S02", "S03", "S04", "S05", "S06", "S06B",
    "S07", "S08", "S09", "S10", "S11", "S12", "S13",
    "S14", "S14B", "S15", "S15B", "S16", "S16B",
    "S17", "S18", "S19",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CompactPrivateContextError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _section_map(bundle: Mapping[str, Any]) -> dict[str, Any]:
    report = bundle.get("report")
    if isinstance(report, Mapping):
        nested = report.get("sections")
        if isinstance(nested, list):
            report = nested
        else:
            return {str(k): v for k, v in report.items()}
    rows: dict[str, Any] = {}
    if isinstance(report, list):
        for item in report:
            if not isinstance(item, Mapping):
                continue
            sid = str(item.get("id") or item.get("section_id") or "")
            if sid:
                rows[sid] = item.get("content", item)
    return rows


def _section_status(bundle: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in bundle.get("section_manifest") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("id") or raw.get("section_id") or "").strip()
        if not sid:
            continue
        out[sid] = str(raw.get("status") or raw.get("state") or "PRESENT").upper()
    return out


def _copy_first(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _decision_surface(bundle: Mapping[str, Any], sections: Mapping[str, Any]) -> dict[str, Any]:
    gameweek = bundle.get("gameweek_context")
    if not isinstance(gameweek, Mapping):
        gameweek = {}
    planning = gameweek.get("planning")
    if not isinstance(planning, Mapping):
        planning = {}
    decision = bundle.get("decision_surfaces")
    if not isinstance(decision, Mapping):
        decision = {}
    proof = bundle.get("execution_proof")
    if not isinstance(proof, Mapping):
        proof = {}

    lineup = {
        "our15": _copy_first(bundle, "our15", "current15", "owned_squad")
        or _copy_first(planning, "our15", "owned_squad", "submitted_squad"),
        "starting_xi": _copy_first(bundle, "starting_xi", "xi")
        or _copy_first(planning, "starting_xi", "xi")
        or _copy_first(decision, "starting_xi", "xi"),
        "bench": _copy_first(bundle, "bench", "bench_order")
        or _copy_first(planning, "bench", "bench_order")
        or _copy_first(decision, "bench", "bench_order"),
        "captain": _copy_first(bundle, "captain", "captain_element")
        or _copy_first(planning, "captain", "captain_element")
        or _copy_first(decision, "captain", "captain_element"),
        "vice_captain": _copy_first(bundle, "vice_captain", "vice", "vice_captain_element")
        or _copy_first(planning, "vice_captain", "vice", "vice_captain_element")
        or _copy_first(decision, "vice_captain", "vice", "vice_captain_element"),
        "chip": _copy_first(bundle, "chip", "active_chip")
        or _copy_first(planning, "chip", "active_chip")
        or _copy_first(decision, "chip", "active_chip"),
    }

    transfer = {
        "transfer_action": _copy_first(bundle, "transfer_action", "transfer_decision")
        or _copy_first(decision, "transfer_action", "transfer_decision"),
        "route": _copy_first(bundle, "route", "package_decision")
        or _copy_first(decision, "route", "package_decision"),
        "frontier": _copy_first(bundle, "transfer_frontier", "package_frontier")
        or _copy_first(decision, "transfer_frontier", "package_frontier"),
    }
    scenario = _copy_first(bundle, "scenario", "scenario_summary")
    if scenario is None:
        scenario = _copy_first(decision, "scenario", "scenario_summary")
    stability = _copy_first(bundle, "stability", "stability_summary")
    if stability is None:
        stability = _copy_first(decision, "stability", "stability_summary")
    mini = _copy_first(bundle, "mini_league", "mini_league_context")
    if mini is None:
        mini = sections.get("S15B")
    return {
        "decision_status": _copy_first(bundle, "final_decision_state", "stage3_action")
        or _copy_first(decision, "final_decision_state", "stage3_action")
        or proof.get("stage3_action"),
        "lineup": lineup,
        "transfer": transfer,
        "scenario": scenario,
        "stability": stability,
        "mini_league": mini,
        "s08": sections.get("S08"),
        "s19": sections.get("S19"),
    }


def build_compact_private_context(
    *,
    bundle: Mapping[str, Any],
    digest: Mapping[str, Any],
    execution_private: Mapping[str, Any],
    actual_bundle_sha256: str,
) -> dict[str, Any]:
    mode = str(bundle.get("report_mode") or "").upper()
    slot = str(bundle.get("report_slot") or "")
    if not mode or not slot:
        raise CompactPrivateContextError("canonical bundle missing report mode/slot")
    if str(digest.get("report_mode") or "").upper() != mode:
        raise CompactPrivateContextError("digest report mode mismatch")
    if str(digest.get("report_slot") or "") != slot:
        raise CompactPrivateContextError("digest report slot mismatch")
    expected_bundle_sha = str(digest.get("canonical_bundle_sha256") or "")
    if not expected_bundle_sha or expected_bundle_sha != str(actual_bundle_sha256):
        raise CompactPrivateContextError("canonical bundle digest mismatch")
    if execution_private.get("math_recomputed") is not False:
        raise CompactPrivateContextError("private execution lineage is not thin-copy")
    model_sha = str(execution_private.get("model_sha") or "")
    runtime_sha = str(execution_private.get("runtime_sha") or "")
    if len(model_sha) != 40 or len(runtime_sha) != 40:
        raise CompactPrivateContextError("canonical app/runtime lineage unavailable")

    section_status = _section_status(bundle)
    if mode == "DEEP":
        if tuple(section_status) != DEEP_SECTION_IDS:
            raise CompactPrivateContextError("DEEP canonical 23-section contract mismatch")
    sections = _section_map(bundle)
    surface = _decision_surface(bundle, sections)
    return {
        "schema": "FPL_V12_COMPACT_PRIVATE_CONTEXT_V1",
        "read_only": True,
        "decision_authority": "CANONICAL_V12_PRIVATE_BUNDLE",
        "math_recomputed": False,
        "report_mode": mode,
        "report_slot": slot,
        "planning_gw": bundle.get("planning_gw"),
        "runner_status": bundle.get("runner_status"),
        "delivery_status": bundle.get("delivery_status"),
        "lineage": {
            "model_sha": model_sha,
            "runtime_sha": runtime_sha,
            "canonical_bundle_sha256": expected_bundle_sha,
            "canonical_body_sha256": digest.get("canonical_body_sha256"),
        },
        "decision": surface,
        "section_status": section_status,
        "evidence_lineage": {
            "source_fingerprints": bundle.get("source_fingerprints"),
            "occurrence_id": bundle.get("occurrence_id"),
            "prefetch_binding": bundle.get("prefetch_binding"),
        },
    }


def build_from_files(
    *,
    bundle_path: Path,
    digest_path: Path,
    execution_private_path: Path,
) -> dict[str, Any]:
    bundle = _read_json(bundle_path)
    digest = _read_json(digest_path)
    execution_private = _read_json(execution_private_path)
    return build_compact_private_context(
        bundle=bundle,
        digest=digest,
        execution_private=execution_private,
        actual_bundle_sha256=_sha256(bundle_path),
    )
