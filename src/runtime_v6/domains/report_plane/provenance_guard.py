from __future__ import annotations

"""R5 provenance and anti-fabrication guard for report computation.

R4 owns structural section completeness. R5 owns evidence truthfulness:
FACT/MODEL/INFERENCE separation, immutable source proof for factual weather,
and execution proof for optimizer/Monte Carlo/frontier claims. Visible rendered
body validation remains R6 and delivery recovery remains R7.
"""

from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from .artifact_provenance import is_immutable_snapshot_id


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_RUN_STATES = frozenset({"EXECUTED", "PARTIAL"})
_NOT_RUN_STATE = "NOT_RUN"

PROVENANCE_CONTRACT_REGISTRY: dict[str, Mapping[str, Any]] = {
    "FACT": {
        "required_fields": ("source", "effective_at", "source_snapshot_ids"),
    },
    "MODEL": {
        "required_fields": ("model", "computed_at", "input_snapshot_ids"),
    },
    "INFERENCE": {
        "required_fields": ("basis", "fact_refs", "model_refs"),
    },
    "WEATHER": {
        "proof_fields": ("fact_ref", "source", "effective_at", "source_snapshot_ids"),
    },
    "EXECUTION": {
        "proof_fields": (
            "state",
            "run_id",
            "method",
            "executed_at",
            "input_fingerprint",
            "output_fingerprint",
        ),
        "components": ("optimizer", "monte_carlo", "frontier"),
    },
}


def canonical_fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, frozenset, dict)):
        return bool(value)
    return True


def _timezone_aware(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value.strip()) is not None


def _valid_snapshot_ids(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and bool(value)
        and all(isinstance(item, str) and is_immutable_snapshot_id(item) for item in value)
    )


def _mapping_rows(payload: Mapping[str, Any]) -> Iterable[tuple[str, Any]]:
    for key in sorted(payload, key=str):
        yield str(key), payload[key]


