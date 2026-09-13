from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.v6_build_verified_player_crosswalks import CrosswalkBuildError, build


def _base() -> dict:
    return {
        "schema_version": 1,
        "season": "2026-2027",
        "canonical_authority": "official_fpl",
        "fuzzy_matching_allowed": False,
        "sources": {
            "fotmob": {
                "entity_scopes": ["TEAM"],
                "verification_status": "VERIFIED_MANUAL",
                "teams": [{"source_native_id": 9825, "official_fpl_team_id": 1}],
            }
        },
        "governance": {"silent_name_matching_allowed": False},
    }


def _bootstrap() -> dict:
    return {
        "elements": [
            {"id": 1, "code": 1001, "web_name": "Alpha"},
            {"id": 2, "code": 1002, "web_name": "Beta"},
            {"id": 3, "code": 1003, "web_name": "Gamma"},
        ]
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "reep_id",
        "type",
        "name",
        "key_opta_numeric",
        "key_understat",
        "key_fotmob",
        "key_statmuse_pl",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_builder_joins_only_by_official_code_and_preserves_partial_coverage(tmp_path: Path):
    reep = tmp_path / "people.csv"
    _write_csv(
        reep,
        [
            {
                "reep_id": "reep_a",
                "type": "player",
                "name": "WRONG NAME ON PURPOSE",
                "key_opta_numeric": "1001",
                "key_understat": "501",
                "key_fotmob": "601",
                "key_statmuse_pl": "701",
            },
            {
                "reep_id": "reep_b",
                "type": "player",
                "name": "Beta",
                "key_opta_numeric": "1002",
                "key_understat": "502",
                "key_fotmob": "",
                "key_statmuse_pl": "702",
            },
            {
                "reep_id": "reep_outside",
                "type": "player",
                "name": "Outside",
                "key_opta_numeric": "9999",
                "key_understat": "999",
                "key_fotmob": "999",
                "key_statmuse_pl": "999",
            },
        ],
    )

    output, report = build(bootstrap=_bootstrap(), reep_csv=reep, base_config=_base())

    assert [row["official_fpl_code"] for row in output["sources"]["understat"]["players"]] == [1001, 1002]
    assert [row["source_native_id"] for row in output["sources"]["fotmob"]["players"]] == [601]
    assert [row["source_native_id"] for row in output["sources"]["statmuse"]["players"]] == [701, 702]
    assert output["sources"]["fotmob"]["teams"] == _base()["sources"]["fotmob"]["teams"]
    assert report["providers"]["fotmob"]["mapped_player_count"] == 1
    assert report["providers"]["fotmob"]["coverage_ratio"] == pytest.approx(1 / 3, rel=1e-5)
    assert report["name_matching_used"] is False
    assert output["governance"]["player_crosswalk_uses_official_code_only"] is True


def test_builder_fails_closed_on_duplicate_provider_native_id(tmp_path: Path):
    reep = tmp_path / "people.csv"
    _write_csv(
        reep,
        [
            {
                "reep_id": "reep_a",
                "type": "player",
                "name": "Alpha",
                "key_opta_numeric": "1001",
                "key_understat": "501",
                "key_fotmob": "601",
                "key_statmuse_pl": "701",
            },
            {
                "reep_id": "reep_b",
                "type": "player",
                "name": "Beta",
                "key_opta_numeric": "1002",
                "key_understat": "501",
                "key_fotmob": "602",
                "key_statmuse_pl": "702",
            },
        ],
    )

    with pytest.raises(CrosswalkBuildError, match="collisions"):
        build(bootstrap=_bootstrap(), reep_csv=reep, base_config=_base())


def test_builder_fails_closed_on_duplicate_official_fpl_code(tmp_path: Path):
    bootstrap = _bootstrap()
    bootstrap["elements"].append({"id": 4, "code": 1001, "web_name": "Duplicate"})
    reep = tmp_path / "people.csv"
    _write_csv(
        reep,
        [
            {
                "reep_id": "reep_a",
                "type": "player",
                "name": "Alpha",
                "key_opta_numeric": "1001",
                "key_understat": "501",
                "key_fotmob": "601",
                "key_statmuse_pl": "701",
            }
        ],
    )

    with pytest.raises(CrosswalkBuildError, match="duplicate Official FPL codes"):
        build(bootstrap=bootstrap, reep_csv=reep, base_config=_base())
