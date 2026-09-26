from __future__ import annotations

import json
from pathlib import Path

from src.runtime_v6.domains.report_plane.private_boundary import (
    split_private_personal_state,
)


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_split_moves_current_team_private_and_sanitizes_public_auth_metadata(tmp_path):
    public = tmp_path / "data/v6"
    private = tmp_path / "private"

    _write(
        public / "personal/current_team.json",
        {
            "generated_at": "2026-09-26T09:24:49+00:00",
            "auth_state": "AUTH_AVAILABLE",
            "bank": 2,
            "free_transfers": 0,
            "players": [{"element_id": i} for i in range(1, 16)],
        },
    )
    _write(
        public / "report_prefetch/latest.json",
        {
            "auth_state": "AUTH_AVAILABLE",
            "report_auth_state": "AUTH_OK",
            "auth_action_required": False,
            "auth_action": "NONE",
            "personal_status": "AVAILABLE",
            "authenticated_personal_deferred": False,
            "scope_health": {
                "CORE": "GREEN",
                "AUTH": "AUTH_OK",
                "PERSONAL": "AVAILABLE",
            },
            "source_failures": [
                {
                    "domain": "official_fpl_personal",
                    "endpoint_class": "me",
                    "status": "LIVE",
                },
                {
                    "domain": "official_fpl",
                    "endpoint_class": "bootstrap_static",
                    "status": "LIVE",
                },
            ],
            "artifacts": [
                {"path": "data/v6/personal/current_team.json"},
                {"path": "data/v6/personal/submitted_picks.json"},
            ],
            "governance": {"data_only": True},
        },
    )
    _write(
        public / "health/report_prefetch.json",
        {
            "auth_state": "AUTH_AVAILABLE",
            "auth_action": "NONE",
            "personal_status": "AVAILABLE",
            "public_core_status": "GREEN",
        },
    )
    private.mkdir(parents=True, exist_ok=True)

    receipt = split_private_personal_state(
        public_root=public,
        private_root=private,
    )

    assert receipt["moved_current_team"] is True
    assert not (public / "personal/current_team.json").exists()
    private_team = json.loads(
        (private / "personal/current_team.json").read_text(encoding="utf-8")
    )
    assert private_team["bank"] == 2
    assert private_team["free_transfers"] == 0

    latest = json.loads(
        (public / "report_prefetch/latest.json").read_text(encoding="utf-8")
    )
    assert "auth_state" not in latest
    assert "report_auth_state" not in latest
    assert "personal_status" not in latest
    assert "AUTH" not in latest["scope_health"]
    assert "PERSONAL" not in latest["scope_health"]
    assert latest["source_failures"] == [
        {
            "domain": "official_fpl",
            "endpoint_class": "bootstrap_static",
            "status": "LIVE",
        }
    ]
    assert all(
        not str(row.get("path") or "").endswith("/personal/current_team.json")
        for row in latest["artifacts"]
    )
    assert latest["governance"]["private_personal_state_split"] is True

    health = json.loads(
        (public / "health/report_prefetch.json").read_text(encoding="utf-8")
    )
    assert "auth_state" not in health
    assert "personal_status" not in health
    assert health["private_personal_state_split"] is True


def test_split_is_idempotent_when_public_current_team_already_removed(tmp_path):
    public = tmp_path / "data/v6"
    private = tmp_path / "private"
    _write(public / "report_prefetch/latest.json", {"governance": {}})
    private.mkdir(parents=True, exist_ok=True)

    first = split_private_personal_state(public_root=public, private_root=private)
    second = split_private_personal_state(public_root=public, private_root=private)

    assert first["moved_current_team"] is False
    assert second["moved_current_team"] is False
    assert not (public / "personal/current_team.json").exists()
