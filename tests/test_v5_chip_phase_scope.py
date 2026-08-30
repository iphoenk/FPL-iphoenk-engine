from types import SimpleNamespace

from src.v5.services.truth import _chip_state, _lock_chip_scope


def _context(*, planning_gw: int, submitted_gw: int | None, phase: str = "PRE_DEADLINE"):
    return SimpleNamespace(
        planning_gw=planning_gw,
        current_gw=submitted_gw,
        submitted_gw=submitted_gw,
        phase=SimpleNamespace(value=phase),
    )


def test_unscoped_legacy_wildcard_flag_does_not_leak_into_next_planning_gw():
    context = _context(planning_gw=3, submitted_gw=2)
    state = _chip_state(
        context,
        {"wildcard_active": True},
        {"active_chip": "wildcard"},
        {"chips": [{"name": "wildcard", "event": 2}]},
    )

    assert state["active_chip"] is None
    assert state["active_chip_count"] == 0
    assert state["legal"] is True
    assert state["user_lock_chip_requested"] is True
    assert state["user_lock_chip_applies_to_planning_gw"] is False
    assert state["user_lock_chip_scope"] == "UNSCOPED_USER_CAPTURE_REJECTED"
    assert state["governance"]["chip_activation_is_gameweek_scoped"] is True
    assert state["governance"]["user_capture_requires_exact_target_gw"] is True


def test_unscoped_legacy_wildcard_flag_is_rejected_even_within_same_gw():
    context = _context(planning_gw=2, submitted_gw=2)
    state = _chip_state(context, {"wildcard_active": True}, None, {"chips": []})

    assert state["active_chip"] is None
    assert state["source"] is None
    assert state["user_lock_chip_applies_to_planning_gw"] is False
    assert state["user_lock_chip_scope"] == "UNSCOPED_USER_CAPTURE_REJECTED"


def test_explicit_target_gw_controls_chip_scope_independently_of_squad_persistence():
    applies, reason = _lock_chip_scope({"wildcard_active": True, "target_gw": 3}, planning_gw=3, submitted_gw=2)
    stale, stale_reason = _lock_chip_scope({"wildcard_active": True, "target_gw": 2}, planning_gw=3, submitted_gw=2)

    assert applies is True
    assert reason == "EXACT_TARGET_GW_MATCH"
    assert stale is False
    assert stale_reason == "EXPLICIT_GW_MISMATCH"


def test_exact_target_gw_is_rejected_when_official_submitted_gw_has_reclaimed_authority():
    applies, reason = _lock_chip_scope({"wildcard_active": True, "target_gw": 3}, planning_gw=3, submitted_gw=3)

    assert applies is False
    assert reason == "POST_DEADLINE_OFFICIAL_RECLAIMS_AUTHORITY"
