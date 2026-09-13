from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.v6_build_identity_wave_b_candidates import (
    METHOD,
    WaveBCandidateError,
    build_understat_candidates,
)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _bootstrap() -> dict:
    return {"elements": [{"id": 1, "code": 1001}, {"id": 2, "code": 1002}, {"id": 3, "code": 1003}]}


def _understat() -> dict:
    return {
        "source_id": "understat",
        "record_groups": {
            "players": [
                {
                    "source_native_id": 501,
                    "official_element_id": 1,
                    "identity_status": "VERIFIED_MANUAL",
                    "player_name": "Must not be used",
                },
                {
                    "source_native_id": 502,
                    "official_element_id": None,
                    "identity_status": "UNMAPPED",
                    "player_name": "Different display label is irrelevant",
                },
                {
                    "source_native_id": 503,
                    "official_element_id": None,
                    "identity_status": "UNMAPPED",
                },
            ]
        },
    }


def test_builder_closes_only_unique_typed_transfermarkt_to_v1_understat_path(tmp_path: Path) -> None:
    v0 = tmp_path / "people.csv"
    v1 = tmp_path / "bridges.csv"
    _write_csv(
        v0,
        ["type", "key_opta_numeric", "key_transfermarkt"],
        [
            {"type": "player", "key_opta_numeric": 1001, "key_transfermarkt": 9001},
            {"type": "player", "key_opta_numeric": 1002, "key_transfermarkt": 9002},
            {"type": "player", "key_opta_numeric": 1003, "key_transfermarkt": 9003},
        ],
    )
    _write_csv(
        v1,
        ["provider", "namespace", "external_id", "reep_id"],
        [
            {"provider": "transfermarkt", "namespace": "spieler", "external_id": 9002, "reep_id": "rp2"},
            {"provider": "understat", "namespace": "player", "external_id": 502, "reep_id": "rp2"},
            {"provider": "transfermarkt", "namespace": "spieler", "external_id": 9003, "reep_id": "rp3"},
        ],
    )

    report = build_understat_candidates(
        bootstrap=_bootstrap(),
        understat_dataset=_understat(),
        reep_v0_people=v0,
        reep_v1_bridges=v1,
    )
    assert report["candidate_count"] == 1
    assert report["observed_unmapped_before"] == 2
    assert report["projected_observed_unmapped_after_reviewed_promotion"] == 1
    assert report["unresolved_observed_native_ids"] == ["503"]
    candidate = report["candidates"][0]
    assert candidate["source_native_id"] == 502
    assert candidate["official_fpl_code"] == 1002
    assert candidate["verification_method"] == METHOD
    assert candidate["evidence"]["transfermarkt_player_id"] == "9002"
    assert candidate["evidence"]["reep_v1_id"] == "rp2"
    assert candidate["evidence"]["name_matching_used"] is False
    assert report["governance"]["auto_promotion_to_runtime_join"] is False
    assert report["governance"]["v0_and_v1_reep_ids_assumed_interchangeable"] is False


def test_builder_fails_closed_on_v1_transfermarkt_collision(tmp_path: Path) -> None:
    v0 = tmp_path / "people.csv"
    v1 = tmp_path / "bridges.csv"
    _write_csv(
        v0,
        ["type", "key_opta_numeric", "key_transfermarkt"],
        [{"type": "player", "key_opta_numeric": 1002, "key_transfermarkt": 9002}],
    )
    _write_csv(
        v1,
        ["provider", "namespace", "external_id", "reep_id"],
        [
            {"provider": "transfermarkt", "namespace": "spieler", "external_id": 9002, "reep_id": "rp2"},
            {"provider": "transfermarkt", "namespace": "spieler", "external_id": 9002, "reep_id": "rpX"},
            {"provider": "understat", "namespace": "player", "external_id": 502, "reep_id": "rp2"},
        ],
    )
    with pytest.raises(WaveBCandidateError, match="bridge conflicts fail closed"):
        build_understat_candidates(
            bootstrap=_bootstrap(),
            understat_dataset=_understat(),
            reep_v0_people=v0,
            reep_v1_bridges=v1,
        )


def test_builder_rejects_duplicate_observed_native_ids(tmp_path: Path) -> None:
    v0 = tmp_path / "people.csv"
    v1 = tmp_path / "bridges.csv"
    _write_csv(v0, ["type", "key_opta_numeric", "key_transfermarkt"], [])
    _write_csv(v1, ["provider", "namespace", "external_id", "reep_id"], [])
    dataset = _understat()
    dataset["record_groups"]["players"].append(
        {"source_native_id": 502, "official_element_id": None, "identity_status": "UNMAPPED"}
    )
    with pytest.raises(WaveBCandidateError, match="duplicate observed native ids"):
        build_understat_candidates(
            bootstrap=_bootstrap(),
            understat_dataset=dataset,
            reep_v0_people=v0,
            reep_v1_bridges=v1,
        )
