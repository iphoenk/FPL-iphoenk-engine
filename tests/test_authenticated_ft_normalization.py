"""Regression contracts for Official FPL authenticated FT allowance normalization."""
from __future__ import annotations

import pytest

from src.runtime_v6.domains.report_plane.personal_prefetch import (
    normalise_authenticated_free_transfers,
    normalise_team,
)


@pytest.mark.parametrize(
    "transfers,expected,source",
    [
        ({"bank": 2, "limit": 1, "made": 0}, 1, "AUTHENTICATED_LIMIT_MINUS_MADE"),
        ({"bank": 2, "limit": 2, "made": 1}, 1, "AUTHENTICATED_LIMIT_MINUS_MADE"),
        ({"bank": 2, "limit": 3, "made": 4, "cost": 4}, 0, "AUTHENTICATED_LIMIT_MINUS_MADE"),
        ({"bank": 2, "limit": 5, "made": 0}, 5, "AUTHENTICATED_LIMIT_MINUS_MADE"),
        ({"bank": 2, "limit": None, "made": 4}, None, "UNLIMITED"),
        ({"bank": 2, "made": 0}, None, "NOT_SUPPORTED"),
        ({"bank": 2, "limit": 3}, None, "NOT_SUPPORTED"),
        ({"bank": 2, "limit": True, "made": 0}, None, "NOT_SUPPORTED"),
        ({"bank": 2, "limit": 8, "made": 0}, None, "NOT_SUPPORTED"),
        ({"bank": 2, "limit": 1, "made": -1}, None, "NOT_SUPPORTED"),
        ({"bank": 2, "free_transfers": 2, "limit": 5, "made": 1}, 2, "OFFICIAL_EXPLICIT"),
    ],
)
def test_private_allowance_follows_authenticated_fields_only(transfers, expected, source):
    assert normalise_authenticated_free_transfers(transfers) == (expected, source)


def _normalised(transfers, auth_state="AVAILABLE"):
    return normalise_team(
        entry_id=3462711,
        gw=6,
        element_index={},
        bootstrap_lineage=None,
        submitted={"picks": [], "lineage": {}},
        auth_state=auth_state,
        my_team_payload={
            "picks": [
                {"element": i, "purchase_price": 45, "selling_price": 44}
                for i in range(1, 16)
            ],
            "transfers": transfers,
        },
        auth_lineage=[],
        generated_at="2026-10-11T06:02:36+07:00",
    )


def test_current_authenticated_snapshot_recovers_ft_and_tracks_provenance():
    team = _normalised({"bank": 2, "limit": 2, "made": 1, "cost": 0})
    assert team["squad_state"] == "AUTHENTICATED_CURRENT_TEAM"
    assert team["free_transfers"] == 1
    assert team["free_transfers_source"] == "AUTHENTICATED_LIMIT_MINUS_MADE"
    assert team["availability"]["free_transfers"] == "AVAILABLE"
    assert team["governance"]["free_transfers_are_not_derived"] is False
    assert team["governance"]["free_transfers_from_authenticated_limit_made_only"] is True
    assert team["bank"] == 2


def test_unlimited_does_not_fabricate_integer_free_transfers():
    team = _normalised({"bank": 2, "limit": None, "made": 6})
    assert team["free_transfers"] is None
    assert team["free_transfers_source"] == "UNLIMITED"
    assert team["availability"]["free_transfers"] == "UNLIMITED"


def test_auth_failure_must_not_expose_transfer_finance_from_payload():
    team = _normalised({"bank": 2, "limit": 4, "made": 1}, auth_state="AUTH_EXPIRED")
    assert team["free_transfers"] is None
    assert team["availability"]["free_transfers"] == "NOT_SUPPORTED"
