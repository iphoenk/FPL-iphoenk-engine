from types import SimpleNamespace

from src.v5.services.truth import _chip_state
from src.v5.state import Phase


def _context(*, planning_gw: int, submitted_gw: int, current_gw: int, phase: Phase):
    return SimpleNamespace(
        planning_gw=planning_gw,
        submitted_gw=submitted_gw,
        current_gw=current_gw,
        phase=phase,
    )


def test_live_submitted_chip_does_not_leak_into_next_planning_gameweek():
    context = _context(planning_gw=3, submitted_gw=2, current_gw=2, phase=Phase.LIVE)
    result = _chip_state(
        context,
        {"wildcard_active": True},
        {"active_chip": "wildcard"},
        {"chips": []},
    )
    assert result["submitted_active_chip"] == "wildcard"
    assert result["submitted_chip_applies_to_planning_gw"] is False
    assert result["active_chip"] is None
    assert result["active_chip_count"] == 0
    assert result["legal"] is True


def test_submitted_chip_remains_active_when_submitted_and_planning_gw_match():
    context = _context(planning_gw=2, submitted_gw=2, current_gw=2, phase=Phase.POST_DEADLINE)
    result = _chip_state(
        context,
        {"wildcard_active": False},
        {"active_chip": "wildcard"},
        {"chips": []},
    )
    assert result["submitted_chip_applies_to_planning_gw"] is True
    assert result["active_chip"] == "wildcard"
    assert result["active_chip_count"] == 1
    assert result["legal"] is True
