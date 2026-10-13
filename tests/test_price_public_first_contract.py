from __future__ import annotations

from src.engines.v12_price_delivery import (
    PRICE_SECTION_IDS,
    _public_first_personal_projection,
    classify_price_personal_mode,
)
from src.runtime_v6.domains.report_plane.prefetch_contract import (
    PRICE_REPORT,
    PREFETCH_PUBLIC_FIRST,
    classify_prefetch_state,
    price_source_domains,
)


def test_price_prefetch_declares_public_domains_without_personal_request():
    domains = price_source_domains(
        report_kind=PRICE_REPORT,
        official_status="AVAILABLE",
        league_status="AVAILABLE",
        personal_requested=False,
        personal_auth_state="NOT_REQUESTED",
    )

    assert domains == {
        "PUBLIC_OFFICIAL": {"status": "AVAILABLE"},
        "PUBLIC_LEAGUE": {"status": "AVAILABLE"},
        "PRIVATE_PERSONAL": {
            "status": "NOT_REQUESTED",
            "auth_state": "NOT_REQUESTED",
            "finance_authority": "UNAVAILABLE",
        },
    }


def test_stale_or_missing_auth_cannot_authorize_finance():
    result = classify_price_personal_mode(
        public_official_available=True,
        public_league_available=True,
        personal_resolution={
            "resolution_status": "PREVIOUS_GW_IDENTITY_FALLBACK",
            "stale": True,
            "finance_allowed": False,
            "source_class": "AUTHENTICATED_CURRENT_TEAM",
        },
    )

    assert result["mode"] == "PUBLIC_FIRST_DEGRADED"
    assert result["finance_status"] == "UNAVAILABLE"
    assert result["executable_transfer_economics"] is False
    assert "STALE_PERSONAL_EVIDENCE" in result["degradation_reasons"]


def test_price_public_first_degraded_is_complete_but_non_executable():
    result = classify_price_personal_mode(
        public_official_available=True,
        public_league_available=True,
        personal_resolution={
            "resolution_status": "UNAVAILABLE",
            "stale": True,
            "finance_allowed": False,
            "source_class": None,
        },
    )

    assert result["mode"] == "PUBLIC_FIRST_DEGRADED"
    assert result["section_ids"] == list(PRICE_SECTION_IDS)
    assert result["public_facts_usable"] is True
    assert result["bank"] == "UNAVAILABLE"
    assert result["free_transfers"] == "UNAVAILABLE"
    assert result["purchase_price"] == "UNAVAILABLE"
    assert result["selling_price"] == "UNAVAILABLE"


def test_degraded_projection_keeps_last_known_roster_historical_only():
    result = _public_first_personal_projection(
        {
            "state": "STALE",
            "supportable": True,
            "source_class": "LAST_GOOD_CURRENT15",
            "gw": 6,
            "observed_at": "2026-10-13T23:08:46+00:00",
            "rows": [{"element_id": 1, "purchase_price": 50, "selling_price": 51}],
        },
        execution_mode="PUBLIC_FIRST_DEGRADED",
    )

    assert result["rows"] == []
    assert result["element_ids"] == []
    assert result["supportable"] is False
    assert result["historical_rows"][0]["element_id"] == 1
    assert result["historical_gw"] == 6
    assert result["finance_status"] == "UNAVAILABLE"
    assert result["personal_data_fabricated"] is False


def test_public_integrity_failure_is_fail_closed():
    result = classify_price_personal_mode(
        public_official_available=False,
        public_league_available=True,
        personal_resolution={
            "resolution_status": "CURRENT_VALID",
            "stale": False,
            "finance_allowed": True,
            "source_class": "AUTHENTICATED_CURRENT_TEAM",
        },
    )

    assert result["mode"] == "FAILED"
    assert result["public_facts_usable"] is False
    assert "PUBLIC_OFFICIAL_UNAVAILABLE" in result["degradation_reasons"]


def test_prefetch_state_distinguishes_public_first_from_failed():
    assert classify_prefetch_state(
        {
            "report_kind": PRICE_REPORT,
            "public_core_complete": True,
            "complete": False,
            "source_domains": {"PRIVATE_PERSONAL": {"status": "NOT_REQUESTED"}},
        }
    ) == PREFETCH_PUBLIC_FIRST

    assert classify_prefetch_state(
        {
            "report_kind": PRICE_REPORT,
            "public_core_complete": False,
            "complete": False,
            "source_domains": {"PRIVATE_PERSONAL": {"status": "AVAILABLE"}},
        }
    ) == "PREFETCH_FAILED"

