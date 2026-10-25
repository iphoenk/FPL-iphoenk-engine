"""Allowlisted, facts-only projection of a validated V6 snapshot for the dashboard (F05).

Pure function: no network, no logging, no publication. It is a schema/fixture boundary only and
is not activated or exported publicly by default.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from src.runtime_v6.registry import ZERO_AUTHORITY_KEYS

PROJECTION_VERSION = "FPL_V6_DASHBOARD_FACTS_V1"
# Only these sections may ever be allowlisted. Anything else (picks, plans, news bodies) cannot be requested.
PERMITTED_SECTIONS = ("health", "identity", "coverage", "provenance", "official_facts")
OPTIONAL_SECTIONS = ("news",)
_FORBIDDEN_NAME = re.compile(
    r"(pick|manager_plan|plan|token|secret|password|credential|authoriz|api_key|apikey|cookie|"
    r"scheduler_control|dispatch|licen[sc]ed|raw_provider|private)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(r"(ghp_[A-Za-z0-9]{8,}|github_pat_|sk-[A-Za-z0-9]{8,}|Bearer\s+\S{8,}|-----BEGIN)")


class ProjectionBoundaryError(ValueError):
    """Raised when input would cross the facts-only boundary. The message never contains values."""


def _check(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _FORBIDDEN_NAME.search(str(key)):
                raise ProjectionBoundaryError(f"forbidden field name at {path}")
            _check(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check(item, f"{path}[{index}]")
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise ProjectionBoundaryError(f"secret-like value at {path}")


def _select(section: Any, fields: list[str], name: str) -> dict[str, Any]:
    if not isinstance(section, Mapping):
        return {}
    chosen = {field: section[field] for field in fields if field in section}
    _check(chosen, name)
    return chosen


def _status(snapshot: Mapping[str, Any]) -> str:
    assessment = snapshot.get("assessment")
    if not isinstance(assessment, Mapping):
        return "UNKNOWN"
    identity = snapshot.get("identity")
    if isinstance(identity, Mapping) and identity.get("consistent") is False:
        return "IDENTITY_UNVERIFIED"
    state = assessment.get("state")
    if state == "FRESH" and assessment.get("usable") is True:
        return "FRESH"
    if state in {"STALE", "INVALID"}:
        return state
    return "UNKNOWN"


def build_dashboard_facts_projection(
    validated_snapshot: Mapping[str, Any],
    allowlist: Mapping[str, list[str]],
    *,
    now: str,
) -> dict[str, Any]:
    unknown_sections = [name for name in allowlist if name not in PERMITTED_SECTIONS]
    if unknown_sections:
        raise ProjectionBoundaryError("allowlist requests a section that is not permitted")
    for name, fields in allowlist.items():
        if any(_FORBIDDEN_NAME.search(str(field)) for field in fields):
            raise ProjectionBoundaryError(f"allowlist requests a forbidden field in {name}")
    snapshot = validated_snapshot if isinstance(validated_snapshot, Mapping) else {}
    sections = {name: _select(snapshot.get(name), list(fields), name) for name, fields in allowlist.items()}
    assessment = snapshot.get("assessment") if isinstance(snapshot.get("assessment"), Mapping) else {}
    optional = snapshot.get("optional") if isinstance(snapshot.get("optional"), Mapping) else {}
    return {
        "version": PROJECTION_VERSION,
        "generated_for": now,
        # Core status depends only on the validated snapshot; optional sections never gate it.
        "status": _status(snapshot),
        "snapshot_generated_at": assessment.get("generated_at"),
        "snapshot_age_minutes": assessment.get("age_minutes"),
        "freshness_basis": assessment.get("freshness_basis"),
        "sections": sections,
        "optional_sections": {
            name: {"available": isinstance(optional.get(name), Mapping) and optional[name].get("status") == "AVAILABLE"}
            for name in OPTIONAL_SECTIONS
        },
        "authority": {"role": "FACTS_ONLY", **{key: "NONE" for key in ZERO_AUTHORITY_KEYS}},
        "publication": {"public_export": False, "additive": True},
    }
