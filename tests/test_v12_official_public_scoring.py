from __future__ import annotations

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
