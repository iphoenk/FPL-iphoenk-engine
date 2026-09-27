from copy import deepcopy
import json
from datetime import datetime, timezone
from pathlib import Path

from src.engines.live_state_service import classify_bonus_lifecycle
from src.models.official_role_evidence import attach_official_role_evidence
from src.engines import v12_integrated_report_runner as integrated
from src.models.official_set_piece_notes import (
    normalize_official_set_piece_notes,
    team_set_piece_note_evidence,
)
from src.runtime_v6.domains.report_plane.report_prefetch import PrefetchService


def _fixture(
    fixture_id,
    *,
    event=5,
    kickoff="2026-09-20T13:00:00Z",
    started=True,
    finished=False,
    finished_provisional=False,
):
    return {
        "id": fixture_id,
        "event": event,
        "kickoff_time": kickoff,
        "started": started,
        "finished": finished,
        "finished_provisional": finished_provisional,
    }


def test_fact1_live_bonus_is_provisional():
    got = classify_bonus_lifecycle(
        [_fixture(1)],
        5,
        {"status": [{"event": 5, "date": "2026-09-20", "bonus_added": False}]},
        event_meta={"id": 5, "finished": False, "data_checked": False},
    )
    assert got["lifecycle_state"] == "LIVE_PROVISIONAL"
    assert got["status"] == "PROVISIONAL"
    assert got["provisional"] is True
    assert got["match_state"] == "IN_PROGRESS"


def test_fact1_finished_provisional_never_implies_final_bonus():
    got = classify_bonus_lifecycle(
        [
            _fixture(
                1,
                started=True,
                finished=True,
                finished_provisional=True,
            )
        ],
        5,
        {"status": []},
        event_meta={"id": 5, "finished": True, "data_checked": True},
    )
    assert got["lifecycle_state"] == "AWAITING_BONUS_FINALIZATION"
    assert got["status"] == "PROVISIONAL"
    assert got["finished_provisional_is_final_authority"] is False


def test_fact1_final_requires_bonus_added_and_final_event_state():
    got = classify_bonus_lifecycle(
        [
            _fixture(
                1,
                started=True,
                finished=True,
                finished_provisional=True,
            )
        ],
        5,
        {"status": [{"event": 5, "date": "2026-09-20", "bonus_added": True}]},
        event_meta={"id": 5, "finished": True, "data_checked": True},
    )
    assert got["lifecycle_state"] == "FINAL"
    assert got["status"] == "FINAL"
    assert got["provisional"] is False
    assert got["match_state"] == "FINALIZED"


def test_fact1_multi_day_gw_can_be_partially_finalized_without_becoming_final():
    got = classify_bonus_lifecycle(
        [
            _fixture(
                1,
                kickoff="2026-09-19T14:00:00Z",
                started=True,
                finished=True,
                finished_provisional=True,
            ),
            _fixture(
                2,
                kickoff="2026-09-20T15:30:00Z",
                started=False,
                finished=False,
            ),
        ],
        5,
        {"status": [{"event": 5, "date": "2026-09-19", "bonus_added": True}]},
        event_meta={"id": 5, "finished": False, "data_checked": False},
    )
    assert got["lifecycle_state"] == "PARTIALLY_FINALIZED"
    assert got["status"] == "PROVISIONAL"
    assert got["bonus_finalized_dates"] == ["2026-09-19"]


def test_fact1_wrong_event_bonus_status_cannot_finalize_target_gw():
    got = classify_bonus_lifecycle(
        [_fixture(1, started=True, finished=True, finished_provisional=True)],
        5,
        {"status": [{"event": 4, "date": "2026-09-20", "bonus_added": True}]},
        event_meta={"id": 5, "finished": True, "data_checked": True},
    )
    assert got["lifecycle_state"] == "AWAITING_BONUS_FINALIZATION"


