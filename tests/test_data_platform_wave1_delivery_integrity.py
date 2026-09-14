from __future__ import annotations

import pytest

from src.runtime_v6.delivery_integrity import (
    DeliveryIntegrityError,
    assess_artifact_matrix,
    assess_report_timing,
    direct_fresh_allowed,
    post_render_gate,
    pre_delivery_gate,
    retrieval_decision,
    validate_final_unavailable_reason,
    validate_rank20,
    validate_watchlist20,
)


def _players(position: str, start: int, count: int = 5):
    return [
        {"element_id": player_id, "position": position}
        for player_id in range(start, start + count)
    ]


def _watchlist20():
    return (
        _players("GK", 101)
        + _players("DEF", 201)
        + _players("MID", 301)
        + _players("FWD", 401)
    )


def _rank20(start: int):
    return [{"element_id": player_id} for player_id in range(start, start + 20)]


def _section_statuses():
    statuses = {f"S{index:02d}": "PASS" for index in range(1, 19)}
    statuses["S14B"] = "PASS"
    return statuses


def test_healthy_v6_truncated_read_recovers_from_same_v6_and_forbids_direct_fresh():
    decision = retrieval_decision(
        v6_scope_state="CURRENT",
        retrieval_state="CONNECTOR_TRUNCATED",
    )
    assert decision["action"] == "SAME_V6_RETRIEVAL_RECOVERY"
    assert decision["direct_fresh_allowed"] is False
    assert decision["final_unavailable_allowed"] is False
    assert direct_fresh_allowed(
        v6_scope_state="CURRENT",
        retrieval_state="PAGINATION_REQUIRED",
    ) is False


@pytest.mark.parametrize(
    "condition",
    [
        "CONNECTOR_TRUNCATED",
        "PAYLOAD_TOO_LARGE",
        "FIRST_READ_PARTIAL",
        "PAGINATION_REQUIRED",
        "PARTIAL_CHUNK",
        "RENDERING_LIMIT",
    ],
)
def test_retrieval_conditions_are_never_final_unavailable_reasons(condition):
    with pytest.raises(DeliveryIntegrityError):
        validate_final_unavailable_reason(condition)


def test_real_v6_scope_failure_allows_scoped_direct_fresh():
    decision = retrieval_decision(
        v6_scope_state="V6_SCOPE_FAILED",
        retrieval_state="COMPLETE",
    )
    assert decision["action"] == "SCOPED_DIRECT_FRESH_ALLOWED"
    assert decision["direct_fresh_allowed"] is True
    assert validate_final_unavailable_reason("V6_SCOPE_FAILED") == "V6_SCOPE_FAILED"


def test_post_slot_generation_is_not_source_staleness_and_lateness_is_separate():
    timing = assess_report_timing(
        logical_slot="2026-09-14T12:30:00+07:00",
        report_generated_at="2026-09-14T12:31:00+07:00",
        delivered_at="2026-09-14T12:31:30+07:00",
    )
    assert timing["report_timeliness"] == "LATE"
    assert timing["report_lateness_seconds"] == 60.0
    assert timing["delivery_lateness_seconds"] == 30.0

    matrix = assess_artifact_matrix(
        {
            "bootstrap": {
                "source_generated_at": "2026-09-14T12:30:45+07:00",
                "maximum_age_minutes": 90,
            },
            "fixtures": {
                "source_generated_at": "2026-09-14T10:00:00+07:00",
                "maximum_age_minutes": 60,
            },
            "submitted_picks": {
                "source_generated_at": "2026-09-12T19:30:00+07:00",
                "maximum_age_minutes": 60,
                "immutable_gw_cache": True,
            },
        },
        observed_at="2026-09-14T12:31:00+07:00",
    )
    assert matrix["bootstrap"]["source_freshness"] == "CURRENT"
    assert matrix["fixtures"]["source_freshness"] == "STALE"
    assert matrix["submitted_picks"]["source_freshness"] == "IMMUTABLE_GW_CACHE_REUSED"


