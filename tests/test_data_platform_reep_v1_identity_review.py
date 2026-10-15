from __future__ import annotations

import csv
import gzip
from pathlib import Path

import pytest

from scripts.v6_reep_v1_fotmob_identity_review import (
    native_starter_evidence, read_reep_v1, build_report,
)


def _complete_observation():
    fixtures = []
    for fid in range(1, 61):
        sides = []
        for side in ("home", "away"):
            sides.append({
                "starting_xi_complete": True,
                "verified_official_starters": [
                    {"source_native_player_id": 111, "official_element_id": 123,
                     "identity_status": "VERIFIED_MANUAL"}
                ],
                "unverified_provider_starter_ids": list(range(200, 210)),
            })
        fixtures.append({"official_fixture_id": fid, "sides": sides})
    return {"source_id": "fotmob", "normalization_status": "NORMALIZED",
            "record_groups": {"match_tactics": fixtures}}


def test_native_starter_evidence_preserves_original_known_links():
    native, known = native_starter_evidence(_complete_observation())
    assert known == {111: 123}
    assert 200 in native and len(native) == 11


def test_source_match_count_and_verified_starter_identity_fail_closed():
    data = _complete_observation()
    data["record_groups"]["match_tactics"].pop()
    with pytest.raises(ValueError, match="60"):
        native_starter_evidence(data)
    data = _complete_observation()
    data["record_groups"]["match_tactics"][0]["sides"][0]["verified_official_starters"][0]["identity_status"] = "UNMAPPED"
    with pytest.raises(ValueError, match="bad existing"):
        native_starter_evidence(data)


def test_reep_only_joins_exact_native_person_and_numeric_opta(tmp_path: Path):
    file = tmp_path / "tiny.csv.gz"
    with gzip.open(file, "wt", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=["provider", "namespace", "external_id", "reep_id"])
        writer.writeheader()
        writer.writerows([
            {"provider": "opta", "namespace": "person_numeric", "external_id": "12345", "reep_id": "r1"},
            {"provider": "fotmob", "namespace": "person", "external_id": "987", "reep_id": "r1"},
            {"provider": "fotmob", "namespace": "team", "external_id": "987", "reep_id": "r2"},
            {"provider": "opta", "namespace": "person", "external_id": "12345", "reep_id": "r3"},
            {"provider": "fotmob", "namespace": "person", "external_id": "555", "reep_id": "r4"},
        ])
    opta, native = read_reep_v1(file, {12345}, {987, 555})
    assert opta == {"r1": {12345}}
    assert native == {"r1": {987}, "r4": {555}}


def test_wrong_snapshot_or_unverified_official_is_not_made_green(tmp_path: Path):
    with pytest.raises(ValueError, match="verified live Official"):
        build_report({"source_id": "official_fpl", "health": "RED"}, _complete_observation(), tmp_path / "missing")
    official = {"source_id": "official_fpl", "health": "GREEN",
                "official": {"bootstrap": {"elements": [{"id": i, "code": 1000+i} for i in range(667)]}}}
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        invalid = tmp_path / "fake.csv.gz"
        invalid.write_bytes(b"not valid reep")
        build_report(official, _complete_observation(), invalid)