def test_fact2_placeholder_notes_are_available_but_not_actionable():
    payload = {
        "last_updated": "2026-09-10T13:57:36Z",
        "teams": [
            {
                "id": 1,
                "notes": [
                    {
                        "external_link": True,
                        "info_message": "Check back for additional notes soon",
                        "source_link": "",
                    }
                ],
            }
        ],
    }
    got = team_set_piece_note_evidence(payload, 1)
    assert got["status"] == "PLACEHOLDER_ONLY"
    assert got["actionable"] is False
    assert got["advisory_only"] is True
    assert got["direct_xmins_mutation"] is False
    assert got["direct_xpts_mutation"] is False
    assert got["direct_start_probability_mutation"] is False


def test_fact2_actionable_note_is_evidence_only_and_cannot_mutate_projection_math():
    notes = {
        "last_updated": "2026-10-01T10:00:00Z",
        "teams": [
            {
                "id": 7,
                "notes": [
                    {
                        "external_link": False,
                        "info_message": "Player A has recently taken corners.",
                        "source_link": "",
                    }
                ],
            }
        ],
    }
    projections = {
        "players": [
            {
                "element": 10,
                "xpts": 6.25,
                "xmins": {
                    "expected_minutes": 82.0,
                    "start_probability": 0.91,
                },
            }
        ]
    }
    canonical_before = deepcopy(projections["players"][0])
    summary = attach_official_role_evidence(
        projections,
        {
            "elements": [
                {
                    "id": 10,
                    "team": 7,
                    "corners_and_indirect_freekicks_order": 1,
                    "penalties_order": 2,
                }
            ]
        },
        set_piece_notes=notes,
    )
    player = projections["players"][0]
    assert player["xpts"] == canonical_before["xpts"]
    assert player["xmins"] == canonical_before["xmins"]
    assert player["official_set_piece_notes"]["status"] == "ACTIONABLE_EVIDENCE"
    assert player["official_set_piece_notes"]["advisory_only"] is True
    assert summary["direct_xpts_mutation"] is False
    assert summary["direct_xmins_mutation"] is False
    assert summary["direct_start_probability_mutation"] is False


def test_fact2_normalizer_keeps_source_and_actionability_counts():
    payload = {
        "last_updated": "2026-09-10T13:57:36Z",
        "teams": [
            {"id": 1, "notes": [{"info_message": "Check back for additional notes soon"}]},
            {"id": 2, "notes": [{"info_message": "Player B is first in line for penalties."}]},
        ],
    }
    got = normalize_official_set_piece_notes(payload)
    assert got["team_count"] == 2
    assert got["actionable_team_count"] == 1
    assert got["evidence_only"] is True
    assert got["direct_model_override_forbidden"] is True


class _FactPrefetchClient:
    def __init__(self, *, set_piece_status="LIVE"):
        self.set_piece_status = set_piece_status
        self.secret_values = ()
        self.auth_configuration_state = "UNAVAILABLE"
        self.auth_available = False
        self.calls = []

    def bootstrap(self):
        self.calls.append("bootstrap")
        return {
            "status": "LIVE",
            "endpoint_class": "bootstrap_static",
            "checked_at": "2026-09-27T04:15:00+00:00",
            "http_status": 200,
            "payload_digest": "a" * 64,
            "payload": {
                "events": [
                    {
                        "id": 5,
                        "is_current": True,
                        "deadline_time": "2026-09-18T17:30:00+00:00",
                    }
                ],
                "teams": [],
                "element_types": [],
                "elements": [],
            },
        }

    def set_piece_notes(self):
        self.calls.append("set_piece_notes")
        return {
            "status": self.set_piece_status,
            "endpoint_class": "set_piece_notes",
            "checked_at": "2026-09-27T04:15:01+00:00",
            "http_status": 200 if self.set_piece_status == "LIVE" else 503,
            "payload_digest": "b" * 64 if self.set_piece_status == "LIVE" else None,
            "payload": (
                {
                    "last_updated": "2026-09-10T13:57:36Z",
                    "teams": [
                        {
                            "id": 1,
                            "notes": [
                                {
                                    "info_message": "Check back for additional notes soon",
                                    "source_link": "",
                                    "external_link": True,
                                }
                            ],
                        }
                    ],
                }
                if self.set_piece_status == "LIVE"
                else None
            ),
        }

    def telemetry(self):
        return {
            "request_count": len(self.calls),
            "failed_requests": int(self.set_piece_status != "LIVE"),
            "maximum_concurrency_used": 1,
        }


