"""P1 visible evidence tables remain strict without double-counting OUR15."""

from src.engines.v12_deep_presentation_lock import (
    load_deep_presentation_lock,
    validate_deep_presentation_lock_contract,
    _rendered_tables,
)
from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines
from src.runtime_v6.domains.report_plane.visible_body_contract import (
    _s02_primary_visible_tables,
)


def _visible(section, content):
    lines, _ = _render_deep_visible_contract_lines(
        section_id=section, content=content,
        owned_ids=set(), owned_names={},
    )
    return "\n".join(lines)


def _our15_rows():
    return [
        {
            "player": f"P{index}",
            "position": "MID",
            "opponent": "EXAMPLE",
            "p_start": 0.83,
            "p_dnp": 0.09,
            "xmins": 70,
            "projection_1gw": 4.0,
            "projection_3gw": 12.0,
            "projection_5gw": 20.0,
            "p_start_evidence": {
                "source": "V12_PLAYER_MINUTES",
                "quality": "PRIOR_DOMINATED",
                "confidence": "LOW",
                "signal_count": 1,
                "model_probability_agrees": True,
            },
        }
        for index in range(15)
    ]


def test_complete_p1_schema_contract_accepts_all_additive_tables():
    assert validate_deep_presentation_lock_contract() == []
    expected = load_deep_presentation_lock()["sections"]
    assert [len(expected[sid]["tables"]) for sid in ("S02", "S08", "S10")] == [2, 3, 2]


def test_s02_has_one_roster_and_one_ordered_identity_matched_audit():
    rendered = _visible("S02", {"rows": _our15_rows()})
    tables = _rendered_tables(rendered)
    assert len(tables) == 2
    assert [len(table["rows"]) for table in tables] == [15, 15]
    count, ids, names, errors = _s02_primary_visible_tables(rendered)
    assert count == 15 and not ids
    assert len(names) == len(set(names)) == 15
    assert not errors
    assert names == [f"P{index}" for index in range(15)]

    # Chelsea retrospective context is supplementary; its observations must
    # not displace either of the locked S02 15-player tables.
    rich_context = {
        "contract": "V12_GW1_GW6_RETROSPECTIVE_CONTEXT_V1",
        "official_players_in_universe": 667,
        "official_gw_slots_present": 6,
        "expected_official_gw_slots": 6,
        "official_points_finalized": False,
        "source_health": {"understat": {"verified_join_count": 1,
                                        "rejected_reasons": {"SOURCE_AFTER_REPORT_CUTOFF": 3}},
                          "fotmob": {"verified_match_count": 1,
                                     "rejected_reasons": {"UNFINISHED_OR_INVALID_SCORE": 2}}},
        "focus_team": {
            "form_gw1_gw6": {
                "wins": 1, "draws": 0, "losses": 0,
                "goals_for": 5, "goals_against": 1,
                "matches": [{"gw": 6, "opponent": "Bournemouth", "home": True,
                             "goals_for": 5, "goals_against": 1,
                             "result": "W", "fpl_points_settlement": "PROVISIONAL"}],
            },
            "tactical_observation": {
                "manager": "Xabi Alonso", "formation": "3-4-2-1",
                "status": "OBSERVED",
            },
        },
        "focus_players": [{
            "name": "Cole Palmer", "position": "MID",
            "provider_skill_observation": {
                "status": "VERIFIED",
                "metrics": {"games": 6, "time": 430, "goals": 3,
                            "assists": 2, "xg": 2.3, "xa": 1.4,
                            "xgi_per90": 0.77},
            },
        }],
    }
    rich_rendered = _visible(
        "S02", {"rows": _our15_rows(),
                "full_season_history": {"retrospective_context": rich_context}}
    )
    rich_tables = _rendered_tables(rich_rendered)
    rich_count, _, rich_names, rich_failures = _s02_primary_visible_tables(rich_rendered)
    assert len(rich_tables) == 2
    assert [len(table["rows"]) for table in rich_tables] == [15, 15]
    assert rich_count == 15 and not rich_failures
    assert rich_names == names
    assert "CHELSEA GW OBSERVATION: GW=6" in rich_rendered
    assert "FPL_status=PROVISIONAL" in rich_rendered
    assert "FOCUS PLAYER PROCESS: Player=Cole Palmer" in rich_rendered
    assert "SOURCE AFTER REPORT CUTOFF=3" in rich_rendered
    assert "UNFINISHED OR INVALID SCORE=2" in rich_rendered
    assert "rejected={" not in rich_rendered

    missing_context = dict(rich_context)
    missing_context["focus_team"] = dict(rich_context["focus_team"])
    missing_context["focus_team"]["form_gw1_gw6"] = {
        "observed_match_count": 0, "wins": 0, "draws": 0,
        "losses": 0, "goals_for": 0, "goals_against": 0, "matches": [],
    }
    absent = _visible("S02", {
        "rows": _our15_rows(),
        "full_season_history": {"retrospective_context": missing_context},
    })
    assert "CHELSEA GW1-GW6 OBSERVED RESULTS: UNAVAILABLE" in absent
    assert "not a 0W-0D-0L season record" in absent
    assert "CHELSEA GW1-GW6 OBSERVED RESULTS: 0W" not in absent
    conditioned_rows = _our15_rows()
    for row in conditioned_rows:
        row["p_start_evidence"]["signals"] = [
            "neutral_prior", "player_selection_posterior",
        ]
    conditioned = _visible("S02", {"rows": conditioned_rows})
    assert "15/15 shared rows have player-conditioned historical selection evidence" in conditioned
    assert "15/15 lack additional role/manager/normalized-availability" in conditioned
    assert "PSTART DIFFERENTIATION AUDIT: LIMITED_RESOLUTION" in conditioned
    assert [len(x["rows"]) for x in _rendered_tables(conditioned)] == [15, 15]



