from __future__ import annotations

from src.runtime_v6.delivery_integrity import MANDATORY_SECTIONS, PARTIAL_ALLOWED_SECTIONS
from src.runtime_v6.report_compute import build_report_compute_contract
from src.runtime_v6.report_qa import validate_post_render_qa, validate_pre_render_qa
from test_support.report_provenance import r5_partitions, r5_section_payloads
from test_support.report_rank20 import rank20_rows
from test_support.report_visible_body import valid_visible_body


def _our15():
    rows = []
    for player_id in (1, 2):
        rows.append({"element_id": player_id, "position": "GK"})
    for player_id in range(3, 8):
        rows.append({"element_id": player_id, "position": "DEF"})
    for player_id in range(8, 13):
        rows.append({"element_id": player_id, "position": "MID"})
    for player_id in range(13, 16):
        rows.append({"element_id": player_id, "position": "FWD"})
    return rows


def _watchlist20():
    rows = []
    start = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for offset in range(5):
            rows.append({"element_id": start + offset, "position": position})
        start += 10
    return rows


def _compute_contract():
    our15 = _our15()
    facts, models, inferences = r5_partitions(
        fact_key="official_price",
        model_key="price_rise_probability",
        fact_source="OFFICIAL_FPL",
        model_name="PRICE_PREDICTOR",
    )
    return build_report_compute_contract(
        scope_matrix_report_ready=True,
        our15_rows=our15,
        starting_xi_ids=[1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        bench_ids=[2, 7, 12, 15],
        watchlist_rows=_watchlist20(),
        rise_rows=rank20_rows(201, "RISE"),
        fall_rows=rank20_rows(301, "FALL"),
        section_payloads=r5_section_payloads(our15),
        facts=facts,
        models=models,
        inferences=inferences,
    )


def _section_manifest():
    return [
        {"section_id": section_id, "status": "COMPLETE"}
        for section_id in MANDATORY_SECTIONS
    ]


def _pre_render(**overrides):
    kwargs = {
        "compute_contract": _compute_contract(),
        "section_manifest": _section_manifest(),
        "mini_league_denominator_complete": True,
        "weather_required": True,
        "weather_direct_chat_present": True,
    }
    kwargs.update(overrides)
    return validate_pre_render_qa(**kwargs)


def _post_render(pre_render=None, **overrides):
    pre = pre_render or _pre_render()
    kwargs = {
        "pre_render_qa": pre,
        "rendered_body": valid_visible_body(pre),
        "rendered_section_ids": list(pre.get("expected_section_ids", MANDATORY_SECTIONS)),
        "rendered_section_states": {
            row["section_id"]: row["status"]
            for row in pre.get("section_manifest", [])
        },
        "rendered_compute_fingerprint": pre.get("compute_fingerprint"),
        "render_contract_token": pre.get("render_contract_token"),
        "rendered_counts": dict(pre.get("expected_counts", {})),
        "rendered_fact_keys": list(pre.get("expected_fact_keys", [])),
        "rendered_model_keys": list(pre.get("expected_model_keys", [])),
        "rendered_mini_league_denominator_complete": True,
        "rendered_weather_direct_chat_present": True,
        "truncated": False,
    }
    kwargs.update(overrides)
    return validate_post_render_qa(**kwargs)


def test_pre_render_pass_only_allows_render_and_never_delivery():
    result = _pre_render()

    assert result["status"] == "PASS"
    assert result["qa_stage"] == "PRE_RENDER"
    assert result["qa_passed"] is True
    assert result["render_allowed"] is True
    assert result["post_render_required"] is True
    assert result["delivery_ready"] is False
    assert result["report_state"] == "BUILDING"
    assert result["next_action"] == "RENDER_REPORT"
    assert result["legacy_fallback_allowed"] is False
    assert result["failures"] == []
    assert result["render_contract_token"]
    assert result["weather_required"] is True
    assert result["weather_direct_chat_present"] is True


def test_pre_render_rejects_compute_that_is_not_exact_wave5_handoff():
    compute = _compute_contract()
    compute["next_action"] = "DELIVER"
    compute["delivery_ready"] = True

    result = _pre_render(compute_contract=compute)

    assert result["status"] == "FAIL"
    assert result["qa_passed"] is False
    assert result["render_allowed"] is False
    assert result["delivery_ready"] is False
    assert result["report_state"] == "QA_FAILED"
    assert result["next_action"] == "RECOMPUTE"
    assert "COMPUTE_CONTRACT_NOT_READY" in result["failures"]


def test_pre_render_rejects_missing_mandatory_section():
    manifest = _section_manifest()[1:]

    result = _pre_render(section_manifest=manifest)

    assert result["status"] == "FAIL"
    assert result["missing_sections"] == [MANDATORY_SECTIONS[0]]
    assert result["render_allowed"] is False
    assert result["next_action"] == "PRE_RENDER_RECOVERY"


def test_pre_render_rejects_duplicate_section_identity():
    manifest = _section_manifest() + [
        {"section_id": MANDATORY_SECTIONS[0], "status": "COMPLETE"}
    ]

    result = _pre_render(section_manifest=manifest)

    assert result["status"] == "FAIL"
    assert result["duplicate_sections"] == [MANDATORY_SECTIONS[0]]
    assert result["render_allowed"] is False


def test_pre_render_rejects_invalid_section_state_even_when_fail_operational_states_are_allowed():
    manifest = _section_manifest()
    section_id = MANDATORY_SECTIONS[0]
    for row in manifest:
        if row["section_id"] == section_id:
            row["status"] = "NOT_RENDERED"

    result = _pre_render(section_manifest=manifest)

    assert result["status"] == "FAIL"
    assert any(section_id in item for item in result["invalid_section_states"])
    assert result["render_allowed"] is False


def test_pre_render_accepts_partial_only_for_explicit_partial_allowed_sections():
    manifest = _section_manifest()
    for row in manifest:
        if row["section_id"] in PARTIAL_ALLOWED_SECTIONS:
            row["status"] = "PARTIAL"

    result = _pre_render(section_manifest=manifest)

    assert result["status"] == "PASS"
    assert result["partial_sections"] == sorted(
        section_id for section_id in MANDATORY_SECTIONS
        if section_id in PARTIAL_ALLOWED_SECTIONS
    )
    assert result["render_allowed"] is True


def test_pre_render_rejects_incomplete_authoritative_mini_league_denominator():
    result = _pre_render(mini_league_denominator_complete=False)

    assert result["status"] == "FAIL"
    assert "MINI_LEAGUE_DENOMINATOR_INCOMPLETE" in result["failures"]
    assert result["render_allowed"] is False
    assert result["delivery_ready"] is False


def test_pre_render_accepts_explicit_degraded_s15b_when_icon_source_unavailable():
    manifest = _section_manifest()
    for row in manifest:
        if row["section_id"] == "S15B":
            row["status"] = "PARTIAL"

    result = _pre_render(
        section_manifest=manifest,
        mini_league_denominator_complete=False,
    )

    assert result["status"] == "PASS"
    assert result["mini_league_contract_state"] == "DEGRADED"
    assert "S15B" in result["partial_sections"]
    assert result["render_allowed"] is True


def test_post_render_accepts_visible_degraded_s15b_without_fabricated_denominator():
    manifest = _section_manifest()
    for row in manifest:
        if row["section_id"] == "S15B":
            row["status"] = "PARTIAL"
    pre = _pre_render(
        section_manifest=manifest,
        mini_league_denominator_complete=False,
    )

    result = _post_render(
        pre,
        rendered_body=valid_visible_body(pre),
        rendered_mini_league_denominator_complete=False,
    )

    assert result["status"] == "PASS"
    assert result["mini_league_contract_state"] == "DEGRADED"
    assert result["visible_mini_league_contract_state"] == "DEGRADED"
    assert result["visible_mini_league_denominator_complete"] is False


def test_post_render_rejects_s15b_missing_explicit_degraded_marker():
    manifest = _section_manifest()
    for row in manifest:
        if row["section_id"] == "S15B":
            row["status"] = "PARTIAL"
    pre = _pre_render(
        section_manifest=manifest,
        mini_league_denominator_complete=False,
    )
    body = valid_visible_body(pre).replace("MINI_LEAGUE SOURCE: DEGRADED", "ICON+ status unavailable")

    result = _post_render(
        pre,
        rendered_body=body,
        rendered_mini_league_denominator_complete=False,
    )

    assert result["status"] == "FAIL"
    assert "VISIBLE_MINI_LEAGUE_STATE_MISMATCH=MISSING!=DEGRADED" in result["failures"]


def test_post_render_pass_advances_only_to_wave7_delivery_proof():
    result = _post_render()

    assert result["status"] == "PASS"
    assert result["qa_stage"] == "POST_RENDER"
    assert result["qa_passed"] is True
    assert result["delivery_ready"] is False
    assert result["report_state"] == "BUILDING"
    assert result["next_action"] == "BUILD_DELIVERY_PROOF"
    assert result["legacy_fallback_allowed"] is False
    assert result["failures"] == []
    assert result["weather_direct_chat_present"] is True
    assert result["visible_body_validated"] is True


def test_post_render_rejects_truncation_even_when_required_sections_are_listed():
    result = _post_render(truncated=True)

    assert result["status"] == "FAIL"
    assert result["qa_passed"] is False
    assert result["report_state"] == "QA_FAILED"
    assert result["delivery_ready"] is False
    assert "RENDER_TRUNCATED" in result["failures"]


def test_post_render_rejects_missing_or_reordered_section_sequence():
    expected = list(MANDATORY_SECTIONS)
    rendered = expected[:-1]

    result = _post_render(rendered_section_ids=rendered)

    assert result["status"] == "FAIL"
    assert result["missing_sections"] == [expected[-1]]
    assert "SECTION_SEQUENCE_MISMATCH" in result["failures"]
    assert result["delivery_ready"] is False


def test_post_render_rejects_stale_compute_or_render_contract_token():
    stale_compute = "0" * 64
    stale_token = "1" * 64

    result = _post_render(
        rendered_compute_fingerprint=stale_compute,
        render_contract_token=stale_token,
    )

    assert result["status"] == "FAIL"
    assert "COMPUTE_FINGERPRINT_MISMATCH" in result["failures"]
    assert "RENDER_CONTRACT_TOKEN_MISMATCH" in result["failures"]
    assert result["delivery_ready"] is False


def test_post_render_rejects_cardinality_drift_after_successful_compute():
    pre = _pre_render()
    counts = dict(pre["expected_counts"])
    counts["WATCHLIST20"] = 19

    result = _post_render(pre, rendered_counts=counts)

    assert result["status"] == "FAIL"
    assert "COUNT_MISMATCH=WATCHLIST20:19!=20" in result["failures"]
    assert result["delivery_ready"] is False


def test_post_render_rejects_fact_model_bleed_or_namespace_drift():
    pre = _pre_render()
    fact_keys = list(pre["expected_fact_keys"])
    model_keys = list(pre["expected_model_keys"]) + [fact_keys[0]]

    result = _post_render(
        pre,
        rendered_fact_keys=fact_keys,
        rendered_model_keys=model_keys,
    )

    assert result["status"] == "FAIL"
    assert "FACT_MODEL_BLEED" in result["failures"]
    assert "MODEL_KEYS_MISMATCH" in result["failures"]
    assert result["delivery_ready"] is False


def test_post_render_rejects_section_status_drift_from_pre_render_contract():
    pre = _pre_render()
    section_states = {
        row["section_id"]: row["status"]
        for row in pre["section_manifest"]
    }
    section_id = MANDATORY_SECTIONS[0]
    section_states[section_id] = "PARTIAL"

    result = _post_render(pre, rendered_section_states=section_states)

    assert result["status"] == "FAIL"
    assert f"SECTION_STATUS_MISMATCH={section_id}:PARTIAL!=COMPLETE" in result["failures"]
    assert result["delivery_ready"] is False


def test_post_render_rejects_tampered_pre_render_contract_payload():
    pre = _pre_render()
    pre["expected_counts"] = dict(pre["expected_counts"])
    pre["expected_counts"]["WATCHLIST20"] = 19

    result = _post_render(pre, rendered_counts=dict(pre["expected_counts"]))

    assert result["status"] == "FAIL"
    assert "PRE_RENDER_CONTRACT_TOKEN_INVALID" in result["failures"]
    assert result["delivery_ready"] is False


def test_post_render_cannot_bypass_failed_pre_render_gate():
    failed_pre = _pre_render(section_manifest=_section_manifest()[1:])

    result = _post_render(failed_pre)

    assert result["status"] == "BLOCKED"
    assert result["qa_passed"] is False
    assert result["delivery_ready"] is False
    assert result["report_state"] == "QA_FAILED"
    assert result["next_action"] == "PRE_RENDER_QA"
    assert result["failures"] == ["PRE_RENDER_QA_NOT_PASSED"]