def _public_only_prefetch_config():
    return {
        "schema_version": 1,
        "season": "2026-2027",
        "entry_id": 3462711,
        "priority_leagues": [],
        "personal_team_enabled": False,
        "mini_league_enabled": False,
        "prefetch_lead_minutes": 15,
        "prefetch_max_age_minutes": 35,
        "http_timeout_seconds": 15,
        "http_retries": 1,
        "http_backoff_seconds": 0,
    }


def test_fact2_full_master_prefetch_binds_public_notes_to_exact_occurrence(tmp_path: Path):
    client = _FactPrefetchClient()
    service = PrefetchService(
        config=_public_only_prefetch_config(),
        output_root=tmp_path,
        client=client,
        now=datetime(2026, 9, 27, 4, 15, tzinfo=timezone.utc),
    )
    manifest = service.run(
        report_kind="full_master",
        logical_slot="2026-09-27T11:30:00+07:00",
    )
    artifact = json.loads(
        (tmp_path / "report_prefetch" / "set_piece_notes.json").read_text()
    )
    assert client.calls == ["bootstrap", "set_piece_notes"]
    assert manifest["set_piece_notes_requested"] is True
    assert manifest["set_piece_notes_status"] == "AVAILABLE"
    assert manifest["public_core_complete"] is True
    assert artifact["report_prefetch_run_id"] == manifest["report_prefetch_run_id"]
    assert artifact["target_logical_report_slot"] == "2026-09-27T11:30:00+07:00"
    assert artifact["semantic_class"] == "FACT"
    assert artifact["governance"]["direct_xpts_mutation"] is False
    assert artifact["governance"]["direct_xmins_mutation"] is False
    assert artifact["governance"]["direct_start_probability_mutation"] is False


def test_fact2_optional_note_failure_does_not_fail_prefetch_public_core(tmp_path: Path):
    client = _FactPrefetchClient(set_piece_status="FAILED")
    service = PrefetchService(
        config=_public_only_prefetch_config(),
        output_root=tmp_path,
        client=client,
        now=datetime(2026, 9, 27, 4, 15, tzinfo=timezone.utc),
    )
    manifest = service.run(
        report_kind="full_master",
        logical_slot="2026-09-27T11:30:00+07:00",
    )
    assert manifest["public_core_complete"] is True
    assert manifest["complete"] is True
    assert manifest["set_piece_notes_status"] == "FAILED"
    assert manifest["source_failures"] == []
    assert manifest["advisory_source_failures"][0]["endpoint_class"] == "set_piece_notes"


def test_fact2_integrated_runner_rejects_stale_or_cross_occurrence_note_artifact(tmp_path: Path):
    runtime = tmp_path
    path = runtime / "data" / "v6" / "report_prefetch" / "set_piece_notes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "semantic_class": "FACT",
                "authority": "OFFICIAL_FPL",
                "status": "AVAILABLE",
                "report_kind": "full_master",
                "target_logical_report_slot": "2026-09-27T04:30:00+07:00",
                "report_prefetch_run_id": "old-request",
                "payload": {"teams": []},
            }
        ),
        encoding="utf-8",
    )
    got = integrated._bound_set_piece_notes(
        runtime,
        prefetch={"report_prefetch_run_id": "current-request"},
        report_slot="2026-09-27T12:30:00+07:00",
    )
    assert got["status"] == "DEGRADED"
    assert got["payload"] is None
    assert "logical_slot" in got["reason"]
    assert "report_prefetch_run_id" in got["reason"]


def test_fact2_endpoint_has_single_v6_report_prefetch_owner():
    registry = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "config"
            / "sources"
            / "official_endpoint_ownership.json"
        ).read_text()
    )
    owners = [
        row["owner_service"]
        for row in registry["network_purposes"]
        if "set-piece-notes" in row.get("endpoint_families", [])
    ]
    assert owners == ["v6_report_prefetch"]
