from __future__ import annotations

from src.engines import v12_integrated_report_runner as runner
from src.engines.v12_report_orchestration import (
    DEEP_HUMAN_SECTION_REQUIREMENTS,
    _render_deep_visible_contract_lines,
)


def _picks(elements, *, captain=None, vice=None, bench=None):
    bench = set(bench or [])
    rows = []
    for position, element in enumerate(elements, start=1):
        is_bench = element in bench
        rows.append(
            {
                "element_id": element,
                "squad_position": 12 if is_bench else min(position, 11),
                "multiplier": (
                    2 if element == captain and not is_bench
                    else 0 if is_bench
                    else 1
                ),
                "captain": element == captain,
                "vice_captain": element == vice,
            }
        )
    return rows


def _fixture(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_captain_candidate_review",
        lambda *, candidate, **kwargs: {
            "element_id": int(candidate["element"]),
            "player": candidate["name"],
            "expected_points": 6.0 - (int(candidate["element"]) / 100.0),
            "haul_probability": 0.12,
            "blank_probability": 0.40,
        },
    )

    our_entry = 100
    owned = [
        {"element_id": element, "name": f"P{element}"}
        for element in range(1, 16)
    ]
    standings = {
        "managers": [
            {
                "entry_id": 201,
                "league_rank": 1,
                "league_total": 110,
                "manager_name": "Leader One",
                "team_name": "Leader FC",
                "gw_score": 60,
            },
            {
                "entry_id": 202,
                "league_rank": 2,
                "league_total": 105,
                "manager_name": "Leader Two",
                "team_name": "Second FC",
                "gw_score": 50,
            },
            {
                "entry_id": our_entry,
                "league_rank": 3,
                "league_total": 100,
                "manager_name": "Us",
                "team_name": "Our FC",
                "gw_score": 45,
            },
        ],
        "complete": True,
    }
    rival_one = list(range(1, 15)) + [16]
    rival_two = list(range(1, 14)) + [17, 18]
    manager_picks = {
        "entries": {
            "201": {
                "entry_id": 201,
                "status": "AVAILABLE",
                "picks": _picks(
                    rival_one,
                    captain=1,
                    vice=2,
                    bench={12, 13, 14, 16},
                ),
            },
            "202": {
                "entry_id": 202,
                "status": "AVAILABLE",
                "picks": _picks(
                    rival_two,
                    captain=2,
                    vice=1,
                    bench={10, 11, 12, 17},
                ),
            },
        }
    }
    exposures = []
    for element in range(1, 16):
        own = 2 if element <= 13 else 1 if element == 14 else 0
        starter = (
            2 if element <= 9
            else 1 if element in {10, 11, 13, 14}
            else 0
        )
        bench = own - starter
        captain = 1 if element in {1, 2} else 0
        vice = 1 if element in {1, 2} else 0
        effective = starter + captain
        exposures.append(
            {
                "element_id": element,
                "ownership_count": own,
                "starter_count": starter,
                "bench_count": bench,
                "captain_count": captain,
                "vice_count": vice,
                "effective_multiplier_sum": effective,
                "denominator": 2,
                "ownership_pct": own * 50.0,
                "starter_pct": starter * 50.0,
                "bench_pct": bench * 50.0,
                "captain_pct": captain * 50.0,
                "vice_pct": vice * 50.0,
                "eo_pct": effective * 50.0,
                "eo_supported": True,
            }
        )
    mini = {
        "coverage_state": "FULL",
        "expected_manager_count": 3,
        "submitted_picks_available_count": 3,
        "rival_exposure_denominator": 2,
        "exposures": exposures,
        "current_league_context": {
            "our_entry_id": our_entry,
            "our_rank": 3,
            "our_total_points": 100,
            "leader_points": 110,
            "points_to_leader": 10,
            "points_to_top_3": 0,
            "points_to_top_5": 0,
            "points_to_nearest_above": 5,
            "points_ahead_nearest_below": None,
            "manager_count": 3,
        },
    }
    overlay = {
        "risk_posture": {"posture": "BALANCED"},
    }
    detail = runner._mini_league_deep_detail(
        mini=mini,
        standings=standings,
        manager_picks=manager_picks,
        owned=owned,
        projections={"players": []},
        lineup={
            "captain": {"element": 1, "name": "P1"},
            "vice_captain": {"element": 2, "name": "P2"},
        },
        mini_overlay=overlay,
        disclosed_gw=5,
        operational_action="WAIT",
    )
    return mini, detail, owned


def test_deep_mini_league_materializes_counts_denominators_and_direct_rivals(monkeypatch):
    mini, detail, _ = _fixture(monkeypatch)

    p1 = next(
        row for row in detail["our15_rival_exposure"]
        if row["element_id"] == 1
    )
    assert p1["ownership_count"] == 2
    assert p1["denominator"] == 2
    assert p1["ownership_pct"] == 100.0
    assert p1["captain_count"] == 1
    assert p1["eo_pct"] == 150.0

    assert detail["direct_rival_scope"]["denominator"] == 2
    assert detail["direct_rival_scope"]["complete"] is True
    assert [row["rank"] for row in detail["direct_rivals"]] == [1, 2]
    assert detail["direct_rivals"][0]["overlap_count"] == 14

    threat_names = {row["player"] for row in detail["rival_threats"]}
    assert {"element:16", "element:17", "element:18"} & threat_names
    assert detail["report_contract"]["raw_count_denominator_percentage_required"] is True
    assert detail["strategy_implication"]["human_posture"] == "BALANCED"
    assert mini["coverage_state"] == "FULL"


def test_s15b_visible_renderer_keeps_full_deep_contract(monkeypatch):
    mini, detail, owned = _fixture(monkeypatch)
    payload = {
        **mini,
        **detail,
    }
    owned_names = {
        row["element_id"]: row["name"]
        for row in owned
    }
    lines, _ = _render_deep_visible_contract_lines(
        section_id="S15B",
        content=payload,
        owned_ids=set(owned_names),
        owned_names=owned_names,
    )
    body = "\n".join(lines)
    assert "OUR15 VS ALL RIVALS" in body
    assert "OUR15 VS DIRECT RIVALS" in body
    assert "RIVAL THREATS NOT IN OUR15" in body
    assert "CAPTAIN LEVERAGE" in body
    assert "CHASE / BALANCED / DEFEND IMPLICATION" in body
    assert "| Player | OWN | START | BENCH | C | VC | EO |" in body
    assert "**P1**" in body
    assert "2/2 (100.0%)" in body
    assert "3/2 (150.0%)" in body
    assert "DIRECT RIVAL DIFFERENCE DETAIL" in body


def test_s15b_manifest_contract_cannot_regress_to_compact_summary():
    required = set(DEEP_HUMAN_SECTION_REQUIREMENTS["S15B"])
    assert {
        "rank_battle",
        "our15_rival_exposure",
        "direct_rival_scope",
        "direct_rivals",
        "direct_rival_our15_exposure",
        "rival_threats",
        "captain_leverage",
        "strategy_implication",
        "report_contract",
    }.issubset(required)
