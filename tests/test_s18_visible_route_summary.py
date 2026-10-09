"""S18 presents canonical alternatives without leaking raw optimizer dictionaries."""

from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines


def _render(board):
    lines, _ = _render_deep_visible_contract_lines(
        section_id="S18",
        content={"action_board": board},
        owned_ids=set(),
        owned_names={},
    )
    return "\n".join(lines)


def test_s18_best_alternative_is_bounded_readable_table():
    board = {
        "axes": [],
        "best_alternative_executable": False,
        "best_alternative": {
            "route": "R1",
            "route_kind": "DIRECT / 1-TRANSFER",
            "moves": {
                "out": [{"element": 426, "name": "Bruno Fernandes"}],
                "in": [{"element": 54, "name": "Candidate 54"}],
            },
            "executable": True,  # Board's more conservative state prevails.
            "execution_economics_status": "UNAVAILABLE",
            "transfer_cost": {"hit": 4, "huge_private_model": "nested_canary"},
            "gw1_net": -0.45,
            "three_gw": 1.23,
            "five_gw": 2.56,
            "p_beats_hold": 0.47,
            "robustness": {"status": "FAIL", "huge": "nested_canary"},
            "action_verdict": "WAIT",
            "dynamic_matchup": {"deeply_nested": {"value": "nested_canary"}},
        },
    }
    visible = _render(board)
    for expected in (
        "### BEST ALTERNATIVE",
        "| Route | R1 |",
        "| Route type | DIRECT / 1-TRANSFER |",
        "| Outgoing | Bruno Fernandes |",
        "| Incoming | Candidate 54 |",
        "| Executable | NO |",
        "| Hit (pts) | 4 |",
        "| 1GW net delta (pts) | -0.45 |",
        "| 3GW net delta (pts) | 1.23 |",
        "| 5GW net delta (pts) | 2.56 |",
        "| P(beats HOLD) | 0.47 |",
        "| Robustness | FAIL |",
        "| Action verdict | WAIT |",
        "Alternative only; governing transfer action remains in S14/S19.",
    ):
        assert expected in visible
    assert "nested_canary" not in visible
    assert "dynamic matchup" not in visible.lower()
    assert len(visible) < 2300


def test_s18_no_alternative_is_explicitly_unavailable():
    visible = _render({"axes": [], "best_alternative": None})
    assert "### BEST ALTERNATIVE" in visible
    assert "Alternative: UNAVAILABLE" in visible


def test_s18_missing_route_fields_are_not_invented():
    visible = _render({"axes": [], "best_alternative": {"route": "HOLD"}})
    assert "| Route | HOLD |" in visible
    assert "| Outgoing | UNAVAILABLE |" in visible
    assert "| Incoming | UNAVAILABLE |" in visible
    assert "| 1GW net delta (pts) | UNAVAILABLE |" in visible
    assert "| Executable | UNAVAILABLE |" in visible
