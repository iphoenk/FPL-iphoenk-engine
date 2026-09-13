#!/usr/bin/env python3
"""Build V6 player crosswalk rows from Official FPL code + a pinned Reep export.

This is an offline/build-time utility. It never performs network requests and never
uses player names, DOBs, aliases, fuzzy matching, or probabilistic matching.

Canonical join:
    Official FPL bootstrap.elements[].code
        == Reep v0 people.csv key_opta_numeric
        -> provider-native id

The output is a V6 verified_crosswalks.json-compatible document. Partial provider
coverage is preserved truthfully; missing mappings remain unmapped at runtime.
"""
from __future__ import annotations

import argparse
import csv
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

REEP_COMMIT = "0ec59faa5d81615b7a8200ae6121023a3bc14ce3"
REEP_PEOPLE_BLOB = "dc4441b1f94f05c36b807ed23f3a2b7dede5878d"
REEP_RELEASE = "2026.25"
REEP_RELEASED_AT = "2026-06-21T00:00:00+00:00"
PROVIDERS = {
    "understat": "key_understat",
    "fotmob": "key_fotmob",
    "statmuse": "key_statmuse_pl",
}
METHOD = "REEP_V0_PINNED_OPTA_NUMERIC_TO_PROVIDER_ID"


class CrosswalkBuildError(RuntimeError):
    pass


def _int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _native(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CrosswalkBuildError(f"unreadable json: {path}") from exc
    if not isinstance(payload, dict):
        raise CrosswalkBuildError(f"expected object: {path}")
    return payload


def _official_codes(bootstrap: dict[str, Any]) -> set[int]:
    elements = bootstrap.get("elements")
    if not isinstance(elements, list) or not elements:
        raise CrosswalkBuildError("Official bootstrap has no elements")
    codes: set[int] = set()
    duplicates: set[int] = set()
    for row in elements:
        if not isinstance(row, dict):
            continue
        code = _int(row.get("code"))
        if code is None or code <= 0:
            continue
        if code in codes:
            duplicates.add(code)
        codes.add(code)
    if duplicates:
        raise CrosswalkBuildError(f"duplicate Official FPL codes: {sorted(duplicates)[:10]}")
    if not codes:
        raise CrosswalkBuildError("Official bootstrap exposes no usable code values")
    return codes


def _read_reep_rows(path: Path, official_codes: set[int]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {provider: [] for provider in PROVIDERS}
    seen_official: dict[str, set[int]] = {provider: set() for provider in PROVIDERS}
    seen_native: dict[str, set[str]] = {provider: set() for provider in PROVIDERS}
    duplicate_official: dict[str, set[int]] = {provider: set() for provider in PROVIDERS}
    duplicate_native: dict[str, set[str]] = {provider: set() for provider in PROVIDERS}

    try:
        handle = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise CrosswalkBuildError(f"unreadable Reep people csv: {path}") from exc

    with handle:
        reader = csv.DictReader(handle)
        required = {"reep_id", "type", "key_opta_numeric", *PROVIDERS.values()}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise CrosswalkBuildError(f"Reep CSV missing columns: {missing}")

        for row in reader:
            if str(row.get("type") or "").strip().lower() != "player":
                continue
            code = _int(row.get("key_opta_numeric"))
            if code is None or code not in official_codes:
                continue
            for provider, column in PROVIDERS.items():
                native = _native(row.get(column))
                if native is None:
                    continue
                if code in seen_official[provider]:
                    duplicate_official[provider].add(code)
                    continue
                if native in seen_native[provider]:
                    duplicate_native[provider].add(native)
                    continue
                seen_official[provider].add(code)
                seen_native[provider].add(native)
                out[provider].append(
                    {
                        "official_fpl_code": code,
                        "source_native_id": int(native) if native.isdigit() else native,
                        "reep_id": row.get("reep_id"),
                    }
                )

    collisions = {
        provider: {
            "official_codes": sorted(duplicate_official[provider]),
            "native_ids": sorted(duplicate_native[provider]),
        }
        for provider in PROVIDERS
        if duplicate_official[provider] or duplicate_native[provider]
    }
    if collisions:
        raise CrosswalkBuildError(f"Reep provider collisions fail closed: {collisions}")

    for provider in out:
        out[provider].sort(key=lambda row: int(row["official_fpl_code"]))
    return out


def build(
    *,
    bootstrap: dict[str, Any],
    reep_csv: Path,
    base_config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if base_config.get("canonical_authority") != "official_fpl":
        raise CrosswalkBuildError("base config canonical_authority must be official_fpl")
    if base_config.get("fuzzy_matching_allowed") is not False:
        raise CrosswalkBuildError("base config must forbid fuzzy matching")

    official_codes = _official_codes(bootstrap)
    provider_rows = _read_reep_rows(reep_csv, official_codes)
    output = deepcopy(base_config)
    sources = output.setdefault("sources", {})
    evidence = [
        f"github:withqwerty/reep@{REEP_COMMIT}:data/people.csv",
        f"git_blob_sha256_contract:{REEP_PEOPLE_BLOB}",
        f"reep_v0_release:{REEP_RELEASE}",
        "official_fpl:bootstrap.elements.code",
    ]

    report: dict[str, Any] = {
        "schema_version": 1,
        "canonical_authority": "official_fpl",
        "join_key": "bootstrap.elements.code == key_opta_numeric",
        "name_matching_used": False,
        "official_player_count": len(official_codes),
        "providers": {},
    }

    for provider, rows in provider_rows.items():
        source = deepcopy(sources.get(provider) or {})
        source.update(
            {
                "verification_status": "VERIFIED_MANUAL",
                "player_verification_method": METHOD,
                "player_crosswalk_release": REEP_RELEASE,
                "player_crosswalk_verified_at": REEP_RELEASED_AT,
                "player_crosswalk_commit": REEP_COMMIT,
                "player_crosswalk_blob": REEP_PEOPLE_BLOB,
                "player_crosswalk_canonical_anchor": "official_fpl.bootstrap.elements.code",
                "player_crosswalk_provider_column": PROVIDERS[provider],
                "player_crosswalk_name_matching": False,
                "evidence": sorted(set([*(source.get("evidence") or []), *evidence])),
                "players": rows,
            }
        )
        scopes = list(source.get("entity_scopes") or [])
        if "PLAYER" not in scopes:
            scopes.append("PLAYER")
        source["entity_scopes"] = sorted(set(scopes))
        sources[provider] = source
        report["providers"][provider] = {
            "mapped_player_count": len(rows),
            "coverage_ratio": round(len(rows) / len(official_codes), 6) if official_codes else 0.0,
            "unmapped_player_count": max(0, len(official_codes) - len(rows)),
            "verification_release": REEP_RELEASE,
            "verification_timestamp": REEP_RELEASED_AT,
        }

    governance = output.setdefault("governance", {})
    governance.update(
        {
            "player_crosswalk_build_is_offline": True,
            "player_crosswalk_uses_official_code_only": True,
            "player_crosswalk_name_matching_allowed": False,
            "player_crosswalk_duplicate_or_conflict_policy": "FAIL_CLOSED",
            "player_crosswalk_partial_coverage_is_allowed": True,
            "player_crosswalk_provider_ids_are_attributes_not_canonical_keys": True,
        }
    )
    return output, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", type=Path, required=True)
    parser.add_argument("--reep-people", type=Path, required=True)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    output, report = build(
        bootstrap=_load_json(args.bootstrap),
        reep_csv=args.reep_people,
        base_config=_load_json(args.base_config),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
