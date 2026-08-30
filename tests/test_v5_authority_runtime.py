from types import SimpleNamespace

import pytest

from src.v5.authenticated_official import safe_finance, summarize_authenticated_payloads
from src.v5.services import truth
from src.v5.services.truth import _lock_chip_scope
from src.v5.squad import planning_override_state, select_squad
from src.v5.state import Phase, authority_chain


def _inputs():
    element_types = [1, 1] + [2] * 5 + [3] * 5 + [4] * 4
    teams = [{"id": team_id, "name": f"Team {team_id}"} for team_id in range(1, 9)]
    elements = []
    for eid, element_type in enumerate(element_types, start=1):
        team_id = ((eid - 1) % 8) + 1
        elements.append(
            {
                "id": eid,
                "web_name": f"P{eid}",
                "team": team_id,
                "element_type": element_type,
                "now_cost": 50,
            }
        )
    bootstrap = {"elements": elements, "teams": teams}
    lock = {
        "players": [
            {
                "element": eid,
                "position": {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}[elements[eid - 1]["element_type"]],
                "expected_web_name": f"P{eid}",
                "expected_team": f"Team {elements[eid - 1]['team']}",
                "purchase_cost": 50,
            }
            for eid in range(1, 16)
        ]
    }
    submitted = {"picks": [{"element": eid} for eid in [*range(1, 15), 16]]}
    authenticated = {
        "picks": [
            {"element": eid, "purchase_price": 45 + (eid % 2), "selling_price": 50}
            for eid in range(1, 16)
        ],
        "transfers": {"bank": 5, "value": 1000, "made": 0, "cost": 0},
    }
    return bootstrap, lock, submitted, authenticated


def _active(lock, *, target_gw=3, wildcard=False, free_hit=False, manual=True):
    return {
        **lock,
        "target_gw": target_gw,
        "planning_override_active": bool(manual and not wildcard and not free_hit),
        "wildcard_active": wildcard,
        "free_hit_active": free_hit,
    }


def _select(lock, *, phase=Phase.PRE_DEADLINE, submitted=None, authenticated=None, planning_gw=3, submitted_gw=2):
    bootstrap, _, default_submitted, default_authenticated = _inputs()
    return select_squad(
        phase=phase,
        bootstrap=bootstrap,
        locked_squad=lock,
        authenticated_my_team=default_authenticated if authenticated is None else authenticated,
        submitted_picks=default_submitted if submitted is None else submitted,
        planning_gw=planning_gw,
        submitted_gw=submitted_gw,
    )


def test_predeadline_decision_authority_chains_exclude_authenticated_official():
    for domain in ("squad", "lineup", "captaincy"):
        chain = authority_chain(Phase.PRE_DEADLINE, domain)
        assert chain == ("user_capture", "official_public")
        assert "official_authenticated" not in chain


def test_valid_exact_target_planning_capture_overrides_public_baseline():
    _, lock, _, _ = _inputs()
    resolved = _select(_active(lock, target_gw=3))
    assert resolved["authority"] == "user_capture"
    assert [row["element"] for row in resolved["squad"]] == list(range(1, 16))
    assert resolved["projection_baseline"]["default_authority"] == "official_public"
    assert resolved["projection_baseline"]["override_applied"] is True
    assert resolved["validation"]["passed"] is True


@pytest.mark.parametrize("flag", ["wildcard", "free_hit"])
def test_valid_exact_target_chip_capture_overrides_public_baseline(flag):
    _, lock, _, _ = _inputs()
    resolved = _select(
        _active(
            lock,
            target_gw=3,
            wildcard=flag == "wildcard",
            free_hit=flag == "free_hit",
            manual=False,
        )
    )
    assert resolved["authority"] == "user_capture"
    assert resolved["projection_baseline"]["override_kind"] == ("WILDCARD" if flag == "wildcard" else "FREE_HIT")


