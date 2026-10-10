from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.v12_public_match_delivery import (
    PublicMatchError,
    _exposure,
    _validated_inputs,
)


SLOT = "2026-10-10T20:57:00+07:00"
CHECKED = "2026-10-10T13:57:15+00:00"


def _write(root: Path, name: str, payload: dict) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path, *, gw: int = 6) -> None:
    root = tmp_path / "data/v6"
    _write(root, "report_prefetch/latest.json", {
        "report_kind": "match_mode",
        "target_logical_report_slot": SLOT,
        "public_core_complete": True,
        "live_requested": True,
        "mini_league_requested": True,
        "gw": gw,
        "entry_id": 3462711,
        "priority_league_id": 9477,
        "generated_at": CHECKED,
    })
    picks = [
        {
            "element_id": i,
            "squad_position": i,
            "multiplier": 2 if i == 7 else (1 if i <= 11 else 0),
            "captain": i == 7,
            "vice_captain": i == 8,
        }
        for i in range(1, 16)
    ]
    entries = {
        str(3462711 if i == 1 else i + 5000000): {"picks": picks}
        for i in range(1, 59)
    }
    _write(root, f"mini_leagues/9477/gw_{gw}_manager_picks.json", {
        "gw": gw, "complete": True, "expected_manager_count": 58,
        "submitted_picks_available_count": 58, "entries": entries,
    })
    _write(root, "mini_leagues/9477/standings.json", {
        "managers": [
            {"entry_id": int(x), "league_rank": i, "manager_name": f"Manager {i}"}
            for i, x in enumerate(entries, start=1)
        ],
        "league_name": "ICON+ League",
    })
    _write(root, "mini_leagues/9477/live_state.json", {
        "gw": gw, "status": "AVAILABLE", "authority": "OFFICIAL_FPL",
        "checked_at": CHECKED,
        "elements": [{"element_id": i, "total_points": i, "minutes": 90} for i in range(1, 16)],
    })


def test_match_public_is_independent_of_expired_private_auth(tmp_path: Path) -> None:
    _fixture(tmp_path)
    # The private tree and session credentials do not exist.
    gw, entry, _, picks, standings, live = _validated_inputs(tmp_path, SLOT)
    assert gw == 6
    assert entry == 3462711
    assert len(picks["entries"]) == len(standings["managers"]) == 58
    assert live["status"] == "AVAILABLE"


def test_match_public_rejects_cross_occurrence_stale_reuse(tmp_path: Path) -> None:
    _fixture(tmp_path)
    with pytest.raises(PublicMatchError, match="MATCH_PREFETCH_OCCURRENCE_MISMATCH"):
        _validated_inputs(tmp_path, "2026-10-10T21:10:00+07:00")


def test_match_public_58_scoring_multipliers_and_eo_not_ownership(tmp_path: Path) -> None:
    _fixture(tmp_path)
    _, entry, _, members, standings, live = _validated_inputs(tmp_path, SLOT)
    icon = _exposure(members, live, standings, entry, {i: f"Player {i}" for i in range(1, 16)})
    row = next(r for r in icon["material_player_exposure"] if r["player"] == "Player 7")
    assert row["owned"] == {"numerator": 58, "denominator": 58, "percentage": 100.0}
    assert row["captain"] == {"numerator": 58, "denominator": 58, "percentage": 100.0}
    assert row["eo"] == {"numerator": 116, "denominator": 58, "percentage": 200.0}
    assert icon["live_standings_rank"]["state"] == "UNAVAILABLE"
    assert icon["current_live_rank"] is None


def test_match_public_fail_closed_on_missing_manager_picks(tmp_path: Path) -> None:
    _fixture(tmp_path)
    root = tmp_path / "data/v6"
    file = root / "mini_leagues/9477/gw_6_manager_picks.json"
    payload = json.loads(file.read_text())
    payload["entries"].pop(next(iter(payload["entries"])))
    file.write_text(json.dumps(payload))
    with pytest.raises(PublicMatchError, match="MATCH_PUBLIC_58_OR_LIVE_INCOMPLETE"):
        _validated_inputs(tmp_path, SLOT)


