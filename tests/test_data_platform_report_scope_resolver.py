from __future__ import annotations

from src.runtime_v6.report_contract import (
    resolve_report_scope,
    resolve_report_scope_matrix,
)


def _scope(**overrides):
    base = {
        "required": True,
        "auth_required": False,
        "volatile": True,
        "fresh_v6_available": True,
        "v6_scope_state": "CURRENT",
        "retrieval_state": "COMPLETE",
        "direct_fresh_available": False,
        "last_good_available": False,
    }
    base.update(overrides)
    return base


def test_public_required_scope_ignores_expired_auth_and_reads_fresh_v6():
    result = resolve_report_scope(
        scope_id="official_universe",
        auth_status="EXPIRED",
        **_scope(),
    )

    assert result["source"] == "FRESH_V6"
    assert result["action"] == "READ_V6"
    assert result["status"] == "PASS"
    assert result["report_blocking"] is False
    assert result["degraded"] is False
    assert result["legacy_fallback_allowed"] is False


def test_private_auth_scope_expired_degrades_only_that_scope_and_never_blocks_report():
    result = resolve_report_scope(
        scope_id="private_ft_itb_sell_value",
        auth_status="EXPIRED",
        **_scope(required=False, auth_required=True),
    )

    assert result["source"] == "PRIVATE_AUTH_UNAVAILABLE"
    assert result["action"] == "DISCLOSE_PRIVATE_AUTH_UNAVAILABLE"
    assert result["status"] == "DEGRADED"
    assert result["report_blocking"] is False
    assert result["degraded"] is True
    assert result["direct_fresh_allowed"] is False
    assert result["legacy_fallback_allowed"] is False
    assert result["reason"] == "AUTH_EXPIRED"


def test_private_auth_scope_with_valid_auth_uses_normal_v6_path():
    result = resolve_report_scope(
        scope_id="private_ft_itb_sell_value",
        auth_status="OK",
        **_scope(required=False, auth_required=True),
    )

    assert result["source"] == "FRESH_V6"
    assert result["status"] == "PASS"
    assert result["report_blocking"] is False


def test_healthy_required_scope_truncation_requires_same_v6_retrieval_recovery_first():
    result = resolve_report_scope(
        scope_id="watchlist20",
        auth_status="EXPIRED",
        **_scope(retrieval_state="CONNECTOR_TRUNCATED"),
    )

    assert result["source"] == "V6_RETRIEVAL_RECOVERY"
    assert result["action"] == "SAME_V6_RETRIEVAL_RECOVERY"
    assert result["status"] == "RECOVERY_REQUIRED"
    assert result["report_blocking"] is True
    assert result["direct_fresh_allowed"] is False
    assert result["legacy_fallback_allowed"] is False


def test_verified_v6_scope_failure_can_use_scoped_direct_fresh_for_that_scope_only():
    result = resolve_report_scope(
        scope_id="price_predictor",
        auth_status="NOT REQUESTED",
        **_scope(
            fresh_v6_available=False,
            v6_scope_state="V6_SCOPE_FAILED",
            direct_fresh_available=True,
        ),
    )

    assert result["source"] == "DIRECT_FRESH"
    assert result["action"] == "SCOPED_DIRECT_FRESH"
    assert result["status"] == "PASS"
    assert result["report_blocking"] is False
    assert result["direct_fresh_allowed"] is True
    assert result["legacy_fallback_allowed"] is False


def test_nonvolatile_scope_may_use_last_good_only_after_v6_scope_is_unavailable():
    result = resolve_report_scope(
        scope_id="submitted_picks",
        auth_status="NOT REQUESTED",
        **_scope(
            volatile=False,
            fresh_v6_available=False,
            v6_scope_state="V6_SCOPE_MISSING",
            direct_fresh_available=False,
            last_good_available=True,
        ),
    )

    assert result["source"] == "LAST_GOOD_NONVOLATILE"
    assert result["action"] == "READ_LAST_GOOD_NONVOLATILE"
    assert result["status"] == "PASS"
    assert result["report_blocking"] is False
    assert result["legacy_fallback_allowed"] is False


def test_required_volatile_scope_without_valid_source_is_blocking_and_disclosed():
    result = resolve_report_scope(
        scope_id="live",
        auth_status="NOT REQUESTED",
        **_scope(
            fresh_v6_available=False,
            v6_scope_state="V6_SCOPE_MISSING",
            direct_fresh_available=False,
            last_good_available=True,
        ),
    )

    assert result["source"] == "UNAVAILABLE"
    assert result["action"] == "DISCLOSE_REQUIRED_SCOPE_UNAVAILABLE"
    assert result["status"] == "BLOCKED"
    assert result["report_blocking"] is True
    assert result["legacy_fallback_allowed"] is False


def test_matrix_auth_expiration_degrades_private_scope_but_keeps_public_deep_report_ready():
    matrix = resolve_report_scope_matrix(
        {
            "official_universe": _scope(),
            "fixtures": _scope(),
            "price_predictor": _scope(),
            "icon_mini_league": _scope(),
            "private_ft_itb_sell_value": _scope(required=False, auth_required=True),
        },
        auth_status="EXPIRED",
    )

    assert matrix["report_ready"] is True
    assert matrix["blocking_scopes"] == []
    assert matrix["degraded_scopes"] == ["private_ft_itb_sell_value"]
    assert matrix["scopes"]["official_universe"]["source"] == "FRESH_V6"
    assert matrix["scopes"]["private_ft_itb_sell_value"]["reason"] == "AUTH_EXPIRED"
    assert matrix["legacy_fallback_allowed"] is False


def test_matrix_keeps_scope_failures_independent_instead_of_blocking_unrelated_scopes():
    matrix = resolve_report_scope_matrix(
        {
            "official_universe": _scope(
                fresh_v6_available=False,
                v6_scope_state="V6_SCOPE_FAILED",
                direct_fresh_available=True,
            ),
            "price_predictor": _scope(),
            "icon_mini_league": _scope(),
        },
        auth_status="NOT REQUESTED",
    )

    assert matrix["report_ready"] is True
    assert matrix["scopes"]["official_universe"]["source"] == "DIRECT_FRESH"
    assert matrix["scopes"]["price_predictor"]["source"] == "FRESH_V6"
    assert matrix["scopes"]["icon_mini_league"]["source"] == "FRESH_V6"


def test_matrix_is_not_ready_when_a_required_public_scope_remains_unavailable():
    matrix = resolve_report_scope_matrix(
        {
            "official_universe": _scope(),
            "fixtures": _scope(
                fresh_v6_available=False,
                v6_scope_state="V6_SCOPE_MISSING",
                direct_fresh_available=False,
                last_good_available=False,
            ),
            "private_ft_itb_sell_value": _scope(required=False, auth_required=True),
        },
        auth_status="EXPIRED",
    )

    assert matrix["report_ready"] is False
    assert matrix["blocking_scopes"] == ["fixtures"]
    assert matrix["degraded_scopes"] == ["private_ft_itb_sell_value"]
    assert matrix["legacy_fallback_allowed"] is False