def test_target_gw_mismatch_rejects_capture_and_uses_public():
    _, lock, submitted, _ = _inputs()
    resolved = _select(_active(lock, target_gw=2))
    assert resolved["authority"] == "official_public"
    assert [row["element"] for row in resolved["squad"]] == [row["element"] for row in submitted["picks"]]
    assert resolved["projection_baseline"]["override_rejection_reason"] == "TARGET_GW_MISMATCH"
    assert resolved["projection_baseline"]["stale_override_rejected"] is True


def test_inactive_capture_does_not_override_public_even_when_target_matches():
    _, lock, _, _ = _inputs()
    inactive = {**lock, "target_gw": 3}
    resolved = _select(inactive)
    assert resolved["authority"] == "official_public"
    assert resolved["projection_baseline"]["override_requested"] is False
    assert resolved["projection_baseline"]["override_applied"] is False


def test_unscoped_active_capture_never_masks_public_submitted_team():
    _, lock, _, _ = _inputs()
    unscoped = {**lock, "wildcard_active": True}
    resolved = _select(unscoped)
    assert resolved["authority"] == "official_public"
    assert resolved["projection_baseline"]["override_rejection_reason"] == "MISSING_TARGET_GW"


@pytest.mark.parametrize("flag", ["wildcard_active", "free_hit_active"])
def test_stale_wc_or_fh_flag_does_not_reactivate_next_planning_gw(flag):
    _, lock, _, _ = _inputs()
    stale = {**lock, "target_gw": 2, flag: True}
    resolved = _select(stale, planning_gw=3, submitted_gw=2)
    assert resolved["authority"] == "official_public"
    assert resolved["projection_baseline"]["override_rejection_reason"] == "TARGET_GW_MISMATCH"


def test_official_public_reclaims_authority_post_deadline():
    _, lock, submitted, authenticated = _inputs()
    resolved = _select(
        _active(lock, target_gw=3, wildcard=True, manual=False),
        phase=Phase.POST_DEADLINE,
        submitted=submitted,
        authenticated=authenticated,
        planning_gw=3,
        submitted_gw=3,
    )
    assert resolved["authority"] == "official_public"
    assert [row["element"] for row in resolved["squad"]] == [row["element"] for row in submitted["picks"]]
    assert resolved["projection_baseline"]["post_deadline_official_reclaims_authority"] is True


def test_valid_authenticated_draft_does_not_supersede_public_squad_authority():
    _, lock, submitted, authenticated = _inputs()
    resolved = _select(lock, submitted=submitted, authenticated=authenticated)
    assert resolved["authority"] == "official_public"
    assert [row["element"] for row in resolved["squad"]] == [row["element"] for row in submitted["picks"]]
    assert resolved["authority_policy"]["authenticated_official_must_not_select_squad"] is True


def test_auth_failure_does_not_block_public_path():
    bootstrap, lock, submitted, _ = _inputs()
    resolved = select_squad(
        phase=Phase.PRE_DEADLINE,
        bootstrap=bootstrap,
        locked_squad=lock,
        authenticated_my_team=None,
        submitted_picks=submitted,
        planning_gw=3,
        submitted_gw=2,
    )
    assert resolved["authority"] == "official_public"
    assert resolved["validation"]["passed"] is True


def test_invalid_capture_identity_is_rejected_then_public_is_validated():
    _, lock, _, _ = _inputs()
    players = [dict(row) for row in lock["players"]]
    players[0]["expected_web_name"] = "WRONG"
    invalid = _active({**lock, "players": players}, target_gw=3)
    resolved = _select(invalid)
    assert resolved["authority"] == "official_public"
    baseline = resolved["projection_baseline"]
    assert baseline["invalid_override_rejected"] is True
    assert baseline["override_rejection_reason"] == "INVALID_USER_CAPTURE"
    assert "locked name mismatch" in baseline["override_validation_error"]
    assert resolved["validation"]["passed"] is True


def test_invalid_capture_legality_is_rejected_then_public_is_validated():
    _, lock, _, _ = _inputs()
    invalid = _active({**lock, "players": lock["players"][:-1]}, target_gw=3)
    resolved = _select(invalid)
    assert resolved["authority"] == "official_public"
    assert resolved["projection_baseline"]["invalid_override_rejected"] is True
    assert resolved["projection_baseline"]["override_rejection_reason"] == "INVALID_USER_CAPTURE"
    assert resolved["validation"]["passed"] is True