def test_s02_rejects_audit_player_identity_drift_not_a_false_30_player_squad():
    rendered = _visible("S02", {"rows": _our15_rows()})
    primary, secondary = rendered.split("#### PSTART EVIDENCE / DNP AUDIT", 1)
    secondary = secondary.replace("| P13 |", "| OTHER |", 1)
    count, _, names, errors = _s02_primary_visible_tables(
        primary + "#### PSTART EVIDENCE / DNP AUDIT" + secondary
    )
    assert count == 15 and len(names) == 15
    assert "VISIBLE_OUR15_AUDIT_IDENTITY_MISMATCH" in errors


def test_s08_has_existing_two_tables_plus_exact_five_row_tail_table():
    profiles = [{
        "player": f"P{index}", "football_rank": index + 1,
        "expected_points": 5.0, "p_start": 0.83, "xmins": 70,
        "p_blank": 0.4, "p_haul": 0.2, "p_ge_10": 0.2,
        "q90": 12.0, "p_ge_15": 0.06, "q75": 8.0,
        "variance": 20.0, "p_dnp": 0.09,
    } for index in range(5)]
    rendered = _visible("S08", {"captain_profiles": profiles, "decision_state": "PREPARE"})
    tables = _rendered_tables(rendered)
    expected = load_deep_presentation_lock()["sections"]["S08"]["tables"]
    assert len(tables) == 3
    assert [len(table["rows"]) for table in tables] == [5, 5, 5]
    assert [list(table["columns"]) for table in tables] == [row["columns"] for row in expected]
    assert "Joint C/VC MC: UNAVAILABLE" in rendered


def test_s10_has_existing_fifteen_price_rows_plus_fifteen_evidence_rows():
    rows = [
        {"player": f"P{i}", "current_price": 5.5,
         "direction": "RISE", "official_or_provider_progress": 92.0,
         "prediction_strength": None, "date_state": "DATE_UNAVAILABLE"}
        for i in range(15)
    ]
    rendered = _visible("S10", {"rows": rows})
    tables = _rendered_tables(rendered)
    expected = load_deep_presentation_lock()["sections"]["S10"]["tables"]
    assert len(tables) == 2
    assert [len(table["rows"]) for table in tables] == [15, 15]
    assert [list(table["columns"]) for table in tables] == [row["columns"] for row in expected]
    assert "NATIVE_FIELD 0/15 populated" in rendered
    assert "NOT_CALIBRATED" in rendered


def test_s15_counterpart_advisory_keeps_one_strict_evidence_table():
    """No/partial/full independent evidence must never add an uncontracted S15 table."""
    from src.engines.v12_deep_presentation_lock import _rendered_tables

    assessment = {
        "assessment_type": "CAPTAIN_VICE",
        "canonical": {
            "subject": "Palmer", "metric": "xPts", "value": 5.0,
            "horizon": "GW7", "as_of": "2026-10-16T21:30:00+07:00",
            "deadline": "2026-10-17T17:00:00+07:00",
        },
        "counterparts": [{
            "source": "Independent", "independence_group": "independent",
            "metric": "xPts", "horizon": "GW7", "value": 4.6,
            "as_of": "2026-10-16T20:00:00+07:00",
        }],
    }
    cases = [
        ({}, "INSUFFICIENT_EVIDENCE", False),
        ({"independent_counterpart": {"assessments": [assessment]}},
         "Independent comparison details (advisory):", True),
        ({"independent_counterpart": {"assessments": [assessment]},
          "independent_counterpart_coverage": {"status": "PARTIAL"}},
         "Independent coverage gate: PARTIAL", True),
        ({"independent_counterpart": {"assessments": [assessment]},
          "independent_counterpart_coverage": {"status": "PASS"}},
         "Independent coverage gate: PASS", True),
    ]
    for content, marker, has_assessment in cases:
        rendered = _visible("S15", content)
        tables = _rendered_tables(rendered)
        assert len(tables) == 1
        assert tables[0]["columns"] == (
            "Evidence domain", "Quality", "Decision impact"
        )
        assert marker in rendered
        if has_assessment:
            assert "CAPTAIN_VICE" in rendered
            assert "source" not in tables[0]["columns"]
            assert "Independent" in rendered
        else:
            assert "no occurrence-bound independent comparable assessment" in rendered
