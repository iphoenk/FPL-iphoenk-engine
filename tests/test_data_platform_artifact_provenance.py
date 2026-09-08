from __future__ import annotations

import json
from pathlib import Path

from src.runtime_v6.artifact_catalog import refresh_artifact_catalog, validate_artifact_catalog
from src.runtime_v6.artifact_provenance import (
    build_artifact_meta,
    source_snapshot_ids_for_payload,
)
from src.runtime_v6.normalizer import (
    CANONICAL_NORMALIZATION_VERSION,
    build_canonical_fixtures,
    build_canonical_players,
    build_canonical_teams,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _write(root: Path, relative: str, payload: dict) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _official_snapshot() -> dict:
    return {
        "schema_version": 4,
        "source_id": "official_fpl",
        "checked_at": "2026-09-08T07:00:00+00:00",
        "current_run_action": "FETCHED",
        "availability": "AVAILABLE",
        "attempts": [
            {
                "request_id": "bootstrap",
                "status": "AVAILABLE",
                "sha256": DIGEST_A,
            },
            {
                "request_id": "fixtures",
                "status": "AVAILABLE",
                "sha256": DIGEST_B,
            },
        ],
        "official": {
            "bootstrap": {
                "elements": [
                    {
                        "id": 1,
                        "code": 1001,
                        "web_name": "One",
                        "first_name": "Player",
                        "second_name": "One",
                        "team": 1,
                        "element_type": 3,
                        "status": "a",
                    }
                ],
                "teams": [
                    {"id": 1, "code": 3, "name": "Team One", "short_name": "ONE"}
                ],
            },
            "fixtures": [
                {
                    "id": 10,
                    "event": 4,
                    "kickoff_time": "2026-09-12T12:30:00Z",
                    "team_h": 1,
                    "team_a": 2,
                    "finished": False,
                    "started": False,
                }
            ],
        },
    }


def test_source_snapshot_ids_use_immutable_request_and_cached_payload_digests() -> None:
    payload = {
        "source_id": "provider",
        "attempts": [
            {"request_id": "live", "status": "AVAILABLE", "sha256": DIGEST_A},
            {"request_id": "unchanged", "status": "NOT_MODIFIED"},
        ],
        "data": {
            "unchanged": {"request_id": "unchanged", "sha256": DIGEST_B},
        },
    }
    assert source_snapshot_ids_for_payload(payload) == [
        f"provider:live:{DIGEST_A}",
        f"provider:unchanged:{DIGEST_B}",
    ]


def test_canonical_fpl_outputs_are_explicitly_provenance_complete(tmp_path: Path) -> None:
    official = _official_snapshot()
    players = build_canonical_players(official, ["official_fpl"], {})
    teams = build_canonical_teams(official)
    fixtures = build_canonical_fixtures(official)

    for name, payload, expected_key in (
        ("canonical_players.json", players, "official_fpl_element_id"),
        ("canonical_teams.json", teams, "official_fpl_team_id"),
        ("canonical_fixtures.json", fixtures, "official_fpl_fixture_id"),
    ):
        assert payload["canonical"] is True
        assert payload["semantic_class"] == "NORMALIZED_FACT"
        assert payload["normalization_version"] == CANONICAL_NORMALIZATION_VERSION
        assert payload["effective_at"] == official["checked_at"]
        assert payload["primary_keys"] == [expected_key]
        assert payload["source_snapshot_ids"] == [
            f"official_fpl:bootstrap:{DIGEST_A}",
            f"official_fpl:fixtures:{DIGEST_B}",
        ]
        _write(tmp_path, f"normalized/{name}", payload)
        meta = build_artifact_meta(tmp_path, f"normalized/{name}")
        assert meta["artifact_class"] == "CANONICAL_DATASET"
        assert meta["provenance_status"] == "COMPLETE"
        assert meta["completeness"]["missing_fields"] == []


def test_derived_current_source_resolves_dependency_to_immutable_digest(tmp_path: Path) -> None:
    _write(tmp_path, "current/official_fpl.json", _official_snapshot())
    _write(
        tmp_path,
        "current/official_price_predictor.json",
        {
            "schema_version": 4,
            "source_id": "official_price_predictor",
            "checked_at": "2026-09-08T07:00:01+00:00",
            "current_run_action": "DERIVED",
            "availability": "AVAILABLE",
            "source_snapshot_ids": ["official_fpl"],
        },
    )
    meta = build_artifact_meta(tmp_path, "current/official_price_predictor.json")
    assert meta["provenance_status"] == "COMPLETE"
    assert meta["source_snapshot_ids"] == [
        f"official_fpl:bootstrap:{DIGEST_A}",
        f"official_fpl:fixtures:{DIGEST_B}",
    ]


def test_catalog_fails_closed_when_canonical_provenance_is_incomplete(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "normalized/canonical_players.json",
        {
            "schema_version": 3,
            "canonical": True,
            "authority": "official_fpl",
            "player_count": 1,
            "players": [{"official_fpl_element_id": 1}],
        },
    )
    catalog = refresh_artifact_catalog(tmp_path)
    report = validate_artifact_catalog(tmp_path)

    assert catalog["schema_version"] == 2
    assert catalog["completeness"]["status"] == "FAIL"
    assert catalog["completeness"]["incomplete_count"] == 1
    assert report["valid"] is False
    assert report["provenance_complete"] is False
    assert any(error.startswith("artifact_provenance_incomplete:normalized/canonical_players.json") for error in report["errors"])


def test_catalog_passes_with_valid_current_and_canonical_artifacts(tmp_path: Path) -> None:
    official = _official_snapshot()
    _write(tmp_path, "current/official_fpl.json", official)
    _write(
        tmp_path,
        "normalized/canonical_players.json",
        build_canonical_players(official, ["official_fpl"], {}),
    )

    catalog = refresh_artifact_catalog(tmp_path)
    report = validate_artifact_catalog(tmp_path)

    assert catalog["completeness"]["status"] == "PASS"
    assert report["valid"] is True
    assert report["provenance_complete"] is True
    assert report["incomplete_count"] == 0
