from __future__ import annotations

from copy import deepcopy

import pytest

from src.runtime_v6.delivery_integrity import (
    DEEP_MANDATORY_SECTIONS,
    FINAL_MANDATORY_SECTIONS,
    MATCH_MANDATORY_SECTIONS,
    POST_ALL_MATCH_MANDATORY_SECTIONS,
    plan_exact_scope_retrieval,
)
from src.runtime_v6.report_compute import build_report_compute_contract
from src.runtime_v6.report_contract import resolve_report_scope_matrix
from src.runtime_v6.report_qa import validate_post_render_qa, validate_pre_render_qa
from src.runtime_v6.report_trigger import build_ad_hoc_report_context
from test_support.report_provenance import r5_partitions, r5_section_payloads
from test_support.report_rank20 import rank20_rows
from test_support.report_visible_body import valid_match_visible_body, valid_visible_body


TAHAP3_SCENARIOS = (
    "V6_GREEN_COMPLETE",
    "V6_GREEN_CONNECTOR_TRUNCATION",
    "V6_AMBER_RECOVERABLE",
    "MANDATORY_SOURCE_UNAVAILABLE",
    "ICON_UNAVAILABLE",
    "WEATHER_UNAVAILABLE",
    "OPTIMIZER_MC_FAILURE",
    "NORMAL_DEEP",
    "DEADLINE_ACTIVE_HOURLY",
    "FINAL_DEADLINE",
    "LIVE_MATCH_CHECKPOINT",
    "POST_ALL_MATCH",
)


def _our15() -> list[dict]:
    return [
        *({"id": i, "position": "GK"} for i in range(1, 3)),
        *({"id": i, "position": "DEF"} for i in range(3, 8)),
        *({"id": i, "position": "MID"} for i in range(8, 13)),
        *({"id": i, "position": "FWD"} for i in range(13, 16)),
    ]


def _watchlist20() -> list[dict]:
    rows: list[dict] = []
    next_id = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for _ in range(5):
            rows.append({"id": next_id, "position": position})
            next_id += 1
    return rows


