from src.v5.evaluation.shadow_parity import compare


def _v5(authority: str, owned_ids=range(1, 16)):
    return {
        "starting_xi": [{"element": i} for i in range(1, 12)],
        "lineup": {"captain": {"element": 3}},
        "user_report": {"captaincy": {"decision": "LOCK"}},
        "ruleset_id": "FPL_2026_27",
        "squad_authority": authority,
        "decision_squad_authority": authority,
        "team_summary": {"owned_ids": list(owned_ids)},
        "framework_health": {"gate0": {"pass": True}},
    }


def test_shadow_parity_accepts_structurally_equivalent_manual_decisions():
    v3 = {
        "starting_xi": [{"element": i} for i in range(1, 12)],
        "captain": 3,
        "captain_state": "LOCK",
        "ruleset_id": "FPL_2026_27",
        "manual_lock_authoritative": True,
        "legal": True,
    }
    result = compare(v3, _v5("user_capture"))
    assert result["pass"] is True
    assert result["required_real_cycles"] >= 3


def test_shadow_parity_accepts_legacy_predeadline_label_when_full_squad_matches_official_public():
    v3 = {
        "starting_xi": [{"element": i} for i in range(1, 12)],
        "squad_rows": [{"element": i} for i in range(1, 16)],
        "captain": 3,
        "ruleset_id": "FPL_2026_27",
        "decision_squad_authority": "pre_deadline_wc",
        "legal": True,
    }
    result = compare(v3, _v5("official_public"))
    assert result["pass"] is True
    assert result["checks"]["manual_lock"] is True
    assert result["authority_equivalence"]["full_identity_match"] is True
    assert result["authority_equivalence"]["legacy_predeadline_label_materially_equivalent_to_public"] is True


def test_shadow_parity_rejects_legacy_predeadline_label_when_public_squad_differs():
    v3 = {
        "starting_xi": [{"element": i} for i in range(1, 12)],
        "squad_rows": [{"element": i} for i in range(1, 16)],
        "captain": 3,
        "ruleset_id": "FPL_2026_27",
        "decision_squad_authority": "pre_deadline_wc",
        "legal": True,
    }
    result = compare(v3, _v5("official_public", owned_ids=list(range(1, 15)) + [99]))
    assert result["pass"] is False
    assert result["checks"]["manual_lock"] is False
    assert result["authority_equivalence"]["full_identity_match"] is False


def test_shadow_parity_maps_historical_v3_user_lock_to_v5_user_capture_only():
    v3 = {
        "starting_xi": [{"element": i} for i in range(1, 12)],
        "squad_rows": [{"element": i} for i in range(1, 16)],
        "captain": 3,
        "ruleset_id": "FPL_2026_27",
        "decision_squad_authority": "user_lock",
        "legal": True,
    }
    assert compare(v3, _v5("official_public"))["checks"]["manual_lock"] is False
    assert compare(v3, _v5("user_capture"))["checks"]["manual_lock"] is True
    assert compare(v3, _v5("user_lock"))["checks"]["manual_lock"] is False


def test_shadow_parity_rejects_locked_captain_mismatch():
    v3 = {
        "starting_xi": [{"element": i} for i in range(1, 12)],
        "captain": 3,
        "captain_state": "LOCK",
    }
    v5 = {
        "starting_xi": [{"element": i} for i in range(1, 12)],
        "lineup": {"captain": {"element": 4}},
        "user_report": {"captaincy": {"decision": "LOCK"}},
    }
    assert compare(v3, v5)["pass"] is False
