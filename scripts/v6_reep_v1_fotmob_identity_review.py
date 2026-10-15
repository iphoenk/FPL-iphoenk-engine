#!/usr/bin/env python3
"""Source-verified Reep v1 FotMob-to-Official FPL crosswalk AUDIT ONLY.

Never alters V6 canonical identity, GW7 forecasts or P(start). Requires the
independently published release checksum; no names/fuzzy matching or aliases.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path

RELEASE = "20261005T180536Z"
BRIDGES_SHA256 = "ccfe36b94612890102d89159b82eb92f22245151b4b7ebbf2859e38f069d7731"


def _id(value):
    try:
        n = int(str(value))
        return n if n > 0 and str(n) == str(value) else None
    except (ValueError, TypeError):
        return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for piece in iter(lambda: f.read(1024 * 1024), b""):
            h.update(piece)
    return h.hexdigest()


def native_starter_evidence(fotmob):
    if fotmob.get("source_id") != "fotmob" or fotmob.get("normalization_status") != "NORMALIZED":
        raise ValueError("original V6 normalized FotMob required")
    fixtures = (fotmob.get("record_groups") or {}).get("match_tactics") or []
    verified, observed = defaultdict(set), set()
    if len(fixtures) != 60:
        raise ValueError("GW1-GW6 FotMob 60 source-native matches not established")
    unique_fixtures = set()
    for match in fixtures:
        fixture_id = _id(match.get("official_fixture_id"))
        if not fixture_id or fixture_id in unique_fixtures:
            raise ValueError("missing or duplicate verified fixture")
        unique_fixtures.add(fixture_id)
        for side in match.get("sides") or []:
            expected = 11
            rows = side.get("verified_official_starters") or []
            extra = side.get("unverified_provider_starter_ids") or []
            if len(rows) + len(extra) != expected or side.get("starting_xi_complete") is not True:
                raise ValueError("not exactly eleven source starters per side")
            for row in rows:
                nid, eid = _id(row.get("source_native_player_id")), _id(row.get("official_element_id"))
                if not nid or not eid or row.get("identity_status") not in ("EXACT", "VERIFIED_MANUAL"):
                    raise ValueError("bad existing certified source starter")
                observed.add(nid)
                verified[nid].add(eid)
            for raw in extra:
                nid = _id(raw)
                if not nid:
                    raise ValueError("missing source-native starter ID")
                observed.add(nid)
    if any(len(ids) != 1 for ids in verified.values()):
        raise ValueError("existing source mapping conflict")
    return observed, {k: next(iter(v)) for k, v in verified.items()}


def read_reep_v1(bridges_gz, official_codes, fotmob_ids):
    opta = defaultdict(set)
    native = defaultdict(set)
    with gzip.open(bridges_gz, "rt", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not {"provider", "namespace", "external_id", "reep_id"}.issubset(reader.fieldnames or []):
            raise ValueError("Reep v1 bridge schema mismatch")
        for r in reader:
            rid = str(r.get("reep_id") or "").strip()
            eid = _id(r.get("external_id"))
            if not rid or not eid:
                continue
            p, ns = str(r.get("provider") or ""), str(r.get("namespace") or "")
            if p == "opta" and ns == "person_numeric" and eid in official_codes:
                opta[rid].add(eid)
            elif p == "fotmob" and ns == "person" and eid in fotmob_ids:
                native[rid].add(eid)
    return opta, native


def build_report(official, fotmob, bridges_gz):
    if official.get("source_id") != "official_fpl" or official.get("health") != "GREEN":
        raise ValueError("verified live Official source required")
    elements = ((official.get("official") or {}).get("bootstrap") or {}).get("elements") or []
    code_map = {}
    for player in elements:
        code, eid = _id(player.get("code")), _id(player.get("id"))
        if code and eid:
            if code in code_map and code_map[code] != eid:
                raise ValueError("Official FPL duplicate Opta numeric code")
            code_map[code] = eid
    if len(code_map) < 600:
        raise ValueError("Full Official FPL universe not available")
    starter_native, certified = native_starter_evidence(fotmob)
    league_players = ((fotmob.get("record_groups") or {}).get("players") or [])
    if not isinstance(league_players, list):
        raise ValueError("FotMob source-native league player records unavailable")
    league_native = {_id(p.get("source_native_id")) for p in league_players if isinstance(p, dict)}
    if None in league_native or len(league_native) != len(league_players):
        raise ValueError("missing or duplicated source-native league stats IDs")
    observed = starter_native | league_native
    actual_sha = sha256_file(bridges_gz)
    if actual_sha != BRIDGES_SHA256:
        raise ValueError("Reep v1 20261005T180536Z original compressed CSV SHA256 mismatch")
    opta, native = read_reep_v1(bridges_gz, set(code_map), observed)
    by_native, collisions = defaultdict(set), []
    for rid in set(opta) & set(native):
        if len(opta[rid]) != 1 or len(native[rid]) != 1:
            collisions.append({"reep_id": rid, "opta_codes": sorted(opta[rid]),
                               "native_ids": sorted(native[rid])})
            continue
        source_id = next(iter(native[rid]))
        official_id = code_map[next(iter(opta[rid]))]
        by_native[source_id].add((official_id, rid))
    for native_id, choices in sorted(by_native.items()):
        if len({x[0] for x in choices}) != 1:
            collisions.append({"native_id": native_id, "choices": sorted(choices)})
        if native_id in certified and any(x[0] != certified[native_id] for x in choices):
            collisions.append({"native_id": native_id, "existing_official_id": certified[native_id],
                               "provider_choices": sorted(choices)})
    reverse = defaultdict(set)
    for native_id, choices in by_native.items():
        if len({x[0] for x in choices}) == 1:
            reverse[next(iter(choices))[0]].add(native_id)
    for official_id, source_ids in reverse.items():
        if len(source_ids) > 1:
            collisions.append({"official_element_id": official_id, "native_ids": sorted(source_ids)})
    if collisions:
        raise ValueError("Reep certified ID collisions; cannot promote: " + json.dumps(collisions[:12]))
    proved = {nid: next(iter(v))[0] for nid, v in by_native.items() if len(v) == 1}
    new = sorted(nid for nid in proved if nid not in certified)
    missing = sorted(observed - set(certified) - set(proved))
    return {
        "contract": "FPL_T1_REEP_V1_EXACT_ID_READ_ONLY_20261016",
        "status": "SOURCE_SHA_VERIFIED_REVIEW_ONLY", "v6_source_run": "PUBLISHER_RUNTIME_CURRENT",
        "reep_release_stamp": RELEASE, "reep_bridges_gzip_sha256": actual_sha,
        "verified_original_fotmob_fixture_count": 60,
        "official_player_count": len(code_map),
        "source_native_starter_player_count": len(starter_native),
        "source_native_league_stats_player_count": len(league_native),
        "source_native_total_observed_player_count": len(observed),
        "previously_certified_native_players": len(certified),
        "independent_bridge_matched_native_players": len(proved),
        "new_independent_bridge_native_players": len(new),
        "still_without_independent_bridge_native_players": len(missing),
        "new_provider_id_candidates": [
            {"fotmob_native_id": nid, "official_fpl_element_id": proved[nid],
             "official_fpl_code": next(code for code, element in code_map.items() if element == proved[nid]),
             "reep_id": next(rid for element, rid in by_native[nid] if element == proved[nid]),
             "bridge_class": "EXACT_FOTMOB_PERSON_TO_REEP_TO_OPTA_PERSON_NUMERIC",
             "status": "SOURCE_ID_VERIFIED_PROMOTION_CANDIDATE"} for nid in new
        ],
        "no_independent_bridge_native_ids": missing,
        "existing_crosswalk_conflicts": 0, "canonical_mapping_updated": False,
        "historical_predeadline_asof_proven": False, "numeric_pstart_effect": "NONE",
        "scheduler_created": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--official", type=Path, required=True)
    p.add_argument("--fotmob", type=Path, required=True)
    p.add_argument("--bridges", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    official = json.loads(a.official.read_text())
    fotmob = json.loads(a.fotmob.read_text())
    report = build_report(official, fotmob, a.bridges)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps({k:v for k,v in report.items() if not isinstance(v,list)}, sort_keys=True))


if __name__ == "__main__":
    main()
