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


def test_public_submitted_picks_require_prior_disclosed_gw(tmp_path):
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
        private_root=None,
        allow_legacy_private_sources=False,
    )
    assert not any(
        row["source_class"] == "OFFICIAL_SUBMITTED_PICKS" for row in rows
    )

    submitted["gw"] = 5
    _write(runtime / "data/v6/personal/submitted_picks.json", submitted)
    rows = collect_personal_evidence_candidates(
        runtime_root=runtime,
        legacy_state={},
        planning_gw=6,
        private_root=None,
        allow_legacy_private_sources=False,
    )
    assert any(
        row["source_class"] == "OFFICIAL_SUBMITTED_PICKS" for row in rows
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
