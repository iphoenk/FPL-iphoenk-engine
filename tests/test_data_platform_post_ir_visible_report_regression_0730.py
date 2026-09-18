from __future__ import annotations

from src.runtime_v6.domains.report_plane.delivery_integrity import MANDATORY_SECTIONS
from src.runtime_v6.domains.report_plane.report_contract import (
    classify_report_outcome,
    report_delivery_status,
    safety_net_decision,
)
from src.runtime_v6.domains.report_plane.visible_body_contract import (
    validate_visible_report_body,
)


LOGICAL_SLOT = "2026-09-18T07:30:00+07:00"


def _thin_0730_body() -> str:
    # Golden regression *class*, not a verbatim transcript. The user-visible
    # 07:30 message was delivered but did not satisfy the canonical visible
    # Deadline/Full catalog. Keep this fixture intentionally thin so the
    # existing visible-body validator proves the body itself is rejectable.
    return """# FPL Deadline Update — 07:30 WIB
CORE TRANSPORT: PASS
ACQUISITION: PASS
PUBLISH INTEGRITY: PASS
V6: GREEN

Data terbaru sudah ditarik. Kondisi tim relatif stabil.
Fokus saat ini adalah menunggu kabar terakhir menjelang deadline.
"""


def test_0730_thin_body_is_rejected_by_existing_visible_body_validator():
    result = validate_visible_report_body(
        rendered_body=_thin_0730_body(),
        expected_section_ids=MANDATORY_SECTIONS,
        expected_counts={
            "OUR15": 15,
            "XI": 11,
            "BENCH": 4,
            "WATCHLIST20": 20,
            "RISE20": 20,
            "FALL20": 20,
        },
        expected_fact_keys=("official_fpl",),
        expected_model_keys=("xpts",),
        expected_inference_keys=("decision",),
        expected_weather_state="DIRECT_CHATGPT",
        mini_league_denominator_complete_required=True,
    )

    assert result["status"] == "FAIL"
    assert any(item.startswith("VISIBLE_SECTIONS_MISSING=") for item in result["failures"])
    assert "VISIBLE_COUNT_MISMATCH=OUR15:0!=15" in result["failures"]
    assert "VISIBLE_COUNT_MISMATCH=RISE20:0!=20" in result["failures"]
    assert "VISIBLE_COUNT_MISMATCH=FALL20:0!=20" in result["failures"]


def test_0730_source_fallback_must_not_be_report_delivery_pass_without_contract_proof():
    # Regression classification:
    # raw/message delivery may happen, but REPORT_SLOT_FULFILLED must remain
    # false until the canonical visible contract passes. Source availability
    # alone therefore cannot yield a report-delivery PASS.
    status = report_delivery_status(
        due=True,
        fresh_v6_available=False,
        direct_fresh_available=False,
        last_good_nonvolatile_available=False,
    )

    assert not status.startswith("PASS"), (
        "07:30 regression: source fallback is being conflated with canonical "
        "report delivery/fulfillment"
    )


def test_0730_raw_delivery_or_prefetch_cannot_suppress_same_slot_recovery():
    # The outer recovery decision currently receives only coarse booleans.
    # For the 07:30 regression, a user-visible message existed but the canonical
    # report contract did not. Until valid report-slot fulfillment proof exists,
    # raw delivery/prefetch/ownership must not suppress recovery.
    decision = safety_net_decision(
        logical_slot=LOGICAL_SLOT,
        primary_owned=True,
        prefetched=True,
        delivered=True,
    )

    assert decision["action"] == "RECOVER"
    assert decision["deduplicated"] is False
    assert "REPORT_CONTRACT" in decision["reason"] or "UNFULFILLED" in decision["reason"]


def test_0730_expected_three_state_classification_is_explicit():
    outcome = classify_report_outcome(
        data_slot_fulfilled=True,
        report_contract_pass=False,
        visible_emitted=True,
        delivery_proof_valid=False,
    )

    assert outcome["DATA_SLOT_FULFILLED"] is True
    assert outcome["REPORT_DELIVERED"] is True
    assert outcome["REPORT_SLOT_FULFILLED"] is False
    assert outcome["REPORT_CONTRACT_PASS"] is False