def test_immutable_cache_marker_is_restricted_to_submitted_picks():
    with pytest.raises(DeliveryIntegrityError):
        assess_artifact_matrix(
            {
                "live": {
                    "source_generated_at": "2026-09-14T12:00:00+07:00",
                    "maximum_age_minutes": 30,
                    "immutable_gw_cache": True,
                }
            },
            observed_at="2026-09-14T12:31:00+07:00",
        )


def test_watchlist20_requires_exact_20_position_split_nonowned_and_current_universe():
    rows = _watchlist20()
    universe = {row["element_id"] for row in rows} | {999}
    result = validate_watchlist20(rows, owned_ids={1, 2, 3}, universe_ids=universe)
    assert result["status"] == "PASS"
    assert result["positions"] == {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}
    assert result["owned_overlap"] == 0

    broken = validate_watchlist20(rows[:16], owned_ids=(), universe_ids=universe)
    assert broken["status"] == "FAIL"
    assert broken["reason"] == "RETRIEVAL/COMPUTE_DEFECT"
    assert broken["total"] == 16


def test_watchlist_owned_overlap_is_delivery_defect():
    rows = _watchlist20()
    result = validate_watchlist20(rows, owned_ids={101})
    assert result["status"] == "FAIL"
    assert result["owned_overlap"] == 1


def test_rise20_and_fall20_are_exact_cardinality_gates():
    assert validate_rank20(_rank20(1000), label="RISE20")["status"] == "PASS"
    assert validate_rank20(_rank20(2000), label="FALL20")["status"] == "PASS"
    broken = validate_rank20(_rank20(1000)[:8], label="RISE20")
    assert broken["status"] == "FAIL"
    assert broken["reason"] == "RETRIEVAL/COMPUTE_DEFECT"


def test_pre_delivery_matrix_blocks_missing_or_short_mandatory_sections():
    good = pre_delivery_gate(
        _section_statuses(),
        watchlist_rows=_watchlist20(),
        rise_rows=_rank20(1000),
        fall_rows=_rank20(2000),
        owned_ids={1, 2, 3},
        universe_ids={row["element_id"] for row in _watchlist20()},
    )
    assert good["status"] == "PASS"
    assert good["report_ready"] is True

    bad = pre_delivery_gate(
        _section_statuses(),
        watchlist_rows=_watchlist20()[:16],
        rise_rows=_rank20(1000)[:8],
        fall_rows=_rank20(2000),
    )
    assert bad["status"] == "FAIL"
    assert bad["report_ready"] is False
    assert any(item.startswith("S10_") for item in bad["failures"])
    assert any(item.startswith("S11_") for item in bad["failures"])


def test_reasoned_partial_is_only_allowed_for_declared_sections():
    statuses = _section_statuses()
    statuses["S13"] = "PARTIAL | optimizer input unavailable"
    assert pre_delivery_gate(
        statuses,
        watchlist_rows=_watchlist20(),
        rise_rows=_rank20(1000),
        fall_rows=_rank20(2000),
    )["status"] == "PASS"

    statuses["S09"] = "PARTIAL | price radar incomplete"
    assert pre_delivery_gate(
        statuses,
        watchlist_rows=_watchlist20(),
        rise_rows=_rank20(1000),
        fall_rows=_rank20(2000),
    )["status"] == "FAIL"


def test_post_render_gate_requires_exact_visible_cardinality_and_rerenders_on_truncation():
    good = post_render_gate(
        watchlist_rendered_rows=20,
        watchlist_position_counts={"GK": 5, "DEF": 5, "MID": 5, "FWD": 5},
        rise_rendered_rows=20,
        fall_rendered_rows=20,
        mandatory_sections_missing=0,
    )
    assert good == {"status": "PASS", "action": "DELIVER", "failures": []}

    truncated = post_render_gate(
        watchlist_rendered_rows=12,
        watchlist_position_counts={"GK": 3, "DEF": 3, "MID": 3, "FWD": 3},
        rise_rendered_rows=20,
        fall_rendered_rows=20,
        mandatory_sections_missing=0,
    )
    assert truncated["status"] == "FAIL"
    assert truncated["action"] == "RENDER_AGAIN"
