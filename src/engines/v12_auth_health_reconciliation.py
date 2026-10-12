"""Slot-bound auth health reconciliation. Metadata only; never exports credentials.

Public legacy authentication remains truthful and independent of the protected
rotating-OIDC publisher. Only same-occurrence, hash-verified private facts may
authorize the effective authenticated CURRENT15 health claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


def _read(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("auth health input must be a JSON object")
    return obj


def _iso(value: Any) -> datetime:
    obj = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if obj.tzinfo is None or obj.utcoffset() is None:
        raise ValueError("auth health timestamp must have an offset")
    return obj.astimezone(timezone.utc)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def slot_key(slot: str, kind: str) -> str:
    _iso(slot)
    if kind not in {"full_master", "match_mode", "05:30_price", "deadline_review"}:
        raise ValueError("unsupported private prefetch kind")
    safe = slot.replace("-", "").replace(":", "").replace("T", "_").replace("+", "_plus_")
    if not all(c.isalnum() or c == "_" for c in safe):
        raise ValueError("unsafe slot token")
    return f"{kind}__{safe}"


def _identity(manifest: Mapping[str, Any], slot: str) -> None:
    if _iso(manifest.get("target_logical_report_slot")) != _iso(slot):
        raise ValueError("wrong prefetch occurrence")
    if int(manifest.get("entry_id") or 0) <= 0:
        raise ValueError("prefetch entry identity absent")
    if int(manifest.get("gw") or 0) <= 0:
        raise ValueError("prefetch gameweek absent")
    if not str(manifest.get("report_prefetch_run_id") or ""):
        raise ValueError("prefetch run ID absent")


def _eligible_team(team: Mapping[str, Any], manifest: Mapping[str, Any], slot: str) -> bool:
    try:
        generated = _iso(team["generated_at"])
        report_slot = _iso(slot)
        players = team["players"]
        ids = [int(player["element_id"]) for player in players]
        availability = dict(team.get("availability") or {})
        return (
            str(team.get("auth_state")) == "AUTH_AVAILABLE"
            and str(team.get("squad_state")) == "AUTHENTICATED_CURRENT_TEAM"
            and int(team.get("entry_id") or 0) == int(manifest.get("entry_id") or 0)
            and int(team.get("gw") or 0) == int(manifest.get("gw") or 0)
            and len(ids) == len(set(ids)) == 15
            and min(ids) > 0
            and type(team.get("bank")) is int
            and all(type(p.get("purchase_price")) is int and type(p.get("selling_price")) is int for p in players)
            and availability.get("authenticated_state") == "AUTH_AVAILABLE"
            and (team.get("governance") or {}).get("auth_bypass_used") is False
            and report_slot - timedelta(minutes=15) <= generated <= report_slot + timedelta(minutes=15)
            and generated <= datetime.now(timezone.utc) + timedelta(minutes=2)
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def make_private_attestation(
    manifest: Mapping[str, Any],
    team: Mapping[str, Any],
    *,
    team_sha256: str,
    slot: str,
    run_id: str,
) -> dict[str, Any]:
    _identity(manifest, slot)
    if len(team_sha256) != 64 or not all(c in "0123456789abcdef" for c in team_sha256):
        raise ValueError("invalid private team SHA256")
    if not str(run_id).isdigit() or str(run_id) != str(manifest["report_prefetch_run_id"]):
        raise ValueError("publisher run not bound to producer")
    good = _eligible_team(team, manifest, slot)
    return {
        "schema_version": 1,
        "report_kind": str(manifest["report_kind"]),
        "report_slot": slot,
        "prefetch_run_id": str(run_id),
        "entry_id": int(manifest["entry_id"]),
        "gw": int(manifest["gw"]),
        "authenticated_current15": good,
        "private_auth_state": "AUTH_AVAILABLE" if good else "UNVERIFIED",
        "team_sha256": team_sha256,
        "team_generated_at": str(team.get("generated_at") or ""),
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "source": "V6_PROTECTED_PRIVATE_PERSONAL_PUBLISHER",
    }


def reconcile(
    manifest: Mapping[str, Any],
    attestation: Mapping[str, Any] | None,
    team: Mapping[str, Any],
    *,
    team_sha256: str,
    attestation_sha256: str,
    private_commit: str,
    slot: str,
) -> dict[str, Any]:
    _identity(manifest, slot)
    legacy = str(manifest.get("report_auth_state") or "UNAVAILABLE").upper()
    result = {
        "schema_version": 1,
        "report_slot": slot,
        "prefetch_run_id": str(manifest["report_prefetch_run_id"]),
        "legacy_public_auth_state": legacy,
        "private_rotating_auth_state": "UNVERIFIED",
        "effective_auth_state": "UNVERIFIED",
        "reconciliation_status": "UNVERIFIED",
        "reason": "PRIVATE_ATTESTATION_NOT_VERIFIED",
        "private_commit": private_commit if len(private_commit) == 40 else "UNVERIFIED",
        "private_attestation_sha256": attestation_sha256,
    }
    att = dict(attestation or {})
    if not att:
        return result
    try:
        eligible = (
            att.get("schema_version") == 1
            and att.get("source") == "V6_PROTECTED_PRIVATE_PERSONAL_PUBLISHER"
            and _iso(att["report_slot"]) == _iso(slot)
            and att.get("report_kind") == manifest.get("report_kind")
            and str(att.get("prefetch_run_id")) == str(manifest["report_prefetch_run_id"])
            and int(att.get("entry_id") or 0) == int(manifest["entry_id"])
            and int(att.get("gw") or 0) == int(manifest["gw"])
            and att.get("authenticated_current15") is True
            and att.get("private_auth_state") == "AUTH_AVAILABLE"
            and att.get("team_sha256") == team_sha256
            and _iso(att["team_generated_at"]) == _iso(team["generated_at"])
            and _iso(att["issued_at"]) >= _iso(att["team_generated_at"])
            and _eligible_team(team, manifest, slot)
            and len(private_commit) == 40
            and len(attestation_sha256) == 64
        )
    except (TypeError, ValueError, KeyError):
        eligible = False
    if eligible:
        result.update({
            "private_rotating_auth_state": "AUTH_AVAILABLE",
            "effective_auth_state": "AUTH_AVAILABLE",
            "reconciliation_status": "PASS",
            "reason": "EXACT_SLOT_PRIVATE_OIDC_BOUND",
        })
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["attest", "reconcile"])
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--team", type=Path, required=True)
    p.add_argument("--slot", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--run-id", default="")
    p.add_argument("--attestation", type=Path)
    p.add_argument("--private-commit", default="")
    a = p.parse_args()
    manifest = _read(a.manifest)
    team = _read(a.team)
    if a.mode == "attest":
        result = make_private_attestation(
            manifest, team, team_sha256=_sha(a.team), slot=a.slot, run_id=a.run_id,
        )
    else:
        if a.attestation is None:
            raise ValueError("attestation path required")
        att = _read(a.attestation) if a.attestation.is_file() else None
        result = reconcile(
            manifest, att, team, team_sha256=_sha(a.team),
            attestation_sha256=_sha(a.attestation) if att else "",
            private_commit=a.private_commit, slot=a.slot,
        )
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("PRIVATE_AUTH_RECONCILIATION=" + (
        result.get("reconciliation_status") or result.get("private_auth_state") or "UNVERIFIED"
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
