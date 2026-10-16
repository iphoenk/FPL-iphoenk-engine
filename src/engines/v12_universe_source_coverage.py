"""Read-only, fail-closed Official universe vs provider coverage gate.

Never remove Official FPL players because a provider bridge is absent.
Retrospective observed XI mapping is a separate metric from universe coverage.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _ids(rows: list[Mapping[str, Any]], key: str) -> set[int]:
    found: set[int] = set()
    for row in rows:
        raw = row.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0 or raw in found:
            raise ValueError(f"INVALID_OR_DUPLICATE_{key.upper()}")
        found.add(raw)
    return found


def audit_universe(
    official_players: list[Mapping[str, Any]],
    scanner_player_ids: list[int],
    provider_bridges: list[Mapping[str, Any]],
    *,
    expected_official_count: int = 667,
) -> dict[str, Any]:
    official = _ids(official_players, "id")
    if len(official) != expected_official_count:
        raise ValueError("OFFICIAL_UNIVERSE_SIZE_NOT_ESTABLISHED")
    if len(scanner_player_ids) != len(set(scanner_player_ids)) or any(
        isinstance(i, bool) or not isinstance(i, int) or i <= 0 for i in scanner_player_ids
    ):
        raise ValueError("SCANNER_DUPLICATE_OR_INVALID_ID")
    scanner = set(scanner_player_ids)
    missing = sorted(official - scanner)
    foreign = sorted(scanner - official)
    mapped: set[int] = set()
    natives: set[str] = set()
    for bridge in provider_bridges:
        oid, native = bridge.get("official_element_id"), bridge.get("source_native_id")
        if isinstance(oid, bool) or not isinstance(oid, int) or oid not in official:
            raise ValueError("PROVIDER_BRIDGE_OFFICIAL_ID_INVALID")
        if native is None or not str(native).strip():
            raise ValueError("PROVIDER_BRIDGE_NATIVE_ID_MISSING")
        native_key = str(native).strip()
        if oid in mapped or native_key in natives:
            raise ValueError("PROVIDER_BRIDGE_COLLISION")
        if bridge.get("identity_status") not in {"EXACT", "VERIFIED_MANUAL"}:
            raise ValueError("PROVIDER_BRIDGE_NOT_CERTIFIED")
        mapped.add(oid)
        natives.add(native_key)
    full = not missing and not foreign
    return {
        "contract": "V12_OFFICIAL_FULL_UNIVERSE_COVERAGE_V1",
        "official_count": len(official),
        "scanner_count": len(scanner),
        "scanner_coverage": "PASS" if full else "FAIL",
        "missing_official_ids": missing,
        "foreign_scanner_ids": foreign,
        "verified_provider_bridges_in_universe": len(mapped),
        "provider_unmapped_official_count": len(official - mapped),
        "provider_full_coverage": "PASS" if len(mapped) == len(official) else "PARTIAL",
        "source_fallback": "OFFICIAL_FPL_ONLY_FOR_UNMAPPED",
        "numeric_model_effect": "NONE",
    }
