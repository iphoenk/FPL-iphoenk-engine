from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.engines.official_fact_completeness import (
    FALLBACK_BANNER,
    build_public_official_fact_integrity,
    require_complete_user_report,
)
from src.engines.official_fact_publication_gate import _apply_fact
from src.engines.official_snapshot_service import _fallback_snapshot


def _snapshot() -> dict:
    elements = []
    for element in range(1, 36):
        if element <= 15:
            element_type = ((element - 1) % 4) + 1
        else:
            element_type = ((element - 16) // 5) + 1
        elements.append({
            "id": element,
            "web_name": f"P{element}",
            "team": ((element - 1) % 5) + 1,
            "element_type": element_type,
            "now_cost": 40 + element,
            "selected_by_percent": f"{element / 10:.1f}",
            "status": "a",
            "news": "",
        })
    fetched = "2026-08-31T05:30:00+00:00"
    return {
        "schema_version": 2,
        "generated_at": fetched,
        "bootstrap": {
            "teams": [{"id": i, "name": f"Team {i}"} for i in range(1, 6)],
            "elements": elements,
        },
        "endpoint_health": {"bootstrap": {"status": "LIVE", "fetched_at": fetched}},
        "official_freshness": {
            "state": "FRESH",
            "fallback": False,
            "snapshot_id": f"bootstrap-static@{fetched}",
            "last_verified_at": fetched,
            "age_seconds": 0,
            "confidence": "HIGH",
        },
    }


def _watchlist() -> dict:
    return {
        "GK": [{"element": i, "position": "GK"} for i in range(16, 21)],
        "DEF": [{"element": i, "position": "DEF"} for i in range(21, 26)],
        "MID": [{"element": i, "position": "MID"} for i in range(26, 31)],
        "FWD": [{"element": i, "position": "FWD"} for i in range(31, 36)],
    }


def _integrity(snapshot=None, owned=None, watchlist=None, auth=None):
    return build_public_official_fact_integrity(
        snapshot or _snapshot(),
        owned or list(range(1, 16)),
        watchlist or _watchlist(),
        personal_auth=auth,
    )


def _codes(integrity: dict) -> list[str]:
    return [row["code"] for row in (integrity.get("publication_integrity") or {}).get("reasons") or []]


def test_15_15_owned_and_20_20_watchlist_happy_path_is_publishable():
    integrity = _integrity()
    assert integrity["owned"]["resolved"] == 15
    assert integrity["owned"]["official_fact_complete"] == 15
    assert integrity["watchlist"]["resolved"] == 20
    assert integrity["watchlist"]["official_fact_complete"] == 20
    assert integrity["watchlist"]["position_counts"] == {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}
    assert integrity["publication_integrity"]["status"] == "PASS"
    assert integrity["publication_integrity"]["complete_user_report_allowed"] is True
    require_complete_user_report(integrity)


def test_public_success_and_personal_auth_failure_keeps_public_facts_fresh():
    integrity = _integrity(auth={"status": "FAILED", "error": "401"})
    assert integrity["publication_integrity"]["status"] == "PASS"
    assert integrity["health"]["Personal authenticated pull"] == "FAILED"
    assert integrity["health"]["Official public pull"] == "PASS"
    assert all(row["current_price"] is not None for row in integrity["owned"]["rows"])
    assert all(row["current_ownership_pct"] is not None for row in integrity["owned"]["rows"])
    assert all(row["official_fact_provenance"]["freshness_state"] == "FRESH" for row in integrity["owned"]["rows"])


def test_one_owned_row_unresolved_blocks_publication():
    snapshot = _snapshot()
    snapshot["bootstrap"]["elements"] = [row for row in snapshot["bootstrap"]["elements"] if row["id"] != 15]
    integrity = _integrity(snapshot=snapshot)
    assert integrity["owned"]["resolved"] == 14
    assert "ELEMENT_ID_UNRESOLVED" in _codes(integrity)
    with pytest.raises(RuntimeError, match="USER_REPORT BLOCKED"):
        require_complete_user_report(integrity)


def test_resolved_element_missing_price_is_data_join_defect_not_unavailable_this_pull():
    snapshot = _snapshot()
    next(row for row in snapshot["bootstrap"]["elements"] if row["id"] == 1)["now_cost"] = None
    integrity = _integrity(snapshot=snapshot)
    defects = [row for row in integrity["publication_integrity"]["reasons"] if row.get("element_id") == 1]
    assert any(row["code"] == "DATA_JOIN_DEFECT" and "current_price" in row["missing_fields"] for row in defects)
    assert "UNAVAILABLE_THIS_PULL" not in str(integrity)
    assert integrity["publication_integrity"]["status"] == "BLOCKED"


def test_resolved_element_missing_ownership_is_data_join_defect():
    snapshot = _snapshot()
    next(row for row in snapshot["bootstrap"]["elements"] if row["id"] == 16)["selected_by_percent"] = None
    integrity = _integrity(snapshot=snapshot)
    defects = [row for row in integrity["publication_integrity"]["reasons"] if row.get("element_id") == 16]
    assert any(row["code"] == "DATA_JOIN_DEFECT" and "current_ownership_pct" in row["missing_fields"] for row in defects)
    assert integrity["watchlist"]["official_fact_complete"] == 19


def test_watchlist_owned_overlap_blocks_publication():
    watchlist = _watchlist()
    watchlist["GK"][0] = {"element": 1, "position": "GK"}
    integrity = _integrity(watchlist=watchlist)
    assert "OWNED_PLAYER_IN_WATCHLIST" in _codes(integrity)
    assert integrity["publication_integrity"]["status"] == "BLOCKED"


def test_watchlist_positional_count_must_be_exactly_5_5_5_5():
    watchlist = _watchlist()
    watchlist["DEF"] = watchlist["DEF"][:-1]
    integrity = _integrity(watchlist=watchlist)
    assert "WATCHLIST_POSITION_COUNT_INVALID" in _codes(integrity)
    assert integrity["watchlist"]["position_counts"]["DEF"] == 4
    assert integrity["publication_integrity"]["status"] == "BLOCKED"


def test_renderer_attempt_with_14_15_fails_closed():
    integrity = _integrity(owned=list(range(1, 15)))
    assert integrity["owned"]["official_fact_complete"] == 14
    with pytest.raises(RuntimeError, match="OWNED_COUNT_INVALID"):
        require_complete_user_report(integrity)


def test_renderer_attempt_with_19_20_fails_closed():
    watchlist = _watchlist()
    watchlist["FWD"] = watchlist["FWD"][:-1]
    integrity = _integrity(watchlist=watchlist)
    assert integrity["watchlist"]["official_fact_complete"] == 19
    with pytest.raises(RuntimeError, match="WATCHLIST"):
        require_complete_user_report(integrity)


def test_same_snapshot_provenance_is_used_for_all_35_public_fact_rows():
    integrity = _integrity()
    rows = integrity["owned"]["rows"] + integrity["watchlist"]["rows"]
    snapshot_ids = {row["official_fact_provenance"]["snapshot_id"] for row in rows}
    assert snapshot_ids == {integrity["official_snapshot"]["snapshot_id"]}
    assert len(rows) == 35


def test_publication_fact_overlay_overwrites_stale_fact_but_preserves_model_fields():
    integrity = _integrity()
    fact = integrity["owned"]["rows"][0]
    source = {
        "element": 1,
        "price": 1.0,
        "ownership_pct": "99.9",
        "status": "u",
        "xpts_gw": 8.25,
        "selection_score": 7.7,
        "lineup_status": "START",
    }
    patched = _apply_fact(source, {1: fact})
    assert patched["price"] == fact["current_price"]
    assert patched["ownership_pct"] == fact["current_ownership_pct"]
    assert patched["status"] == fact["status"]
    assert patched["xpts_gw"] == 8.25
    assert patched["selection_score"] == 7.7
    assert patched["lineup_status"] == "START"
    assert patched["fact_authority"] == "PUBLIC_OFFICIAL_FACT"


def test_verified_fallback_keeps_exact_banner_never_claims_fresh_and_degrades_publication():
    previous = _snapshot()
    previous["generated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    previous["official_freshness"]["last_verified_at"] = previous["generated_at"]
    failed = {
        "status": "FAILED",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "error": "Timeout",
    }
    fallback = _fallback_snapshot(previous, failed)
    assert fallback is not None
    freshness = fallback["official_freshness"]
    assert freshness["state"] == "FALLBACK"
    assert freshness["banner"] == FALLBACK_BANNER
    assert freshness["confidence"] == "DOWNGRADED"
    assert freshness["age_seconds"] >= 0
    integrity = _integrity(snapshot=fallback)
    assert integrity["official_snapshot"]["freshness_state"] == "FALLBACK"
    assert integrity["official_snapshot"]["fresh_pull_succeeded"] is False
    assert integrity["official_snapshot"]["verified_fallback"] is True
    assert integrity["publication_integrity"]["status"] == "DEGRADED"
    assert integrity["publication_integrity"]["complete_user_report_allowed"] is True
    assert integrity["health"]["Official public pull"] == "DEGRADED"
    assert integrity["health"]["Reporting"] == "DEGRADED"
    assert integrity["health"]["Serving"] == "DEGRADED"
    require_complete_user_report(integrity)


def test_complete_but_untrusted_snapshot_cannot_publish():
    snapshot = _snapshot()
    snapshot["endpoint_health"]["bootstrap"]["status"] = "FAILED"
    snapshot.pop("official_freshness", None)
    integrity = _integrity(snapshot=snapshot)
    assert integrity["owned"]["official_fact_complete"] == 15
    assert integrity["watchlist"]["official_fact_complete"] == 20
    assert "OFFICIAL_SOURCE_UNAVAILABLE" in _codes(integrity)
    assert integrity["publication_integrity"]["status"] == "BLOCKED"
    with pytest.raises(RuntimeError, match="OFFICIAL_SOURCE_UNAVAILABLE"):
        require_complete_user_report(integrity)


def test_unverified_previous_snapshot_is_not_accepted_as_fallback():
    previous = _snapshot()
    previous["endpoint_health"]["bootstrap"]["status"] = "FAILED"
    previous.pop("official_freshness", None)
    assert _fallback_snapshot(previous, {"status": "FAILED"}) is None
