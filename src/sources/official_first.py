from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from src.utils import ROOT

COVERAGE_PATH = ROOT / "config" / "sources" / "official_first_coverage.json"

EXPECTED_RECS = tuple(
    [f"REC-{n:02d}" for n in range(1, 9)]
    + ["REC-09a", "REC-09b"]
    + [f"REC-{n:02d}" for n in range(10, 42)]
)

APPLICABILITY = {
    "PUBLIC_FIRST",
    "PUBLIC_FIRST_WITH_ENRICHMENT",
    "PUBLIC_FIRST_WITH_UNEXPOSED_ENRICHMENT",
    "PUBLIC_THEN_PRIVATE_AUTH",
    "PUBLIC_CONTEXT",
    "OFFICIAL_TRANSPORT_POLICY",
    "POLICY_ONLY",
    "NOT_APPLICABLE",
}


@lru_cache(maxsize=1)
def load_official_first_coverage() -> dict[str, Any]:
    payload = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))
    validate_official_first_coverage(payload)
    return payload


def validate_official_first_coverage(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("registry") != "OFFICIAL_FIRST_REC_COVERAGE_V1":
        raise RuntimeError("unexpected Official-first coverage registry")
    policy = payload.get("policy") or {}
    if policy.get("official_fpl_first_for_native_or_potentially_native_fields") is not True:
        raise RuntimeError("Official-first policy must be enabled")
    if policy.get("fallback_requires_explicit_disposition") is not True:
        raise RuntimeError("fallback must require explicit Official disposition")

    allowed_fallbacks = set(policy.get("allowed_fallback_dispositions") or [])
    required_fallbacks = {
        "OFFICIAL_NOT_APPLICABLE",
        "OFFICIAL_UNAVAILABLE",
        "FIELD_NOT_EXPOSED",
        "PRIVATE_AUTH_REQUIRED",
    }
    if allowed_fallbacks != required_fallbacks:
        raise RuntimeError("Official-first fallback dispositions must be exact and closed")

    catalog = payload.get("endpoint_catalog") or {}
    rows = payload.get("recommendations") or {}
    if set(rows) != set(EXPECTED_RECS):
        missing = sorted(set(EXPECTED_RECS) - set(rows))
        extra = sorted(set(rows) - set(EXPECTED_RECS))
        raise RuntimeError(f"Official-first REC coverage mismatch missing={missing} extra={extra}")

    for rec_id, row in rows.items():
        applicability = row.get("applicability")
        if applicability not in APPLICABILITY:
            raise RuntimeError(f"invalid Official applicability for {rec_id}: {applicability}")
        endpoints = row.get("endpoints")
        if not isinstance(endpoints, list):
            raise RuntimeError(f"Official endpoints must be a list for {rec_id}")
        unknown = sorted(set(endpoints) - set(catalog))
        if unknown:
            raise RuntimeError(f"unknown Official endpoints for {rec_id}: {unknown}")
        if applicability == "NOT_APPLICABLE" and endpoints:
            raise RuntimeError(f"NOT_APPLICABLE REC cannot declare endpoints: {rec_id}")
        if applicability not in {"NOT_APPLICABLE", "POLICY_ONLY"} and not endpoints:
            raise RuntimeError(f"Official-applicable REC must declare endpoints: {rec_id}")
        if not str(row.get("purpose") or "").strip():
            raise RuntimeError(f"Official-first purpose missing for {rec_id}")

    return {
        "registry": payload.get("registry"),
        "schema_version": payload.get("schema_version"),
        "covered_recommendations": len(rows),
        "official_applicable": sum(
            1 for row in rows.values() if row.get("applicability") not in {"NOT_APPLICABLE", "POLICY_ONLY"}
        ),
        "not_applicable": sum(1 for row in rows.values() if row.get("applicability") == "NOT_APPLICABLE"),
        "policy_only": sum(1 for row in rows.values() if row.get("applicability") == "POLICY_ONLY"),
        "integrity_ok": True,
    }


def coverage_for(rec_id: str) -> dict[str, Any]:
    try:
        return dict(load_official_first_coverage()["recommendations"][str(rec_id)])
    except KeyError as exc:
        raise KeyError(f"REC not covered by Official-first matrix: {rec_id}") from exc


def official_attempt_required(rec_id: str) -> bool:
    applicability = coverage_for(rec_id).get("applicability")
    return applicability not in {"NOT_APPLICABLE", "POLICY_ONLY"}


def fallback_allowed(rec_id: str, disposition: str) -> bool:
    row = coverage_for(rec_id)
    allowed = set(load_official_first_coverage()["policy"]["allowed_fallback_dispositions"])
    disposition = str(disposition)
    if row.get("applicability") == "NOT_APPLICABLE":
        return disposition == "OFFICIAL_NOT_APPLICABLE"
    return disposition in allowed - {"OFFICIAL_NOT_APPLICABLE"}
