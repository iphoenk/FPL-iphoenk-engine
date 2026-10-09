from src.engines.v12_report_orchestration import _render_package_frontier_lines
from src.runtime_v6.domains.report_plane.report_qa import _required_visible_markers


def test_s14_nested_robustness_is_human_facing():
    body = "\n".join(
        _render_package_frontier_lines(
            {
                "selected_route_id": "HOLD",
                "routes": [
                    {
                        "route": "BUY",
                        "robustness": {
                            "classification": "FRAGILE",
                            "rules": {"automatic_retuning": False},
                        },
                    }
                ],
            },
            section_state="COMPLETE",
        )
    )
    assert "Robustness: classification=FRAGILE; rules: automatic_retuning=False" in body
    assert "{'classification'" not in body


def test_deep_does_not_require_match_scout_markers():
    markers = _required_visible_markers("DEEP")
    assert "MULTI-AXIS ACTION BOARD" in markers
    assert "MINUTES/SUBS:" not in markers
    assert "XG/XA/XGI/SHOTS/CHANCES:" not in markers



def test_s14_and_s14b_contract_markers_are_visible():
    from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines

    s14, _ = _render_deep_visible_contract_lines(
        section_id="S14",
        content={"package_search_proof": {"eligible_universe_evaluated": 1000, "eligible_universe_expected": 1000, "legal_route_count": 42}},
        owned_ids=set(),
        owned_names={},
    )
    s14b, _ = _render_deep_visible_contract_lines(
        section_id="S14B",
        content={"staging_rows": []},
        owned_ids=set(),
        owned_names={},
    )
    assert any("UNIVERSE SCAN / OPTIMAL TEAM IMPACT:" in line for line in s14)
    assert any("MULTI-GW PLAN / CONTINGENCY:" in line for line in s14b)


def test_match_scout_nested_values_are_not_python_repr():
    from src.engines.v12_report_orchestration import _render_match_scout_lines

    body = "\n".join(_render_match_scout_lines([{"fixture_id": 1, "result": {"state": "DRAW"}}]))
    assert "RESULT: state=DRAW" in body
    assert "{'state'" not in body


def test_s05_renders_readable_fixture_cards_instead_of_raw_fixture_objects():
    from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines

    lines, _ = _render_deep_visible_contract_lines(
        section_id="S05",
        content={
            "gw_topology": "NORMAL_GW",
            "fixtures_display": [
                {
                    "fixture_id": 51,
                    "match": "Arsenal vs Leeds",
                    "home_team": "Arsenal",
                    "away_team": "Leeds",
                    "home_away": "H",
                    "kickoff_wib": "10 Oct 2026, 18:30 WIB",
                    "fixture_status": "NOT STARTED",
                    "rest_days": "UNAVAILABLE",
                    "venue": "Emirates Stadium",
                    "venue_status": "VERIFIED",
                    "weather": "LOW",
                    "weather_state": "FORECAST",
                    "weather_freshness": "FRESH",
                    "weather_fixture_id": 51,
                    "weather_kickoff": "2026-10-10T11:30:00+00:00",
                }
            ],
            "fixtures": [{"id": 51, "team_h": 1, "team_a": 13}],
            "competition_coverage": {},
            "player_workload": [],
            "weather": [],
        },
        owned_ids=set(),
        owned_names={},
    )
    body = "\n".join(lines)
    assert "Arsenal vs Leeds" in body
    assert "Emirates Stadium" in body
    assert "| Fixture | Match | Sides | Kickoff (WIB) | Rest days | Venue | Status | Weather |" in body
    assert "{'id': 51" not in body
    assert "fixture id=51" not in body


def test_s06_requires_canonical_pitch_and_separate_bench_surface():
    from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines

    xi = [
        {"name": "FWD One", "position": "FWD"},
        {"name": "MID One", "position": "MID", "is_captain": True},
        {"name": "MID Two", "position": "MID", "is_vice_captain": True},
        {"name": "DEF One", "position": "DEF"},
        {"name": "GK One", "position": "GK"},
    ]
    lines, _ = _render_deep_visible_contract_lines(
        section_id="S06",
        content={
            "formation": "1-1-2-1",
            "starting_xi": xi,
            "bench": {"bench_gk": {"name": "GK Bench"}, "outfield_autosub_priority": [{"name": "Bench 1"}]},
            "xi_base_xpts": 50.0,
            "captain_adjusted_xpts": 55.0,
        },
        owned_ids=set(),
        owned_names={},
    )
    body = "\n".join(lines)
    assert "s06-pitch" in body
    assert "GK Bench" in body
    assert "Bench 1" in body
    assert "captain-adjusted xPts" in body