def test_match_serving_retains_complete_public_sections() -> None:
    from src.engines.v12_delivery_reliability import _serving_project_content

    sample = {"submitted_picks_exposure": {"available_count": 58, "expected_count": 58}, "material_player_exposure": [{"player": "Bruno", "eo": {"numerator": 72, "denominator": 58}}]}
    assert _serving_project_content("MATCH10", sample) == sample
    assert _serving_project_content("MATCH13", {"event_live": "AVAILABLE"}) == {"event_live": "AVAILABLE"}


def test_match_full_13_section_synthetic_smoke(tmp_path: Path) -> None:
    from src.engines.v12_public_match_delivery import run

    _fixture(tmp_path)
    root = tmp_path / "data/v6"
    players = []
    for i in range(1, 16):
        pos = 1 if i in {1, 15} else 2 if i in {2, 3, 4, 5, 6} else 3 if i <= 11 else 4
        players.append({"official_fpl_element_id": i, "web_name": f"P{i}", "team_id": 1 if i <= 8 else 2, "element_type": pos})
    _write(root, "normalized/canonical_players.json", {"players": players})
    _write(root, "normalized/canonical_teams.json", {"teams": [{"official_fpl_team_id": 1, "name": "Alpha"}, {"official_fpl_team_id": 2, "name": "Beta"}]})
    _write(root, "normalized/canonical_fixtures.json", {"fixtures": [{"official_fpl_fixture_id": 101, "event": 6, "team_h": 1, "team_a": 2, "started": True, "finished": False, "kickoff_time": "2026-10-10T12:00:00Z"}]})
    _write(root, "current/official_fpl.json", {"official": {"fixtures": [{"id": 101, "team_h_score": 2, "team_a_score": 1}]}})
    output = tmp_path / "out"
    result = run(tmp_path, SLOT, output)
    assert result["sections"] == 13
    assert result["status"] == "READY_DEGRADED"
    serving = json.loads((output / "serving_report.json").read_text())
    assert list(serving["sections"]) == [f"MATCH{i}" for i in range(1, 14)]
    assert serving["sections"]["MATCH10"]["content"]["submitted_picks_exposure"]["available_count"] == 58
    assert serving["sections"]["MATCH13"]["content"]["submitted_picks"] == "AVAILABLE"
    assert "Alpha vs Beta" in (output / "serving_report.md").read_text()
    assert "2-1" in (output / "serving_report.md").read_text()


def test_match_exact_occurrence_survives_latest_pointer_advance(tmp_path: Path) -> None:
    _fixture(tmp_path)
    root = tmp_path / "data/v6"
    latest = root / "report_prefetch/latest.json"
    bound = root / "report_prefetch/occurrences/match_mode__20261010_205700_plus_0700.json"
    bound.parent.mkdir(parents=True, exist_ok=True)
    bound.write_text(latest.read_text())
    latest.write_text(json.dumps({"report_kind": "full_master", "target_logical_report_slot": "2026-10-10T21:30:00+07:00"}))
    _, _, pref, _, _, _ = _validated_inputs(tmp_path, SLOT)
    assert pref["report_kind"] == "match_mode"


from src.engines.v12_official_public_scoring import rank_live, score_entry
from src.runtime_v6.domains.report_plane.personal_prefetch import normalise_submitted_picks


def _entry(*, chip=None, hit=0, subs=None):
    return {
        "active_chip": chip, "automatic_subs": subs,
        "entry_history": {"event": 6, "points": 20, "total_points": 320, "event_transfers_cost": hit},
        "picks": [
            {"element_id": i, "squad_position": i,
             "multiplier": 2 if i == 2 else (1 if i <= 11 or chip == "bboost" else 0),
             "captain": i == 2, "vice_captain": i == 4}
            for i in range(1, 16)
        ],
    }


