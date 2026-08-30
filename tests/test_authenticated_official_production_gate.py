from src.engines.authenticated_official import _production_readiness, _safe_finance


def _my_team():
    return {
        "transfers": {"bank": 5, "value": 1006, "made": 0, "cost": 0},
        "picks": [
            {"element": i, "purchase_price": 50 + i, "selling_price": 49 + i}
            for i in range(1, 16)
        ],
        "chips": [],
    }


def test_private_finance_uses_current_private_squad_not_previous_submitted_squad():
    payload = _my_team()
    # Previous submitted squad deliberately differs by one element.
    authoritative = set(range(1, 15)) | {99}
    finance = _safe_finance(payload, authoritative)

    assert finance["private_squad_coverage"] == {"expected": 15, "covered": 15, "complete": True}
    assert finance["private_exact_sell_total"] is not None
    assert finance["private_exact_purchase_total"] is not None
    assert finance["coverage"]["complete"] is False
    assert len(finance["prices_for_private_squad"]) == 15


def test_disabled_auth_remains_non_blocking():
    readiness = _production_readiness({"mode": "disabled", "state": "DISABLED"})
    assert readiness == {"required": False, "ready": True, "reasons": []}


def test_configured_auth_requires_exact_entry_endpoints_and_private_state():
    summary = {
        "mode": "session_cookie",
        "state": "VALID",
        "verified_entry": 3462711,
        "endpoint_health": {
            "me": {"status": "LIVE"},
            "my_team": {"status": "LIVE"},
            "transfers_latest": {"status": "LIVE"},
        },
        "safe_finance": {
            "private_squad_coverage": {"expected": 15, "covered": 15, "complete": True},
            "private_exact_sell_total": 995,
            "private_exact_purchase_total": 1000,
        },
        "chip_state": {"available": True, "chips": []},
        "transfers_latest": {"available": True, "count": 0},
        "raw_authenticated_payload_persisted": False,
    }
    readiness = _production_readiness(summary)
    assert readiness["required"] is True
    assert readiness["ready"] is True
    assert readiness["reasons"] == []


def test_configured_auth_rejects_partial_or_incomplete_state():
    summary = {
        "mode": "session_cookie",
        "state": "PARTIAL",
        "verified_entry": None,
        "endpoint_health": {},
        "safe_finance": {},
        "chip_state": {"available": False},
        "transfers_latest": {"available": False},
        "raw_authenticated_payload_persisted": False,
    }
    readiness = _production_readiness(summary)
    assert readiness["required"] is True
    assert readiness["ready"] is False
    assert "entry_not_verified" in readiness["reasons"]
    assert "private_squad_finance_incomplete" in readiness["reasons"]
