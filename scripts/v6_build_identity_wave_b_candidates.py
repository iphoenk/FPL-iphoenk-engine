#!/usr/bin/env python3
"""Build deterministic V6 Identity Wave-B gap-closure candidates.

This utility is intentionally OFFLINE and BUILD-TIME ONLY. It never performs
network requests and never uses player names, aliases, DOB, fuzzy matching, or
probabilistic matching.

Primary safe route for Understat:

    Official FPL bootstrap.elements[].code
      == Reep-v1 canonical bridge opta/person_numeric
      -> Reep-v1 stable entity
      -> Reep-v1 canonical bridge understat/player
      -> Understat native player id

Secondary frozen fallback, used only when the primary route has no anchor:

    Official FPL bootstrap.elements[].code
      == frozen Reep-v0 people.csv key_opta_numeric
      -> frozen verified key_transfermarkt
      == Reep-v1 canonical bridge transfermarkt/spieler
      -> Reep-v1 stable entity
      -> Reep-v1 canonical bridge understat/player
      -> Understat native player id

Reep-v1 opta/person_numeric is a canonical bridge namespace in the pinned bridge
artifact. The older overlay label ``opta_numeric`` is NOT used here.

The output is a REVIEW CANDIDATE artifact, not a runtime join table. Promotion
into config/v6/verified_crosswalks.json requires review and provenance retention.
FotMob and StatMuse are deliberately not auto-promoted here because the pinned
v1 release does not expose an equivalent safe canonical bridge path for them.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

REEP_V1_STAMP = "20260907T201034Z"
REEP_V1_MANIFEST_SHA256 = "65356d7522832ea58c19993a95eb31ceb9d6e22e3ff518014387734b13e43529"
REEP_V1_BRIDGES_SHA256 = "a03aef520a454bdcd181b5b332b91e7b41ee57f4914e6e2c456cf49a8b86a735"
REEP_V0_PEOPLE_BLOB = "dc4441b1f94f05c36b807ed23f3a2b7dede5878d"
METHOD = "REEP_V1_OPTA_PERSON_NUMERIC_TO_UNDERSTAT"
FALLBACK_METHOD = "REEP_V0_OPTA_TO_TRANSFERMARKT__REEP_V1_TRANSFERMARKT_TO_UNDERSTAT"
JOINABLE = {"EXACT", "VERIFIED_MANUAL"}


class WaveBCandidateError(RuntimeError):
    pass


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _int(value: Any) -> int | None:
    try:
        text = _text(value)
        return int(text) if text is not None else None
    except (TypeError, ValueError):
        return None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WaveBCandidateError(f"unreadable json: {path}") from exc
    if not isinstance(value, dict):
        raise WaveBCandidateError(f"expected json object: {path}")
    return value


def _official_code_to_element(bootstrap: dict[str, Any]) -> dict[int, int]:
    rows = bootstrap.get("elements")
    if not isinstance(rows, list) or not rows:
        raise WaveBCandidateError("Official FPL bootstrap has no elements")
    out: dict[int, int] = {}
    seen_elements: dict[int, int] = {}
    duplicate_codes: set[int] = set()
    duplicate_elements: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = _int(row.get("code"))
        element_id = _int(row.get("id"))
        if code is None or code <= 0 or element_id is None or element_id <= 0:
            continue
        if code in out and out[code] != element_id:
            duplicate_codes.add(code)
        if element_id in seen_elements and seen_elements[element_id] != code:
            duplicate_elements.add(element_id)
        out[code] = element_id
        seen_elements[element_id] = code
    if duplicate_codes:
        raise WaveBCandidateError(f"duplicate Official FPL codes: {sorted(duplicate_codes)[:10]}")
    if duplicate_elements:
        raise WaveBCandidateError(
            f"Official FPL element ids mapped to conflicting codes: {sorted(duplicate_elements)[:10]}"
        )
    if not out:
        raise WaveBCandidateError("Official FPL bootstrap exposes no usable code/element pairs")
    return out


def _observed_unmapped(dataset: dict[str, Any], source_id: str) -> set[str]:
    if dataset.get("source_id") != source_id:
        raise WaveBCandidateError(f"unexpected source dataset: expected {source_id}")
    rows = ((dataset.get("record_groups") or {}).get("players") or [])
    observed: set[str] = set()
    duplicate: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        native = _text(row.get("source_native_id"))
        if native is None:
            raise WaveBCandidateError(f"{source_id}: observed row missing native id")
        if native in observed:
            duplicate.add(native)
        observed.add(native)
    if duplicate:
        raise WaveBCandidateError(f"{source_id}: duplicate observed native ids: {sorted(duplicate)[:10]}")

    return {
        _text(row.get("source_native_id"))
        for row in rows
        if isinstance(row, dict)
        and _text(row.get("source_native_id")) is not None
        and not (
            str(row.get("identity_status") or "") in JOINABLE
            and _int(row.get("official_element_id")) is not None
        )
    }


def _v0_official_to_transfermarkt(path: Path, official_codes: set[int]) -> dict[int, str]:
    try:
        handle = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise WaveBCandidateError(f"unreadable Reep v0 people csv: {path}") from exc

    out: dict[int, str] = {}
    reverse: dict[str, int] = {}
    conflicts: list[str] = []
    with handle:
        reader = csv.DictReader(handle)
        required = {"type", "key_opta_numeric", "key_transfermarkt"}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise WaveBCandidateError(f"Reep v0 people CSV missing columns: {missing}")
        for row in reader:
            if str(row.get("type") or "").strip().lower() != "player":
                continue
            code = _int(row.get("key_opta_numeric"))
            tm = _text(row.get("key_transfermarkt"))
            if code is None or code not in official_codes or tm is None:
                continue
            if code in out and out[code] != tm:
                conflicts.append(f"official_code:{code}")
                continue
            other = reverse.get(tm)
            if other is not None and other != code:
                conflicts.append(f"transfermarkt:{tm}")
                continue
            out[code] = tm
            reverse[tm] = code
    if conflicts:
        raise WaveBCandidateError(f"v0 anchor conflicts fail closed: {sorted(set(conflicts))[:20]}")
    return out


def _read_v1_bridge_indexes(
    path: Path,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return Opta numeric -> Reep-v1, Transfermarkt -> Reep-v1, Reep-v1 -> Understat."""
    try:
        handle = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise WaveBCandidateError(f"unreadable Reep v1 bridges csv: {path}") from exc

    opta_numeric_to_reep: dict[str, str] = {}
    tm_to_reep: dict[str, str] = {}
    reep_to_understat: dict[str, str] = {}
    reep_to_current_opta: dict[str, str] = {}
    conflicts: list[str] = []
    with handle:
        reader = csv.DictReader(handle)
        required = {"provider", "namespace", "external_id", "reep_id"}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise WaveBCandidateError(f"Reep v1 bridges CSV missing columns: {missing}")
        for row in reader:
            provider = str(row.get("provider") or "").strip().lower()
            namespace = str(row.get("namespace") or "").strip().lower()
            external_id = _text(row.get("external_id"))
            reep_id = _text(row.get("reep_id"))
            if external_id is None or reep_id is None:
                continue

            if provider == "opta" and namespace == "person_numeric":
                existing = opta_numeric_to_reep.get(external_id)
                if existing is not None and existing != reep_id:
                    conflicts.append(f"opta_person_numeric:{external_id}")
                else:
                    opta_numeric_to_reep[external_id] = reep_id

                previous_opta = reep_to_current_opta.get(reep_id)
                if previous_opta is not None and previous_opta != external_id:
                    conflicts.append(f"opta_reep:{reep_id}")
                else:
                    reep_to_current_opta[reep_id] = external_id

            elif provider == "transfermarkt" and namespace in {"spieler", "player"}:
                existing = tm_to_reep.get(external_id)
                if existing is not None and existing != reep_id:
                    conflicts.append(f"transfermarkt:{external_id}")
                else:
                    tm_to_reep[external_id] = reep_id

            elif provider == "understat" and namespace == "player":
                existing = reep_to_understat.get(reep_id)
                if existing is not None and existing != external_id:
                    conflicts.append(f"understat_reep:{reep_id}")
                else:
                    reep_to_understat[reep_id] = external_id

    if conflicts:
        raise WaveBCandidateError(f"Reep v1 bridge conflicts fail closed: {sorted(set(conflicts))[:20]}")
    return opta_numeric_to_reep, tm_to_reep, reep_to_understat


