from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.v12_personal_data_plane import (
    PersonalDataPlaneError,
    candidate_payload_fingerprint,
    collect_personal_evidence_candidates,
)


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _team(gw: int = 5) -> dict:
    return {
        "auth_state": "AUTH_AVAILABLE",
        "generated_at": "2026-09-26T00:00:00+00:00",
        "gw": gw,
        "players": [{"element_id": i} for i in range(1, 16)],
    }


def _owner_state() -> dict:
    return {
        "confirmed_current_squad_state": {
            "goalkeepers": [{"element_id": 1}],
            "defenders": [{"element_id": 2}],
            "midfielders": [{"element_id": 3}],
            "forwards": [{"element_id": 4}],
            "explicit_user_confirmation": True,
            "explicit_user_confirmed_at": "2026-09-26T00:00:00+00:00",
            "applicable_planning_gw": 6,
        }
    }


def test_private_plane_can_run_without_public_private_sources(tmp_path):
    runtime = tmp_path / "runtime"
    private = tmp_path / "private"
    _write(private / "personal/current_team.json", _team())
    rows = collect_personal_evidence_candidates(
        runtime_root=runtime,
        legacy_state={},
        planning_gw=6,
        private_root=private,
        allow_legacy_private_sources=False,
        require_private_personal=True,
    )
    assert rows
    assert all(
        row["source"].startswith("PRIVATE:")
        for row in rows
        if row["source_class"] != "OFFICIAL_SUBMITTED_PICKS"
    )


def test_private_owner_manual_state_is_private_from_origin(tmp_path):
    runtime = tmp_path / "runtime"
    private = tmp_path / "private"
    _write(private / "personal/owner_state.json", _owner_state())
    rows = collect_personal_evidence_candidates(
        runtime_root=runtime,
        legacy_state={},
        planning_gw=6,
        private_root=private,
        allow_legacy_private_sources=False,
    )
    assert any(
        row["source"].startswith("PRIVATE:personal/owner_state.json")
        for row in rows
    )
    assert not (runtime / "data/v6/personal/current_team.json").exists()


def test_private_submitted_picks_are_primary_and_public_copy_is_legacy_only(tmp_path):
    runtime = tmp_path / "runtime"
    private = tmp_path / "private"
    submitted = {
        "status": "AVAILABLE",
        "gw": 5,
        "generated_at": "2026-09-26T00:00:00+00:00",
        "picks": [],
    }
    _write(private / "personal/submitted_picks.json", submitted)
    _write(runtime / "data/v6/personal/submitted_picks.json", submitted)

    rows = collect_personal_evidence_candidates(
        runtime_root=runtime,
        legacy_state={},
        planning_gw=6,
        private_root=private,
        allow_legacy_private_sources=False,
    )
    official = [
        row for row in rows
        if row["source_class"] == "OFFICIAL_SUBMITTED_PICKS"
    ]
    assert len(official) == 1
    assert official[0]["source"] == "PRIVATE:personal/submitted_picks.json"

    rows_without_private = collect_personal_evidence_candidates(
        runtime_root=runtime,
        legacy_state={},
        planning_gw=6,
        private_root=None,
        allow_legacy_private_sources=False,
    )
    assert not any(
        row["source_class"] == "OFFICIAL_SUBMITTED_PICKS"
        for row in rows_without_private
    )

    legacy_rows = collect_personal_evidence_candidates(
        runtime_root=runtime,
        legacy_state={},
        planning_gw=6,
        private_root=None,
        allow_legacy_private_sources=True,
    )
    assert any(
        row["source"] == "data/v6/personal/submitted_picks.json"
        for row in legacy_rows
    )


def test_private_required_fails_closed(tmp_path):
    with pytest.raises(PersonalDataPlaneError):
        collect_personal_evidence_candidates(
            runtime_root=tmp_path / "runtime",
            legacy_state={},
            planning_gw=6,
            private_root=tmp_path / "private",
            allow_legacy_private_sources=False,
            require_private_personal=True,
        )


def test_semantic_fingerprint_ignores_storage_source_label():
    payload = {
        "source_class": "AUTHENTICATED_CURRENT_TEAM",
        "payload": _team(),
        "observed_at": "x",
        "gw": 5,
        "auth_state": "AUTH_AVAILABLE",
    }
    a = [{**payload, "source": "data/v6/personal/current_team.json"}]
    b = [{**payload, "source": "PRIVATE:personal/current_team.json"}]
    assert candidate_payload_fingerprint(a) == candidate_payload_fingerprint(b)


def test_dual_read_compatibility_can_preserve_legacy_submitted_pick_behavior(tmp_path):
    runtime = tmp_path / "runtime"
    submitted = {
        "status": "AVAILABLE",
        "gw": 6,
        "generated_at": "2026-09-26T00:00:00+00:00",
        "picks": [],
    }
    _write(runtime / "data/v6/personal/submitted_picks.json", submitted)
    rows = collect_personal_evidence_candidates(
        runtime_root=runtime,
        legacy_state={},
        planning_gw=6,
        allow_legacy_private_sources=True,
        enforce_public_disclosure=False,
    )
    assert any(
        row["source_class"] == "OFFICIAL_SUBMITTED_PICKS" for row in rows
    )


def test_private_manual_capture_is_user_confirmed_current_and_carries_visible_finance(tmp_path):
    runtime = tmp_path / "runtime"
    private = tmp_path / "private"
    _write(
        private / "personal/manual/gw6_capture.json",
        {
            "schema": "FPL_MANUAL_CURRENT_TEAM_CAPTURE_V1",
            "captured_at": "2026-09-26T16:56:00+07:00",
            "planning_gw": 6,
            "squad": [
                {"element_id": i, "current_price": 40 + i}
                for i in range(1, 16)
            ],
            "finance": {
                "bank": 2,
                "free_transfers": 0,
                "current_transfer_cost_points": 0,
            },
            "chips": {
                "wildcard": {"status": "PLAYED", "played_in_gw": 2},
                "free_hit": {"status": "AVAILABLE"},
            },
        },
    )
    rows = collect_personal_evidence_candidates(
        runtime_root=runtime,
        legacy_state={},
        planning_gw=6,
        private_root=private,
        allow_legacy_private_sources=False,
        require_private_personal=True,
    )
    manual = next(
        row for row in rows
        if row["source"].startswith("PRIVATE:personal/manual/")
    )
    assert manual["source_class"] == "USER_CONFIRMED"
    assert manual["explicit_confirmation"] is True
    assert manual["applicable_planning_gw"] == 6
    assert manual["payload"]["bank"] == 2
    assert manual["payload"]["free_transfers"] == 0
    assert manual["payload"]["availability"]["selling_price"] == "UNAVAILABLE"
    assert len(manual["payload"]["players"]) == 15
