from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.v12_match_occurrence import PublicMatchError, build_public_match
from src.engines.v12_delivery_reliability import write_serving_artifacts
from src.engines.v12_report_production_gate import evaluate_report_production_gate

CANONICAL = (
    Path(__file__).resolve().parents[1]
    / "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
)
SLOT = "2026-10-10T20:57:00+07:00"


def _put(root: Path, name: str, value: dict) -> None:
    path = root / "data/v6" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _runtime(tmp_path: Path, *, invalid_count: bool = False, gw: int = 6) -> Path:
    manager_picks = []
    for element in range(1, 16):
        manager_picks.append({
            "element_id": element,
            "squad_position": element,
            "multiplier": 2 if element == 7 else (1 if element <= 11 else 0),
            "captain": element == 7,
            "vice_captain": element == 8,
            "bench_order": element - 11 if element > 11 else None,
        })
    entries = {
        str(1000 + i): {
            "status": "AVAILABLE",
            "picks": manager_picks,
            "checked_at": "2026-10-10T13:57:00+00:00",
        }
        for i in range(57)
    }
    entries["3462711"] = {
        "status": "AVAILABLE",
        "picks": manager_picks[:14] if invalid_count else manager_picks,
        "checked_at": "2026-10-10T13:57:00+00:00",
    }
    _put(tmp_path, "report_prefetch/occurrences/match_mode__20261010_205700_plus_0700.json", {
        "report_kind": "match_mode",
        "target_logical_report_slot": SLOT,
        "gw": gw,
        "entry_id": 3462711,
        "priority_league_id": 9477,
        "public_core_complete": True,
        "mini_league_status": "AVAILABLE",
        "live_status": "AVAILABLE",
        "expected_manager_count": 58,
        "report_prefetch_run_id": "test-bound",
    })
    _put(tmp_path, "mini_leagues/9477/gw_6_manager_picks.json", {
        "gw": 6, "complete": True, "submitted_picks_missing_count": 0,
        "generated_at": "2026-10-10T13:57:00+00:00", "entries": entries,
    })
    _put(tmp_path, "mini_leagues/9477/live_state.json", {
        "gw": 6, "status": "AVAILABLE", "checked_at": "2026-10-10T13:57:00+00:00",
        "elements": [
            {"element_id": i, "total_points": i, "minutes": 75, "bonus": 0, "bps": i}
            for i in range(1, 16)
        ],
    })
    _put(tmp_path, "mini_leagues/9477/standings.json", {
        "league_name": "ICON+ League", "complete": True,
        "generated_at": "2026-10-10T13:57:00+00:00",
        "managers": [
            {"entry_id": 1000 + i, "league_rank": i + 1}
            for i in range(57)
        ] + [{"entry_id": 3462711, "league_rank": 7}],
    })
    _put(tmp_path, "normalized/canonical_players.json", {
        "players": [
            {"official_fpl_element_id": i, "web_name": f"P{i}", "team_id": 1,
             "element_type": 1 if i in {1, 15} else (2 if i <= 6 else (3 if i <= 11 else 4))}
            for i in range(1, 16)
        ]
    })
    _put(tmp_path, "normalized/canonical_fixtures.json", {
        "fixtures": [{"event": 6, "team_h": 1, "team_a": 2,
                      "started": True, "finished": False}]
    })
    _put(tmp_path, "normalized/canonical_teams.json", {
        "teams": [
            {"official_fpl_team_id": 1, "name": "Alpha"},
            {"official_fpl_team_id": 2, "name": "Beta"},
        ]
    })
    return tmp_path


def test_match_public_without_auth_is_13_section_degraded_and_real_exposure(tmp_path):
    root = _runtime(tmp_path)
    bundle = build_public_match(
        runtime_data_root=root, report_slot=SLOT,
        canonical_text=CANONICAL.read_text(encoding="utf-8"),
    )
    ids = [row["section_id"] for row in bundle["report"]["sections"]]
    assert ids == [f"MATCH{i}" for i in range(1, 14)]
    assert bundle["report_mode"] == "MATCH"
    assert bundle["runner_status"] == "DEGRADED"
    assert bundle["execution_proof"]["source_evidence"]["auth_required"] is False
    assert bundle["report"]["sections"][9]["state"] == "DEGRADED"
    assert "P7" in bundle["visible_body"]
    assert "Coverage: 58/58" in bundle["visible_body"]
    assert "## MATCH 13" in bundle["visible_body"]
    assert "AUTH_AVAILABLE" not in bundle["visible_body"]
    out = tmp_path / "out"
    snapshot = write_serving_artifacts(bundle=bundle, output_dir=out)
    assert list(snapshot["sections"]) == ids
    assert snapshot["delivery_status"] == "READY_DEGRADED"
    verdict = evaluate_report_production_gate(
        bundle, serving_snapshot=snapshot, visible_body_non_empty=True,
    )
    assert verdict["status"] == "PASS", verdict


def test_match_rejects_incomplete_official_15(tmp_path):
    root = _runtime(tmp_path, invalid_count=True)
    with pytest.raises(PublicMatchError, match="MATCH_LOCKED_XI_INCOMPLETE"):
        build_public_match(
            runtime_data_root=root, report_slot=SLOT,
            canonical_text=CANONICAL.read_text(encoding="utf-8"),
        )


def test_match_rejects_wrong_gw_or_stale_prefetch(tmp_path):
    root = _runtime(tmp_path, gw=5)
    with pytest.raises(PublicMatchError, match="MATCH_PUBLIC_COVERAGE_INCOMPLETE"):
        build_public_match(
            runtime_data_root=root, report_slot=SLOT,
            canonical_text=CANONICAL.read_text(encoding="utf-8"),
        )
    with pytest.raises(PublicMatchError, match="MATCH_PREFETCH_EXACT_PUBLIC_SCOPE_NOT_READY"):
        build_public_match(
            runtime_data_root=root, report_slot="2026-10-10T20:59:00+07:00",
            canonical_text=CANONICAL.read_text(encoding="utf-8"),
        )