def test_invalid_capture_without_public_baseline_fails_closed():
    bootstrap, lock, _, authenticated = _inputs()
    invalid = _active({**lock, "players": lock["players"][:-1]}, target_gw=3)
    with pytest.raises(RuntimeError, match="no usable V5 squad authority"):
        select_squad(
            phase=Phase.PRE_DEADLINE,
            bootstrap=bootstrap,
            locked_squad=invalid,
            authenticated_my_team=authenticated,
            submitted_picks=None,
            planning_gw=3,
            submitted_gw=2,
        )


def test_invalid_target_scope_is_rejected_without_blocking_public_fallback():
    state = planning_override_state(
        {"players": [{"element": 1}], "free_hit_active": True, "target_gw": "not-a-gw"},
        planning_gw=3,
        submitted_gw=2,
    )
    assert state["override_applied"] is False
    assert state["override_rejection_reason"] == "INVALID_TARGET_GW"
    assert state["effective_authority"] == "official_public"


def test_chip_scope_requires_exact_target_gw_and_rejects_legacy_aliases():
    for legacy in ({"planning_gw": 3}, {"gameweek": 3}, {"gw": 3}, {}):
        assert _lock_chip_scope(legacy, planning_gw=3, submitted_gw=2) == (
            False,
            "UNSCOPED_USER_CAPTURE_REJECTED",
        )
    assert _lock_chip_scope({"target_gw": 3}, planning_gw=3, submitted_gw=2) == (
        True,
        "EXACT_TARGET_GW_MATCH",
    )
    assert _lock_chip_scope({"target_gw": 2}, planning_gw=3, submitted_gw=2) == (
        False,
        "EXPLICIT_GW_MISMATCH",
    )
    assert _lock_chip_scope({"target_gw": 3}, planning_gw=3, submitted_gw=3) == (
        False,
        "POST_DEADLINE_OFFICIAL_RECLAIMS_AUTHORITY",
    )


def test_authenticated_finance_enrichment_and_no_raw_persistence_are_preserved():
    _, _, _, authenticated = _inputs()
    finance = safe_finance(authenticated, set(range(1, 16)))
    assert finance["bank"] == 5
    assert finance["coverage"]["complete"] is True
    summary = summarize_authenticated_payloads(
        me={"player": {"entry": 3462711}},
        my_team=authenticated,
        transfers_latest=[],
        authoritative_elements=set(range(1, 16)),
    )
    assert summary["raw_authenticated_payload_persisted"] is False


def test_truth_assemble_passes_event_gw_scope_into_team_service(monkeypatch):
    captured = {}
    context = SimpleNamespace(
        phase=Phase.PRE_DEADLINE,
        planning_gw=3,
        submitted_gw=2,
        current_gw=2,
        scoring_gw=2,
        is_live_event=False,
    )

    monkeypatch.setattr(truth, "build_event_context", lambda bootstrap, now=None: context)
    monkeypatch.setattr(truth, "context_dict", lambda value: {"phase": value.phase.value})
    monkeypatch.setattr(truth, "build_index", lambda bootstrap: object())

    def fake_build_team_state(**kwargs):
        captured.update(kwargs)
        return {"validation": {"passed": True}, "finance": {}, "squad": [], "owned_ids": []}

    monkeypatch.setattr(truth, "build_team_state", fake_build_team_state)
    monkeypatch.setattr(truth, "personalized_live_score", lambda **kwargs: {})
    monkeypatch.setattr(truth, "_match_state", lambda fixtures, scoring_gw: {})
    monkeypatch.setattr(truth, "_chip_state", lambda context, lock, submitted, history: {"legal": True})

    truth.handle(
        "assemble",
        {
            "bootstrap": {"elements": [], "teams": []},
            "locked_squad": {},
            "auth_runtime": {},
            "dynamic": {},
            "base": {},
        },
    )
    assert captured["planning_gw"] == 3
    assert captured["submitted_gw"] == 2