def _all_fact_snapshot_ids(facts: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for row in facts.values():
        if not isinstance(row, Mapping):
            continue
        snapshots = row.get("source_snapshot_ids")
        if not isinstance(snapshots, Sequence) or isinstance(snapshots, (str, bytes)):
            continue
        result.update(
            item
            for item in snapshots
            if isinstance(item, str) and is_immutable_snapshot_id(item)
        )
    return result


def _validate_partition(
    facts: Mapping[str, Any],
    models: Mapping[str, Any],
    inferences: Mapping[str, Any],
) -> dict[str, Any]:
    fact_keys = {str(key) for key in facts}
    model_keys = {str(key) for key in models}
    inference_keys = {str(key) for key in inferences}
    fact_model_overlap = fact_keys & model_keys
    overlap = sorted(
        fact_model_overlap
        | (fact_keys & inference_keys)
        | (model_keys & inference_keys)
    )
    failures: list[str] = []
    if overlap:
        failures.append(f"PARTITION_OVERLAP={','.join(overlap)}")

    for key, row in _mapping_rows(facts):
        if not isinstance(row, Mapping):
            failures.append(f"FACT_ROW_INVALID={key}")
            continue
        if not _nonempty(row.get("source")):
            failures.append(f"FACT_SOURCE_MISSING={key}")
        if not _timezone_aware(row.get("effective_at")):
            failures.append(f"FACT_EFFECTIVE_AT_INVALID={key}")
        if not _valid_snapshot_ids(row.get("source_snapshot_ids")):
            failures.append(f"FACT_SOURCE_SNAPSHOT_IDS_INVALID={key}")

    fact_snapshot_ids = _all_fact_snapshot_ids(facts)
    for key, row in _mapping_rows(models):
        if not isinstance(row, Mapping):
            failures.append(f"MODEL_ROW_INVALID={key}")
            continue
        if not _nonempty(row.get("model")):
            failures.append(f"MODEL_ID_MISSING={key}")
        if not _timezone_aware(row.get("computed_at")):
            failures.append(f"MODEL_COMPUTED_AT_INVALID={key}")
        input_snapshot_ids = row.get("input_snapshot_ids")
        if not _valid_snapshot_ids(input_snapshot_ids):
            failures.append(f"MODEL_INPUT_SNAPSHOT_IDS_INVALID={key}")
        elif not {str(item) for item in input_snapshot_ids}.issubset(fact_snapshot_ids):
            failures.append(f"MODEL_INPUT_PROVENANCE_UNLINKED={key}")

    for key, row in _mapping_rows(inferences):
        if not isinstance(row, Mapping):
            failures.append(f"INFERENCE_ROW_INVALID={key}")
            continue
        if not _nonempty(row.get("basis")):
            failures.append(f"INFERENCE_BASIS_MISSING={key}")
        fact_refs = row.get("fact_refs")
        model_refs = row.get("model_refs")
        if not isinstance(fact_refs, Sequence) or isinstance(fact_refs, (str, bytes)):
            failures.append(f"INFERENCE_FACT_REFS_INVALID={key}")
            fact_refs = []
        if not isinstance(model_refs, Sequence) or isinstance(model_refs, (str, bytes)):
            failures.append(f"INFERENCE_MODEL_REFS_INVALID={key}")
            model_refs = []
        if not fact_refs and not model_refs:
            failures.append(f"INFERENCE_EVIDENCE_REFS_MISSING={key}")
        unknown_facts = sorted({str(ref) for ref in fact_refs} - fact_keys)
        unknown_models = sorted({str(ref) for ref in model_refs} - model_keys)
        if unknown_facts:
            failures.append(f"INFERENCE_UNKNOWN_FACT_REFS={key}:{','.join(unknown_facts)}")
        if unknown_models:
            failures.append(f"INFERENCE_UNKNOWN_MODEL_REFS={key}:{','.join(unknown_models)}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "fact_keys": sorted(fact_keys),
        "model_keys": sorted(model_keys),
        "inference_keys": sorted(inference_keys),
        "overlap": overlap,
        "fact_model_overlap": sorted(fact_model_overlap),
    }


def _validate_source_proof(proof: Any, *, prefix: str) -> list[str]:
    if not isinstance(proof, Mapping):
        return [f"{prefix}_SOURCE_PROOF_MISSING"]
    failures: list[str] = []
    if not _nonempty(proof.get("source")):
        failures.append(f"{prefix}_SOURCE_MISSING")
    if not _timezone_aware(proof.get("effective_at")):
        failures.append(f"{prefix}_EFFECTIVE_AT_INVALID")
    if not _valid_snapshot_ids(proof.get("source_snapshot_ids")):
        failures.append(f"{prefix}_SOURCE_SNAPSHOT_IDS_INVALID")
    return failures


def _validate_weather(section_payloads: Mapping[str, Any], facts: Mapping[str, Any]) -> dict[str, Any]:
    weather = section_payloads.get("WEATHER")
    if not isinstance(weather, Mapping):
        return {"status": "FAIL", "failures": ["WEATHER_SECTION_MISSING"]}

    state = str(weather.get("content_state") or "").strip().upper()
    rows = weather.get("rows")
    row_count = len(rows) if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)) else 0
    proof_required = state == "PASS" or row_count > 0
    failures: list[str] = []
    proof = weather.get("source_proof")
    if proof_required:
        failures.extend(_validate_source_proof(proof, prefix="WEATHER"))
        if isinstance(proof, Mapping):
            fact_ref = str(proof.get("fact_ref") or "").strip()
            if not fact_ref:
                failures.append("WEATHER_FACT_REF_MISSING")
            elif fact_ref not in facts:
                failures.append(f"WEATHER_FACT_REF_UNKNOWN={fact_ref}")
            else:
                fact = facts[fact_ref]
                if not isinstance(fact, Mapping):
                    failures.append(f"WEATHER_FACT_REF_INVALID={fact_ref}")
                else:
                    proof_source = str(proof.get("source") or "").strip().casefold()
                    fact_source = str(fact.get("source") or "").strip().casefold()
                    if proof_source and fact_source and proof_source != fact_source:
                        failures.append(f"WEATHER_FACT_SOURCE_MISMATCH={fact_ref}")
                    proof_ids = proof.get("source_snapshot_ids")
                    fact_ids = fact.get("source_snapshot_ids")
                    if _valid_snapshot_ids(proof_ids) and _valid_snapshot_ids(fact_ids):
                        if not {str(item) for item in proof_ids}.issubset(
                            {str(item) for item in fact_ids}
                        ):
                            failures.append(f"WEATHER_FACT_PROVENANCE_MISMATCH={fact_ref}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "content_state": state,
        "proof_required": proof_required,
        "row_count": row_count,
    }


def _execution_state(row: Any) -> str:
    if not isinstance(row, Mapping):
        return ""
    return str(row.get("state") or "").strip().upper()


def _validate_run_identity(row: Any, *, label: str) -> list[str]:
    if not isinstance(row, Mapping):
        return [f"{label}_EXECUTION_PROOF_INVALID"]
    failures: list[str] = []
    for field in ("run_id", "method"):
        if not _nonempty(row.get(field)):
            failures.append(f"{label}_{field.upper()}_MISSING")
    if not _timezone_aware(row.get("executed_at")):
        failures.append(f"{label}_EXECUTED_AT_INVALID")
    for field in ("input_fingerprint", "output_fingerprint"):
        if not _valid_sha256(row.get(field)):
            failures.append(f"{label}_{field.upper()}_INVALID")
    return failures


