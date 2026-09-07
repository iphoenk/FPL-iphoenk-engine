from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .season_contract import materialize_season_tokens

ROOT = Path(__file__).resolve().parents[2]
V6_CONFIG_ROOT = (ROOT / "config" / "v6").resolve()

_REQUIRED_ADMISSION = {
    "cost": "ZERO",
    "account_required": False,
    "login_required": False,
    "private_api_key_required": False,
    "private_token_required": False,
}


class SourcePolicyError(ValueError):
    pass


def normalize_addition_admission(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply one fail-closed access contract to every additive V6 source."""
    out = deepcopy(payload)
    admission = dict(out.get("admission_policy") or {})
    for key, expected in _REQUIRED_ADMISSION.items():
        if admission.get(key) != expected:
            raise SourcePolicyError(f"V6 source addition admission policy must set {key}={expected!r}")
    if admission.get("auth_block_allowed") is not False:
        raise SourcePolicyError("V6 source addition admission policy must forbid private auth blocks")

    normalized: list[dict[str, Any]] = []
    for source in out.get("sources") or []:
        row = deepcopy(source)
        source_id = str(row.get("id") or "<missing>")
        if row.get("auth"):
            raise SourcePolicyError(f"V6 additive source cannot declare private auth: {source_id}")
        access = {
            **{key: admission[key] for key in _REQUIRED_ADMISSION},
            "shared_public_key": False,
            **dict(row.get("access") or {}),
        }
        for key, expected in _REQUIRED_ADMISSION.items():
            if access.get(key) != expected:
                raise SourcePolicyError(
                    f"V6 additive source violates no-cost/no-auth admission: {source_id}:{key}={access.get(key)!r}"
                )
        if access.get("shared_public_key") is True and not str(access.get("public_shared_access_segment") or "").strip():
            raise SourcePolicyError(
                f"V6 additive shared-public-key source must declare its public access segment: {source_id}"
            )
        row["access"] = access
        normalized.append(row)

    out["sources"] = normalized
    return out


def _safe_config_path(value: Any) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise SourcePolicyError("params_from_records.path is required")
    path = (ROOT / raw).resolve()
    try:
        path.relative_to(V6_CONFIG_ROOT)
    except ValueError as exc:
        raise SourcePolicyError(f"request parameter source escapes config/v6: {raw}") from exc
    if not path.is_file():
        raise SourcePolicyError(f"request parameter source does not exist: {raw}")
    return path


def _materialize_request(request: dict[str, Any]) -> dict[str, Any]:
    spec = request.get("params_from_records")
    if not spec:
        return deepcopy(request)
    if not isinstance(spec, dict):
        raise SourcePolicyError("params_from_records must be an object")
    if str(spec.get("format") or "csv").lower() != "csv":
        raise SourcePolicyError("only csv params_from_records format is supported")

    path = _safe_config_path(spec.get("path"))
    external = json.loads(path.read_text(encoding="utf-8"))
    records_key = str(spec.get("records_key") or "").strip()
    records = external.get(records_key) if records_key else None
    if not isinstance(records, list) or not records:
        raise SourcePolicyError(f"request parameter source has no records at key {records_key!r}")
    fields = dict(spec.get("fields") or {})
    if not fields:
        raise SourcePolicyError("params_from_records.fields cannot be empty")

    out = deepcopy(request)
    params = dict(out.get("params") or {})
    for target_param, record_field in fields.items():
        target = str(target_param)
        field = str(record_field)
        if target in params:
            raise SourcePolicyError(
                f"request parameter {target!r} is both static and config-materialized"
            )
        values: list[str] = []
        for index, record in enumerate(records):
            if not isinstance(record, dict) or field not in record:
                raise SourcePolicyError(
                    f"request parameter source missing field {field!r} at record {index}"
                )
            values.append(str(record[field]))
        params[target] = ",".join(values)
    out["params"] = params
    return out


def materialize_config_request_params(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve V6 season tokens and config-backed provider request parameters."""
    out = materialize_season_tokens(deepcopy(payload))
    sources: list[dict[str, Any]] = []
    for source in out.get("sources") or []:
        row = deepcopy(source)
        row["requests"] = [_materialize_request(request) for request in row.get("requests") or []]
        sources.append(row)
    out["sources"] = sources
    return out