def _candidate(
    *,
    native: str,
    code: int,
    element_id: int,
    method: str,
    reep_v1_id: str,
    bridge_path: list[str],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_id": "understat",
        "source_native_id": int(native) if native.isdigit() else native,
        "official_fpl_code": code,
        "official_element_id": element_id,
        "verification_status": "CANDIDATE_REQUIRES_REVIEW",
        "verification_method": method,
        "bridge_path": bridge_path,
        "evidence": {
            "reep_v1_release": REEP_V1_STAMP,
            "reep_v1_manifest_sha256": REEP_V1_MANIFEST_SHA256,
            "reep_v1_bridges_sha256": REEP_V1_BRIDGES_SHA256,
            "reep_v1_id": reep_v1_id,
            "observed_native_id_in_current_dataset": True,
            "name_matching_used": False,
            "fuzzy_matching_used": False,
            **evidence,
        },
    }


def build_understat_candidates(
    *,
    bootstrap: dict[str, Any],
    understat_dataset: dict[str, Any],
    reep_v0_people: Path,
    reep_v1_bridges: Path,
) -> dict[str, Any]:
    code_to_element = _official_code_to_element(bootstrap)
    official_codes = set(code_to_element)
    gaps = _observed_unmapped(understat_dataset, "understat")
    official_to_tm = _v0_official_to_transfermarkt(reep_v0_people, official_codes)
    opta_to_reep, tm_to_reep, reep_to_understat = _read_v1_bridge_indexes(reep_v1_bridges)

    candidates: list[dict[str, Any]] = []
    seen_native: set[str] = set()
    seen_element: set[int] = set()

    direct_candidates = 0
    for code, element_id in sorted(code_to_element.items()):
        reep_v1_id = opta_to_reep.get(str(code))
        if reep_v1_id is None:
            continue
        understat_native = reep_to_understat.get(reep_v1_id)
        if understat_native is None or understat_native not in gaps:
            continue
        if understat_native in seen_native:
            raise WaveBCandidateError(f"candidate native id duplicated: understat:{understat_native}")
        if element_id in seen_element:
            raise WaveBCandidateError(f"candidate Official element duplicated: {element_id}")
        seen_native.add(understat_native)
        seen_element.add(element_id)
        candidates.append(
            _candidate(
                native=understat_native,
                code=code,
                element_id=element_id,
                method=METHOD,
                reep_v1_id=reep_v1_id,
                bridge_path=[
                    "official_fpl.bootstrap.elements.code",
                    "reep_v1:opta/person_numeric",
                    "reep_v1:understat/player",
                    "official_fpl.bootstrap.elements.id",
                ],
                evidence={
                    "opta_person_numeric": str(code),
                    "primary_canonical_bridge_used": True,
                },
            )
        )
        direct_candidates += 1

    unresolved_anchor = 0
    fallback_candidates = 0
    for code, tm in sorted(official_to_tm.items()):
        element_id = code_to_element[code]
        if element_id in seen_element:
            continue
        reep_v1_id = tm_to_reep.get(tm)
        if reep_v1_id is None:
            unresolved_anchor += 1
            continue
        understat_native = reep_to_understat.get(reep_v1_id)
        if (
            understat_native is None
            or understat_native not in gaps
            or understat_native in seen_native
        ):
            continue
        seen_native.add(understat_native)
        seen_element.add(element_id)
        candidates.append(
            _candidate(
                native=understat_native,
                code=code,
                element_id=element_id,
                method=FALLBACK_METHOD,
                reep_v1_id=reep_v1_id,
                bridge_path=[
                    "official_fpl.bootstrap.elements.code",
                    "reep_v0.key_opta_numeric",
                    "reep_v0.key_transfermarkt",
                    "reep_v1:transfermarkt/spieler",
                    "reep_v1:understat/player",
                    "official_fpl.bootstrap.elements.id",
                ],
                evidence={
                    "reep_v0_people_blob": REEP_V0_PEOPLE_BLOB,
                    "transfermarkt_player_id": tm,
                    "primary_canonical_bridge_used": False,
                },
            )
        )
        fallback_candidates += 1

    candidates.sort(key=lambda row: (int(row["official_element_id"]), str(row["source_native_id"])))
    candidate_natives = {str(row["source_native_id"]) for row in candidates}
    unresolved_gaps = sorted(gaps - candidate_natives)
    current_opta_anchors = sum(1 for code in official_codes if str(code) in opta_to_reep)

    return {
        "schema_version": 2,
        "semantic_class": "IDENTITY_WAVE_B_CANDIDATE_REVIEW",
        "canonical_authority": "official_fpl",
        "provider": "understat",
        "method": METHOD,
        "fallback_method": FALLBACK_METHOD,
        "candidate_count": len(candidates),
        "direct_candidate_count": direct_candidates,
        "fallback_candidate_count": fallback_candidates,
        "observed_unmapped_before": len(gaps),
        "projected_observed_unmapped_after_reviewed_promotion": len(unresolved_gaps),
        "candidate_observed_join_gain": len(candidates),
        "unresolved_observed_native_ids": unresolved_gaps,
        "official_codes_with_v1_opta_person_numeric_anchor": current_opta_anchors,
        "official_codes_with_v0_tm_anchor": len(official_to_tm),
        "v0_tm_anchors_missing_in_v1": unresolved_anchor,
        "candidates": candidates,
        "governance": {
            "data_only": True,
            "runtime_network_dependency": False,
            "build_time_only": True,
            "auto_promotion_to_runtime_join": False,
            "review_required_before_promotion": True,
            "name_matching_allowed": False,
            "fuzzy_matching_allowed": False,
            "v0_and_v1_reep_ids_assumed_interchangeable": False,
            "primary_bridge": "reep_v1:opta/person_numeric",
            "secondary_bridge": "reep_v0_opta_to_transfermarkt_then_reep_v1",
            "overlay_opta_numeric_used": False,
            "conflicts_fail_closed": True,
            "fotmob_auto_closure_supported": False,
            "statmuse_auto_closure_supported": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", type=Path, required=True)
    parser.add_argument("--understat-dataset", type=Path, required=True)
    parser.add_argument("--reep-v0-people", type=Path, required=True)
    parser.add_argument("--reep-v1-bridges", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = build_understat_candidates(
        bootstrap=_load_json(args.bootstrap),
        understat_dataset=_load_json(args.understat_dataset),
        reep_v0_people=args.reep_v0_people,
        reep_v1_bridges=args.reep_v1_bridges,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
