import pytest

from src.runtime_v6.domains.report_plane.public_last_deadline import (
    PublicIdentityGap,
    public_last_deadline_eligible,
    purchase_prices_from_transfer_history,
    selling_price_tenths,
)


def test_selling_price_profit_even():
    assert selling_price_tenths(purchase_price=50, current_price=54) == 52


def test_selling_price_profit_odd_floors_half_profit():
    assert selling_price_tenths(purchase_price=50, current_price=53) == 51


def test_selling_price_price_drop():
    assert selling_price_tenths(purchase_price=50, current_price=47) == 47


def test_selling_price_unchanged():
    assert selling_price_tenths(purchase_price=50, current_price=50) == 50


def test_transfer_history_proves_transferred_in_acquisition_cost():
    prices = purchase_prices_from_transfer_history(
        last_deadline_elements=[2],
        transfer_history=[
            {
                "element_out": 1,
                "element_in": 2,
                "element_in_cost": 61,
                "time": "2026-09-01T10:00:00Z",
            }
        ],
        initial_purchase_prices={1: 50},
    )
    assert prices == {2: 61}


def test_initial_purchase_price_gap_fails_closed_instead_of_guessing():
    with pytest.raises(PublicIdentityGap, match="initial_or_unproven_purchase_price:1"):
        purchase_prices_from_transfer_history(
            last_deadline_elements=[1],
            transfer_history=[],
        )


def test_pending_transfers_none_allows_only_valid_reconstruction():
    assert public_last_deadline_eligible(
        reconstruction_valid=True,
        pending_transfers="none",
    ) is True


def test_pending_transfers_present_is_hard_rejection():
    assert public_last_deadline_eligible(
        reconstruction_valid=True,
        pending_transfers="present",
    ) is False


def test_pending_transfer_attestation_is_fail_closed():
    with pytest.raises(ValueError):
        public_last_deadline_eligible(
            reconstruction_valid=True,
            pending_transfers="unknown",
        )