def _compute(*, mutate_sections=None) -> dict:
    our15 = _our15()
    sections = r5_section_payloads(our15)
    if mutate_sections:
        mutate_sections(sections)
    facts, models, inferences = r5_partitions()
    return build_report_compute_contract(
        scope_matrix_report_ready=True,
        our15_rows=our15,
        starting_xi_ids=[1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        bench_ids=[2, 7, 12, 15],
        watchlist_rows=_watchlist20(),
        rise_rows=rank20_rows(201, "RISE"),
        fall_rows=rank20_rows(301, "FALL"),
        section_payloads=sections,
        facts=facts,
        models=models,
        inferences=inferences,
    )


def _catalog(mode: str):
    token = str(mode).upper()
    if token == "MATCH":
        return MATCH_MANDATORY_SECTIONS
    if token == "POST_ALL_MATCH":
        return POST_ALL_MATCH_MANDATORY_SECTIONS
    if token == "FINAL":
        return FINAL_MANDATORY_SECTIONS
    return DEEP_MANDATORY_SECTIONS


def _full_manifest(*, s15b_status: str = "COMPLETE") -> list[dict]:
    return [
        {
            "section_id": section_id,
            "status": s15b_status if section_id == "S15B" else "COMPLETE",
        }
        for section_id in DEEP_MANDATORY_SECTIONS
    ]


def _pre(*, mode: str, weather: str, manifest=None, mini_complete: bool = True, compute=None):
    selected_manifest = manifest or [
        {"section_id": section_id, "status": "COMPLETE"}
        for section_id in _catalog(mode)
    ]
    return validate_pre_render_qa(
        compute_contract=compute or _compute(),
        section_manifest=selected_manifest,
        mini_league_denominator_complete=mini_complete,
        report_mode=mode,
        weather_contract_state=weather,
    )


def _post(pre: dict, *, body: str | None = None, weather: str | None = None, mini_complete: bool | None = None):
    return validate_post_render_qa(
        pre_render_qa=pre,
        rendered_body=body if body is not None else valid_visible_body(pre),
        rendered_section_ids=list(pre["expected_section_ids"]),
        rendered_section_states={
            row["section_id"]: row["status"] for row in pre["section_manifest"]
        },
        rendered_compute_fingerprint=pre["compute_fingerprint"],
        render_contract_token=pre["render_contract_token"],
        rendered_counts=dict(pre["expected_counts"]),
        rendered_fact_keys=list(pre["expected_fact_keys"]),
        rendered_model_keys=list(pre["expected_model_keys"]),
        rendered_mini_league_denominator_complete=(
            pre["mini_league_denominator_complete"]
            if mini_complete is None
            else mini_complete
        ),
        rendered_weather_contract_state=weather or pre["weather_contract_state"],
        truncated=False,
    )


def test_tahap3_scenario_registry_is_exact():
    assert TAHAP3_SCENARIOS == (
        "V6_GREEN_COMPLETE",
        "V6_GREEN_CONNECTOR_TRUNCATION",
        "V6_AMBER_RECOVERABLE",
        "MANDATORY_SOURCE_UNAVAILABLE",
        "ICON_UNAVAILABLE",
        "WEATHER_UNAVAILABLE",
        "OPTIMIZER_MC_FAILURE",
        "NORMAL_DEEP",
        "DEADLINE_ACTIVE_HOURLY",
        "FINAL_DEADLINE",
        "LIVE_MATCH_CHECKPOINT",
        "POST_ALL_MATCH",
    )


def test_v6_green_complete_retrieval():
    result = plan_exact_scope_retrieval(
        v6_scope_id="bootstrap",
        v6_scope_state="CURRENT",
        retrieval_state="COMPLETE",
    )
    assert result["action"] == "READ_V6_ONLY"
    assert result["direct_fresh_allowed"] is False
    assert result["legacy_fallback_allowed"] is False


def test_v6_green_connector_truncation_recovers_same_v6_first():
    result = plan_exact_scope_retrieval(
        v6_scope_id="bootstrap",
        v6_scope_state="CURRENT",
        retrieval_state="CONNECTOR_TRUNCATED",
    )
    assert result["action"] == "SAME_V6_RETRIEVAL_RECOVERY"
    assert result["direct_fresh_allowed"] is False
    assert result["scope_lock_required"] is True


def test_v6_amber_recoverable_can_use_exact_scope_direct_fresh_only_after_scope_failure():
    matrix = resolve_report_scope_matrix(
        {
            "official_universe": {
                "required": True,
                "auth_required": False,
                "volatile": True,
                "fresh_v6_available": False,
                "v6_scope_state": "V6_SCOPE_STALE",
                "retrieval_state": "COMPLETE",
                "direct_fresh_available": True,
                "last_good_available": False,
            }
        },
        auth_status="NOT REQUESTED",
    )
    row = matrix["scopes"]["official_universe"]
    assert matrix["report_ready"] is True
    assert row["source"] == "DIRECT_FRESH"
    assert row["direct_fresh_allowed"] is True
    assert row["legacy_fallback_allowed"] is False


def test_mandatory_source_unavailable_stays_visible_and_degraded_not_schema_dropped():
    matrix = resolve_report_scope_matrix(
        {
            "official_universe": {
                "required": True,
                "auth_required": False,
                "volatile": True,
                "fresh_v6_available": False,
                "v6_scope_state": "V6_SCOPE_MISSING",
                "retrieval_state": "COMPLETE",
                "direct_fresh_available": False,
                "last_good_available": False,
            }
        },
        auth_status="NOT REQUESTED",
    )
    row = matrix["scopes"]["official_universe"]
    assert matrix["report_ready"] is True
    assert row["status"] == "DEGRADED"
    assert row["report_blocking"] is False
    assert row["action"] == "RENDER_REQUIRED_SCOPE_UNAVAILABLE"


def test_icon_unavailable_keeps_s14b_visible_with_explicit_degraded_state():
    pre = _pre(
        mode="DEEP",
        weather="DIRECT_CHATGPT",
        manifest=_full_manifest(s15b_status="PARTIAL"),
        mini_complete=False,
    )
    assert pre["status"] == "PASS"
    assert pre["mini_league_contract_state"] == "DEGRADED"
    post = _post(pre, mini_complete=False)
    assert post["status"] == "PASS"
    assert post["visible_mini_league_contract_state"] == "DEGRADED"


def test_weather_unavailable_is_truthful_degraded_not_report_schema_degradation():
    pre = _pre(mode="DEEP", weather="SOURCE_DEGRADED")
    assert pre["status"] == "PASS"
    post = _post(pre, weather="SOURCE_DEGRADED")
    assert post["status"] == "PASS"
    assert post["visible_weather_contract_state"] == "SOURCE_DEGRADED"


def test_optimizer_mc_failure_must_degrade_truthfully_and_fake_pass_still_fails():
    def truthful_degraded(sections):
        sections["OPTIMIZER"] = {
            "content_state": "PARTIAL",
            "degradation_reason": "OPTIMIZER_AND_MC_UNAVAILABLE",
            "routes": [],
        }

    degraded = _compute(mutate_sections=truthful_degraded)
    assert degraded["status"] == "PASS"
    assert degraded["SECTION_CONTRACT"]["checks"]["OPTIMIZER"]["content_state"] == "PARTIAL"

    def fabricated(sections):
        sections["OPTIMIZER"].pop("execution_proof")

    fake = _compute(mutate_sections=fabricated)
    assert fake["status"] == "FAIL"
    assert fake["PROVENANCE"]["execution"]["status"] == "FAIL"
    assert "OPTIMIZER_EXECUTION_PROOF_MISSING" in fake["PROVENANCE"]["execution"]["failures"]


def test_normal_deep_keeps_full_canonical_backbone_and_actual_body_passes():
    pre = _pre(mode="DEEP", weather="DIRECT_CHATGPT")
    assert pre["status"] == "PASS"
    assert pre["expected_section_ids"] == list(DEEP_MANDATORY_SECTIONS)
    assert _post(pre)["status"] == "PASS"


def test_deadline_active_hourly_uses_full_backbone_not_progress_only():
    pre = _pre(mode="DEADLINE", weather="DIRECT_CHATGPT")
    assert pre["status"] == "PASS"
    assert pre["expected_section_ids"] == list(MANDATORY_SECTIONS)
    post = _post(pre)
    assert post["status"] == "PASS"
    assert post["visible_body_validated"] is True


@pytest.mark.parametrize("mode", ["DEADLINE", "FINAL"])
def test_final_and_deadline_modes_keep_canonical_backbone(mode: str):
    pre = _pre(mode=mode, weather="DIRECT_CHATGPT")
    assert pre["status"] == "PASS"
    expected = (
        list(FINAL_MANDATORY_SECTIONS)
        if mode == "FINAL"
        else list(DEEP_MANDATORY_SECTIONS)
    )
    assert pre["expected_section_ids"] == expected
    assert _post(pre)["status"] == "PASS"


def test_live_match_checkpoint_uses_match1_to_match13_catalog_not_full_backbone():
    manifest = [
        {"section_id": section_id, "status": "COMPLETE"}
        for section_id in MATCH_MANDATORY_SECTIONS
    ]
    pre = _pre(
        mode="MATCH",
        weather="MATCH_CURRENT",
        manifest=manifest,
    )
    assert pre["status"] == "PASS"
    assert pre["expected_section_ids"] == list(MATCH_MANDATORY_SECTIONS)
    assert pre["generated_section_ids"] == pre["expected_section_ids"]
    post = _post(
        pre,
        body=valid_match_visible_body(pre),
        weather="MATCH_CURRENT",
    )
    assert post["status"] == "PASS"
    assert post["visible_body_validated"] is True


def test_post_all_match_uses_own_canonical_backbone_and_requires_scout_marker():
    context = build_ad_hoc_report_context(
        request_id="req-post-all-match",
        requested_at="2026-09-18T11:45:00+07:00",
        report_type="POST_ALL_MATCH",
    )
    assert context["qa_report_mode"] == "POST_ALL_MATCH"

    pre = _pre(mode="POST_ALL_MATCH", weather="DIRECT_CHATGPT")
    assert pre["status"] == "PASS"
    assert pre["expected_section_ids"] == list(POST_ALL_MATCH_MANDATORY_SECTIONS)

    body = valid_visible_body(pre)
    missing_marker = body.replace(
        "GW COMPLETED MATCH-BY-MATCH SCOUT",
        "MATCH-BY-MATCH REVIEW",
        1,
    )
    assert _post(pre, body=missing_marker)["status"] == "FAIL"

    post = _post(pre, body=body)
    assert post["status"] == "PASS"
    assert post["visible_body_validated"] is True
