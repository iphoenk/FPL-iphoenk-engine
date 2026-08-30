import pytest

from src.v5.shadow_cycle import _predeadline_authority_checks


def _v5(authority: str, auth_state: str = "DISABLED"):
    return {
        "phase": {"phase": "PRE_DEADLINE"},
        "squad_authority": authority,
        "decision_squad_authority": authority,
        "authenticated_official": {
            "state": auth_state,
            "expected_entry": 3462711,
            "verified_entry": 3462711 if auth_state == "VALID" else None,
            "draft_integrity": {"count": 15, "matches_authoritative_squad": True} if auth_state == "VALID" else {},
            "raw_authenticated_payload_persisted": False,
        },
    }


def test_public_submitted_is_valid_predeadline_fallback_when_auth_unavailable():
    checks, proof = _predeadline_authority_checks(
        _v5("official_public"),
        3462711,
        require_authenticated=False,
        require_official_submitted=True,
    )
    assert all(checks.values())
    assert proof["authority"] == "official_public"
    assert proof["public_submitted_semantics"] == "LAST_CONFIRMED_SUBMITTED_TEAM_NOT_UNSUBMITTED_DRAFT"


def test_public_submitted_proof_rejects_stale_user_lock():
    checks, _ = _predeadline_authority_checks(
        _v5("user_lock"),
        3462711,
        require_authenticated=False,
        require_official_submitted=True,
    )
    assert checks["official_submitted_authority_pre_deadline"] is False


def test_authenticated_proof_still_requires_valid_private_draft():
    checks, _ = _predeadline_authority_checks(
        _v5("official_authenticated", auth_state="VALID"),
        3462711,
        require_authenticated=True,
        require_official_submitted=False,
    )
    assert all(checks.values())


def test_shadow_trigger_cannot_require_two_mutually_exclusive_predeadline_authorities():
    with pytest.raises(RuntimeError):
        _predeadline_authority_checks(
            _v5("official_authenticated", auth_state="VALID"),
            3462711,
            require_authenticated=True,
            require_official_submitted=True,
        )