def _validate_optional_execution(
    row: Any,
    *,
    label: str,
    expected_output_fingerprint: str,
    require_actual_paths: bool = False,
) -> list[str]:
    if row is None:
        return []
    if not isinstance(row, Mapping):
        return [f"{label}_EXECUTION_PROOF_INVALID"]
    state = _execution_state(row)
    if state == _NOT_RUN_STATE:
        if not _nonempty(row.get("reason")):
            return [f"{label}_NOT_RUN_REASON_MISSING"]
        return []
    if state not in _RUN_STATES:
        return [f"{label}_STATE_INVALID={state or '<empty>'}"]

    failures = _validate_run_identity(row, label=label)
    if _valid_sha256(row.get("output_fingerprint")) and str(row["output_fingerprint"]).lower() != expected_output_fingerprint:
        failures.append(f"{label}_OUTPUT_FINGERPRINT_MISMATCH")
    if require_actual_paths:
        actual_paths = row.get("actual_paths")
        if not isinstance(actual_paths, int) or isinstance(actual_paths, bool) or actual_paths <= 0:
            failures.append(f"{label}_ACTUAL_PATHS_INVALID")
    if state == "PARTIAL" and not _nonempty(row.get("degradation_reason")):
        failures.append(f"{label}_DEGRADATION_REASON_MISSING")
    return failures


def _validate_execution(section_payloads: Mapping[str, Any]) -> dict[str, Any]:
    optimizer = section_payloads.get("OPTIMIZER")
    if not isinstance(optimizer, Mapping):
        return {"status": "FAIL", "failures": ["OPTIMIZER_SECTION_MISSING"]}

    section_state = str(optimizer.get("content_state") or "").strip().upper()
    routes = optimizer.get("routes")
    route_rows = list(routes) if isinstance(routes, Sequence) and not isinstance(routes, (str, bytes)) else []
    proof = optimizer.get("execution_proof")
    failures: list[str] = []

    if section_state == "PASS" or route_rows:
        if not isinstance(proof, Mapping):
            return {
                "status": "FAIL",
                "failures": ["OPTIMIZER_EXECUTION_PROOF_MISSING"],
                "content_state": section_state,
            }

        optimizer_run = proof.get("optimizer")
        optimizer_state = _execution_state(optimizer_run)
        if optimizer_state not in _RUN_STATES:
            failures.append(f"OPTIMIZER_STATE_INVALID={optimizer_state or '<empty>'}")
        else:
            failures.extend(_validate_run_identity(optimizer_run, label="OPTIMIZER"))
            expected_routes = canonical_fingerprint(route_rows)
            if (
                isinstance(optimizer_run, Mapping)
                and _valid_sha256(optimizer_run.get("output_fingerprint"))
                and str(optimizer_run["output_fingerprint"]).lower() != expected_routes
            ):
                failures.append("OPTIMIZER_OUTPUT_FINGERPRINT_MISMATCH")
            if section_state == "PASS" and optimizer_state != "EXECUTED":
                failures.append("OPTIMIZER_PASS_REQUIRES_EXECUTED_STATE")
            if optimizer_state == "PARTIAL" and not _nonempty(optimizer_run.get("degradation_reason")):
                failures.append("OPTIMIZER_DEGRADATION_REASON_MISSING")

        route_summary_fingerprint = canonical_fingerprint(
            {"route_ids": [row.get("route_id") if isinstance(row, Mapping) else None for row in route_rows]}
        )
        optional_components = (
            ("monte_carlo", "MONTE_CARLO", True),
            ("frontier", "FRONTIER", False),
        )
        for component, label, require_actual_paths in optional_components:
            if component not in proof:
                failures.append(f"{label}_EXECUTION_PROOF_MISSING")
                continue
            failures.extend(
                _validate_optional_execution(
                    proof.get(component),
                    label=label,
                    expected_output_fingerprint=route_summary_fingerprint,
                    require_actual_paths=require_actual_paths,
                )
            )

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "content_state": section_state,
        "route_count": len(route_rows),
    }


def validate_report_provenance(
    *,
    section_payloads: Mapping[str, Any],
    facts: Mapping[str, Any],
    models: Mapping[str, Any],
    inferences: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate all R5 evidence claims through one fail-closed authority."""
    partition = _validate_partition(facts, models, inferences)
    weather = _validate_weather(section_payloads, facts)
    execution = _validate_execution(section_payloads)
    failures = [
        name
        for name, result in (
            ("PARTITION", partition),
            ("WEATHER", weather),
            ("EXECUTION", execution),
        )
        if result["status"] != "PASS"
    ]
    return {
        "status": "PASS" if not failures else "FAIL",
        "provenance_ready": not failures,
        "failures": failures,
        "partition": partition,
        "weather": weather,
        "execution": execution,
        "registry": PROVENANCE_CONTRACT_REGISTRY,
    }
