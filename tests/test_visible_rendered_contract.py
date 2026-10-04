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
