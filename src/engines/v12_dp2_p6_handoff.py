from __future__ import annotations

"""Occurrence-bound D-P2 -> P6 transport contract."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any


class HandoffError(RuntimeError):
    pass


@dataclass(frozen=True)
class P6Handoff:
    report_kind: str
    logical_slot: str
    freeze_target_at: str
    occurrence_id: str
    production_sha: str
    runtime_data_sha: str
    gw_fixture_fingerprint: str
    model_version: str
    schema_version: str
    projection_lineage_fingerprint: str
    current15_fingerprint: str
    owner_context_fingerprint: str
    mc_authority: str

    def as_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


def _aware(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HandoffError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HandoffError(f"{label} must be timezone-aware")
    return parsed


def occurrence_id(*, report_kind: str, logical_slot: str) -> str:
    payload = json.dumps(
        {"report_kind": str(report_kind).lower(), "logical_slot": str(logical_slot)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_handoff(
    *,
    report_kind: str,
    logical_slot: str,
    freeze_target_at: str,
    production_sha: str,
    runtime_data_sha: str,
    identity: Mapping[str, Any],
) -> P6Handoff:
    logical = _aware(logical_slot, "logical_slot")
    freeze = _aware(freeze_target_at, "freeze_target_at")
    if freeze > logical:
        raise HandoffError("freeze target must not be after visible occurrence")
    required = (
        "gw_fixture_fingerprint", "model_version", "schema_version",
        "projection_lineage_fingerprint", "current15_fingerprint",
        "owner_context_fingerprint", "mc_authority",
    )
    missing = [key for key in required if not str(identity.get(key) or "").strip()]
    if missing:
        raise HandoffError(f"missing P6 handoff identity: {missing}")
    return P6Handoff(
        report_kind=str(report_kind).lower(),
        logical_slot=logical.isoformat(),
        freeze_target_at=freeze.isoformat(),
        occurrence_id=occurrence_id(report_kind=report_kind, logical_slot=logical.isoformat()),
        production_sha=str(production_sha),
        runtime_data_sha=str(runtime_data_sha),
        gw_fixture_fingerprint=str(identity["gw_fixture_fingerprint"]),
        model_version=str(identity["model_version"]),
        schema_version=str(identity["schema_version"]),
        projection_lineage_fingerprint=str(identity["projection_lineage_fingerprint"]),
        current15_fingerprint=str(identity["current15_fingerprint"]),
        owner_context_fingerprint=str(identity["owner_context_fingerprint"]),
        mc_authority=str(identity["mc_authority"]),
    )


def validate_snapshot_binding(
    handoff: P6Handoff,
    *,
    snapshot: Mapping[str, Any],
) -> None:
    expected = {
        "logical_slot": handoff.logical_slot,
        "production_sha": handoff.production_sha,
        "runtime_data_sha": handoff.runtime_data_sha,
        "gw_fixture_fingerprint": handoff.gw_fixture_fingerprint,
    }
    for key, value in expected.items():
        observed = str(snapshot.get(key) or "")
        if observed != str(value):
            raise HandoffError(
                f"stale/cross-occurrence snapshot rejected: {key}={observed!r} expected {value!r}"
            )
    if str(snapshot.get("occurrence_id") or "") != handoff.occurrence_id:
        raise HandoffError("cross-occurrence P6 handoff rejected")
