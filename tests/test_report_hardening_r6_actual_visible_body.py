from __future__ import annotations

from src.runtime_v6.delivery_integrity import MANDATORY_SECTIONS
from src.runtime_v6.report_qa import validate_post_render_qa, validate_pre_render_qa
from test_support.report_visible_body import valid_visible_body


def _compute_contract() -> dict:
    return {
        "status": "PASS",
        "compute_ready": True,
        "delivery_ready": False,
        "next_action": "PRE_RENDER_QA",
        "legacy_fallback_allowed": False,
        "compute_fingerprint": "a" * 64,
        "OUR15": {"status": "PASS", "total": 15},
        "XI": {"status": "PASS", "total": 11},
        "BENCH": {"status": "PASS", "total": 4},
        "WATCHLIST20": {"status": "PASS", "total": 20},
        "RISE20": {"status": "PASS", "total": 20},
        "FALL20": {"status": "PASS", "total": 20},
        "FACT_MODEL": {
            "status": "PASS",
            "overlap": [],
            "fact_keys": ["official_price"],
            "model_keys": ["price_projection"],
            "inference_keys": ["transfer_call"],
        },
    }


def _pre_render() -> dict:
    return validate_pre_render_qa(
        compute_contract=_compute_contract(),
        section_manifest=[
            {"section_id": section_id, "status": "COMPLETE"}
            for section_id in MANDATORY_SECTIONS
        ],
        mini_league_denominator_complete=True,
        weather_required=True,
        weather_direct_chat_present=True,
    )


def _body(**overrides) -> str:
    return valid_visible_body(_pre_render(), **overrides)


def _post(body: str, **overrides) -> dict:
    pre = _pre_render()
    kwargs = {
        "pre_render_qa": pre,
        "rendered_body": body,
        "rendered_section_ids": list(pre["expected_section_ids"]),
        "rendered_section_states": {
            row["section_id"]: row["status"] for row in pre["section_manifest"]
        },
        "rendered_compute_fingerprint": pre["compute_fingerprint"],
        "render_contract_token": pre["render_contract_token"],
        "rendered_counts": dict(pre["expected_counts"]),
        "rendered_fact_keys": list(pre["expected_fact_keys"]),
        "rendered_model_keys": list(pre["expected_model_keys"]),
        "rendered_mini_league_denominator_complete": True,
        "rendered_weather_direct_chat_present": True,
        "truncated": False,
    }
    kwargs.update(overrides)
    return validate_post_render_qa(**kwargs)


def test_valid_canonical_visible_body_passes_r6_and_only_advances_to_delivery_proof():
    result = _post(_body())

    assert result["status"] == "PASS"
    assert result["qa_passed"] is True
    assert result["delivery_ready"] is False
    assert result["next_action"] == "BUILD_DELIVERY_PROOF"
    assert result["visible_body_validated"] is True


def test_metadata_cannot_false_pass_a_progress_only_visible_body():
    result = _post("# 04:30 MORNING DEEP REVIEW\nGenerating report...\n")

    assert result["status"] == "FAIL"
    assert result["qa_passed"] is False
    assert "VISIBLE_BODY_PROGRESS_PLACEHOLDER" in result["failures"]
    assert any(item.startswith("VISIBLE_SECTIONS_MISSING=") for item in result["failures"])


def test_visible_body_missing_14b_fails_even_when_metadata_claims_complete():
    result = _post(_body(include_14b=False))

    assert result["status"] == "FAIL"
    assert "VISIBLE_SECTIONS_MISSING=S14B" in result["failures"]


def test_visible_rise20_must_really_have_twenty_rows():
    result = _post(_body(rise_count=19))

    assert result["status"] == "FAIL"
    assert "VISIBLE_COUNT_MISMATCH=RISE20:19!=20" in result["failures"]


def test_visible_rise20_count_cannot_hide_missing_j1_schema_field():
    result = _post(_body(omit_rise_field="eta_human"))

    assert result["status"] == "FAIL"
    assert "VISIBLE_RANK20_SCHEMA_MISSING=RISE20:eta_human" in result["failures"]


def test_visible_rise20_reuses_r2_identity_semantics():
    body = _body().replace("| 2 | 202 | RISE02 |", "| 2 | 201 | RISE02 |", 1)
    result = _post(body)

    assert result["status"] == "FAIL"
    assert "VISIBLE_RANK20_SEMANTIC_INVALID=RISE20:IDENTITY_DUPLICATE" in result["failures"]


def test_visible_rise20_reuses_r2_ownership_semantics():
    body = _body().replace("| 1 | 201 | RISE01 | 7.0 | 12.3 | NON_OWNED | RISE |", "| 1 | 201 | RISE01 | 7.0 | 12.3 | BROKEN | RISE |", 1)
    result = _post(body)

    assert result["status"] == "FAIL"
    assert "VISIBLE_RANK20_SEMANTIC_INVALID=RISE20:ROW_OWNERSHIP_TAG_INVALID=1:BROKEN" in result["failures"]


def test_visible_rise20_reuses_r2_timestamp_semantics():
    body = _body().replace(
        "| 1 | MEDIUM | V6_PRICE_MODEL | 2026-09-17T04:30:00+07:00 |",
        "| 1 | MEDIUM | V6_PRICE_MODEL | not-a-time |",
        1,
    )
    result = _post(body)

    assert result["status"] == "FAIL"
    assert "VISIBLE_RANK20_SEMANTIC_INVALID=RISE20:ROW_OBSERVED_AT_INVALID=1" in result["failures"]


def test_visible_fact_model_inference_partition_cannot_drop_inference():
    result = _post(_body(include_inference=False))

    assert result["status"] == "FAIL"
    assert "VISIBLE_INFERENCE_KEYS_MISMATCH" in result["failures"]


def test_visible_body_truncation_marker_fails_even_when_truncated_flag_is_false():
    result = _post(_body() + "[TRUNCATED]\n")

    assert result["status"] == "FAIL"
    assert "VISIBLE_BODY_TRUNCATION_MARKER" in result["failures"]
