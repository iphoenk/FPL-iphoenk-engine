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