def test_official_public_hit_and_previous_overall():
    result = score_entry(_entry(hit=4), {i: i for i in range(1, 16)})
    assert result["gross_points"] == 68
    assert result["hit"] == 4
    assert result["net_points"] == 64
    assert result["previous_overall_points"] == 300
    assert result["live_overall_points"] == 364


def test_unknown_hit_is_not_invented_zero():
    entry = _entry()
    entry.pop("entry_history")
    result = score_entry(entry, {i: i for i in range(1, 16)})
    assert result["gross_points"] == 68
    assert result["hit"] is None
    assert result["net_points"] is None
    assert result["live_overall_points"] is None


def test_official_autosub_applied_once():
    entry = _entry(subs=[{"element_out": 3, "element_in": 12}], hit=8)
    result = score_entry(entry, {i: i for i in range(1, 16)})
    assert result["gross_points"] == 77
    assert result["net_points"] == 69
    assert result["calculated_autosub_applied"] == 1
    assert result["autosub_state"] == "OFFICIAL_APPLIED"
    entry["picks"][2]["multiplier"] = 0
    entry["picks"][11]["multiplier"] = 1
    already = score_entry(entry, {i: i for i in range(1, 16)})
    assert already["gross_points"] == 77
    assert already["calculated_autosub_applied"] == 0


def test_pending_dnp_does_not_finalize_autosub():
    result = score_entry(
        _entry(subs=None), {i: i for i in range(1, 16)},
        player_teams={3: 1}, finished_teams={1}, live_minutes={3: 0},
    )
    assert result["autosub_state"] == "PENDING"
    assert result["status"] == "PROVISIONAL"


def test_triple_captain_bench_boost_and_vice():
    triple = _entry(chip="3xc")
    triple["picks"][1]["multiplier"] = 3
    assert score_entry(triple, {i: i for i in range(1, 16)})["gross_points"] == 70
    boost = _entry(chip="bboost")
    assert score_entry(boost, {i: i for i in range(1, 16)})["gross_points"] == 122
    vice = score_entry(
        _entry(), {i: i for i in range(1, 16)},
        player_teams={2: 1}, finished_teams={1}, live_minutes={2: 0, 4: 90},
    )
    assert vice["vice_takeover_provisional"] is True
    assert vice["multipliers"][2] == 0
    assert vice["multipliers"][4] == 2


def test_rank_ties_provisional_without_inventing_transfer_order():
    rows = [
        {"entry_id": 10, "live_overall_points": 410},
        {"entry_id": 20, "live_overall_points": 408},
        {"entry_id": 30, "live_overall_points": 410},
    ]
    ranked = rank_live(rows)
    assert [r["entry_id"] for r in ranked] == [10, 30, 20]
    assert [r["live_rank"] for r in ranked] == [1, 1, 3]
    assert ranked[0]["tie_unresolved"] and ranked[1]["tie_unresolved"]


def test_public_normalizer_preserves_scoring_evidence():
    response = {
        "status": "LIVE", "checked_at": "2026-10-10T10:00:00Z",
        "http_status": 200, "payload_digest": "fixture",
        "payload": {
            "active_chip": None,
            "entry_history": {"event": 6, "event_transfers_cost": 8, "total_points": 333, "points": 20},
            "automatic_subs": [{"element_out": 3, "element_in": 12}],
            "picks": [{"element": p["element_id"], "position": p["squad_position"],
                       "multiplier": p["multiplier"], "is_captain": p["captain"],
                       "is_vice_captain": p["vice_captain"]}
                      for p in _entry()["picks"]],
        },
    }
    result = normalise_submitted_picks(3462711, 6, response)
    assert result["entry_history"]["event_transfers_cost"] == 8
    assert result["automatic_subs"][0]["element_in"] == 12
    assert len(result["picks"]) == 15
