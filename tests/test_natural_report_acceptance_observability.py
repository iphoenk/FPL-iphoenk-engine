from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.domains.report_plane.report_delivery import (
    build_natural_report_acceptance_proof,
    seal_natural_report_acceptance_proof,
    seal_same_slot_completion_ledger,
    validate_natural_report_acceptance_proof_readback,
)


OCCURRENCE = "2026-09-21T00:30:00+07:00"


def _fixture(**overrides):
    row = {
        "fixture_id": 123,
        "event": 6,
        "kickoff_time": "2026-09-20T23:00:00+07:00",
        "started": True,
        "finished": False,
        "finished_provisional": False,
        "minutes": 45,
        "status": "LIVE",
        "evidence_source": "official_fpl",
        "evidence_generated_at": "2026-09-21T00:29:10+07:00",
        "checked_at": "2026-09-21T00:30:08+07:00",
        "freshness_classification": "FRESH",
    }
    row.update(overrides)
    return row


def _evidence(**overrides):
    row = {
        "scheduler_occurrence": OCCURRENCE,
        "timezone": "Asia/Jakarta",
        "observed_at": "2026-09-21T00:30:05+07:00",
        "core_logical_slot": "2026-09-21T00:00:00+07:00",
        "scheduler_identity": "FPL Master Monitor V12",
        "core_gate_executed": True,
        "core_gate_resolution": "ALREADY_FULFILLED",
        "same_slot_fulfilled": True,
        "bound_v6_run_id": "run-123",
        "v6_publication_sha": "a" * 40,
        "v6_generation": "gen-123",
        "publish_integrity": "PASS",
        "authoritative_runtime_snapshot": True,
        "duplicate_acquisition": False,
        "preliminary_report_due": False,
        "preliminary_reason": "NO_STATIC_TRIGGER",
        "dynamic_evidence_checked": True,
        "dynamic_trigger": True,
        "dynamic_trigger_reason": "SCORING_GW_FIXTURE_LIVE",
        "final_report_due": True,
        "final_mode": "MATCH",
        "dynamic_fixture_evidence": [_fixture()],
        "render_attempted": True,
        "render_completed": True,
        "rendered_mode": "MATCH",
        "rendered_section_ids": [f"MATCH{index}" for index in range(1, 14)],
        "rendered_section_names": [f"Match section {index}" for index in range(1, 14)],
        "section_count": 13,
        "critical_sections_present": True,
        "post_render_qa_pass": True,
        "human_facing_qa_pass": True,
        "render_content_digest": "b" * 64,
        "render_completed_at": "2026-09-21T00:30:20+07:00",
        "report_instance_count": 1,
        "locked_team_source": "OFFICIAL_FPL_PUBLIC_SUBMITTED_PICKS",
        "locked_team_status": "COMPLETE",
        "submitted_15_available": True,
        "xi_available": True,
        "bench_available": True,
        "captain_available": True,
        "vice_available": True,
        "league_id": 99,
        "league_name": "ICON+",
        "icon_live_requested": True,
        "icon_live_status": "COMPLETE",
        "manager_count_expected": 10,
        "manager_picks_covered": 10,
        "ownership_available": True,
        "starter_available": True,
        "icon_captain_available": True,
        "icon_vice_available": True,
        "eo_status": "COMPLETE",
        "live_points_status": "COMPLETE",
        "delivery_ui_ack": "UNAVAILABLE",
    }
    row.update(overrides)
    return row


def test_01_natural_occurrence_builds_acceptance_proof():
    proof = build_natural_report_acceptance_proof(_evidence())
    assert proof["proof_kind"] == "V12_NATURAL_REPORT_ACCEPTANCE_PROOF"
    assert proof["durable_acceptance_evidence"] is True
    assert proof["authoritative"] is False


def test_02_occurrence_identity_is_preserved_exactly():
    proof = build_natural_report_acceptance_proof(_evidence())
    assert proof["occurrence"] == {
        "scheduler_occurrence": OCCURRENCE,
        "timezone": "Asia/Jakarta",
        "observed_at": "2026-09-21T00:30:05+07:00",
        "core_logical_slot": "2026-09-21T00:00:00+07:00",
        "scheduler_identity": "FPL Master Monitor V12",
    }


def test_03_core_result_and_duplicate_acquisition_are_retained():
    proof = build_natural_report_acceptance_proof(_evidence())
    core = proof["core"]
    assert core["core_gate_executed"] is True
    assert core["core_gate_resolution"] == "ALREADY_FULFILLED"
    assert core["bound_v6_run_id"] == "run-123"
    assert core["publish_integrity"] == "PASS"
    assert core["authoritative_runtime_snapshot"] is True
    assert core["duplicate_acquisition"] is False


def test_04_two_stage_report_due_is_retained():
    proof = build_natural_report_acceptance_proof(_evidence())
    due = proof["report_due"]
    assert due["preliminary_report_due"] is False
    assert due["preliminary_reason"] == "NO_STATIC_TRIGGER"
    assert due["dynamic_evidence_checked"] is True
    assert due["dynamic_trigger"] is True
    assert due["final_report_due"] is True
    assert due["final_mode"] == "MATCH"


def test_05_live_fixture_evidence_fields_are_retained_without_reinterpretation():
    proof = build_natural_report_acceptance_proof(_evidence())
    fixture = proof["dynamic_fixture_evidence"][0]
    assert fixture["fixture_id"] == 123
    assert fixture["event"] == 6
    assert fixture["kickoff_time"] == "2026-09-20T23:00:00+07:00"
    assert fixture["started"] is True
    assert fixture["finished"] is False
    assert fixture["finished_provisional"] is False
    assert fixture["minutes"] == 45
    assert fixture["status"] == "LIVE"
    assert fixture["evidence_source"] == "official_fpl"
    assert fixture["freshness_classification"] == "FRESH"


def test_06_historical_finished_provisional_shape_is_recorded_not_repaired():
    evidence = _evidence(
        dynamic_fixture_evidence=[
            _fixture(finished=False, finished_provisional=True, minutes=90, status="FINISHED_PROVISIONAL")
        ]
    )
    fixture = build_natural_report_acceptance_proof(evidence)["dynamic_fixture_evidence"][0]
    assert fixture["started"] is True
    assert fixture["finished"] is False
    assert fixture["finished_provisional"] is True
    assert fixture["minutes"] == 90


def test_07_match_route_pass_is_independent_of_ui_ack():
    proof = build_natural_report_acceptance_proof(_evidence(delivery_ui_ack="UNAVAILABLE"))
    assert proof["acceptance"]["routing_acceptance"] == "PASS"
    assert proof["acceptance"]["render_acceptance"] == "PASS"
    assert proof["acceptance"]["ui_delivery_ack"] == "UNAVAILABLE"


def test_08_match_trigger_true_but_final_not_due_is_routing_fail():
    proof = build_natural_report_acceptance_proof(
        _evidence(final_report_due=False, final_mode=None, render_attempted=False, render_completed=False)
    )
    assert proof["acceptance"]["routing_acceptance"] == "FAIL"


def test_09_match_trigger_true_but_match_absent_is_routing_fail():
    proof = build_natural_report_acceptance_proof(_evidence(final_mode="DEEP"))
    assert proof["acceptance"]["routing_acceptance"] == "FAIL"


def test_10_unresolved_dynamic_trigger_remains_unresolved():
    proof = build_natural_report_acceptance_proof(
        _evidence(dynamic_trigger="UNRESOLVED", dynamic_trigger_reason="FRESH_EVIDENCE_UNAVAILABLE")
    )
    assert proof["acceptance"]["routing_acceptance"] == "UNRESOLVED"
    assert proof["acceptance"]["render_acceptance"] == "UNRESOLVED"


def test_11_render_completed_is_not_ui_delivery_ack():
    proof = build_natural_report_acceptance_proof(_evidence(delivery_ui_ack="UNAVAILABLE"))
    assert proof["render"]["render_completed"] is True
    assert proof["render"]["render_proven"] is True
    assert proof["delivery"]["delivery_ui_ack"] == "UNAVAILABLE"
    assert proof["delivery"]["rendering_implies_ui_delivery"] is False


def test_12_render_proof_requires_digest_critical_sections_and_single_report():
    no_digest = build_natural_report_acceptance_proof(_evidence(render_content_digest=None))
    no_critical = build_natural_report_acceptance_proof(_evidence(critical_sections_present=False))
    duplicate = build_natural_report_acceptance_proof(_evidence(report_instance_count=2))
    assert no_digest["render"]["render_proven"] is False
    assert no_critical["render"]["render_proven"] is False
    assert duplicate["render"]["render_proven"] is False


def test_13_successful_match_render_can_be_proven_without_delivery_ack():
    proof = build_natural_report_acceptance_proof(_evidence())
    assert proof["render"]["render_proven"] is True
    assert proof["acceptance"]["render_acceptance"] == "PASS"
    assert proof["delivery"]["delivery_ui_ack"] == "UNAVAILABLE"


def test_14_ui_ack_proven_requires_actual_ack_evidence():
    proof = build_natural_report_acceptance_proof(_evidence(delivery_ui_ack="PROVEN"))
    assert proof["delivery"]["delivery_ui_ack"] == "UNAVAILABLE"
    assert "DELIVERY_UI_ACK_PROOF_INCOMPLETE" in proof["failures"]


def test_15_ui_ack_proven_is_allowed_only_with_receipt_and_timestamp():
    proof = build_natural_report_acceptance_proof(
        _evidence(
            delivery_ui_ack="PROVEN",
            ui_ack_evidence={
                "provider_receipt_id": "ui-receipt-1",
                "acknowledged_at": "2026-09-21T00:30:25+07:00",
            },
        )
    )
    assert proof["delivery"]["delivery_ui_ack"] == "PROVEN"
    assert proof["delivery"]["ui_ack_evidence"]["provider_receipt_id"] == "ui-receipt-1"


def test_16_locked_team_source_and_status_are_retained_without_payload_duplication():
    proof = build_natural_report_acceptance_proof(_evidence())
    locked = proof["locked_team"]
    assert locked["locked_team_source"] == "OFFICIAL_FPL_PUBLIC_SUBMITTED_PICKS"
    assert locked["locked_team_status"] == "COMPLETE"
    assert locked["submitted_15_available"] is True
    assert locked["xi_available"] is True
    assert locked["bench_available"] is True
    assert locked["captain_available"] is True
    assert locked["vice_available"] is True
    assert "players" not in locked


def test_17_icon_coverage_complete_m_over_n_is_retained():
    icon = build_natural_report_acceptance_proof(_evidence())["icon_plus"]
    assert icon["manager_count_expected"] == 10
    assert icon["manager_picks_covered"] == 10
    assert icon["picks_coverage"] == "10/10"
    assert icon["picks_coverage_status"] == "COMPLETE"


def test_18_partial_icon_coverage_remains_partial():
    icon = build_natural_report_acceptance_proof(
        _evidence(manager_count_expected=10, manager_picks_covered=7, icon_live_status="PARTIAL")
    )["icon_plus"]
    assert icon["picks_coverage"] == "7/10"
    assert icon["picks_coverage_status"] == "PARTIAL"


def test_19_eo_unavailable_does_not_blank_healthy_exposure_proof():
    icon = build_natural_report_acceptance_proof(
        _evidence(eo_status="UNAVAILABLE", live_points_status="UNAVAILABLE")
    )["icon_plus"]
    assert icon["eo_status"] == "UNAVAILABLE"
    assert icon["ownership_available"] is True
    assert icon["starter_available"] is True
    assert icon["captain_available"] is True
    assert icon["vice_available"] is True


def test_20_one_icon_subscope_failure_does_not_erase_other_fields():
    icon = build_natural_report_acceptance_proof(
        _evidence(icon_captain_available=False, eo_status="UNAVAILABLE")
    )["icon_plus"]
    assert icon["captain_available"] is False
    assert icon["ownership_available"] is True
    assert icon["starter_available"] is True
    assert icon["vice_available"] is True


def test_21_deep_match_is_one_coherent_report():
    deep_sections = (
        [f"S{index:02d}" for index in range(1, 16)]
        + ["S15B"]
        + [f"S{index:02d}" for index in range(16, 20)]
    )
    match_sections = [f"MATCH{index}" for index in range(1, 14)]
    section_ids = deep_sections + match_sections
    proof = build_natural_report_acceptance_proof(
        _evidence(
            final_mode="DEEP+MATCH",
            rendered_mode="DEEP+MATCH",
            rendered_section_ids=section_ids,
            rendered_section_names=[f"Section {index}" for index in range(len(section_ids))],
            section_count=len(section_ids),
            report_instance_count=1,
        )
    )
    assert proof["acceptance"]["routing_acceptance"] == "PASS"
    assert proof["acceptance"]["render_acceptance"] == "PASS"
    assert proof["render"]["report_instance_count"] == 1


def test_22_duplicate_report_is_not_accepted_as_render_proof():
    proof = build_natural_report_acceptance_proof(_evidence(report_instance_count=2))
    assert proof["render"]["render_proven"] is False
    assert proof["acceptance"]["render_acceptance"] == "FAIL"
    assert "REPORT_INSTANCE_COUNT_INVALID" in proof["failures"]


def test_23_prospective_proof_seals_and_readback_validates():
    sealed = seal_natural_report_acceptance_proof(_evidence())
    assert sealed["immutable"] is True
    assert len(sealed["proof_hash"]) == 64
    readback = validate_natural_report_acceptance_proof_readback(
        sealed, expected_scheduler_occurrence=OCCURRENCE
    )
    assert readback["status"] == "PASS"
    assert readback["readback_valid"] is True
    assert readback["acceptance"]["routing_acceptance"] == "PASS"
    assert readback["acceptance"]["render_acceptance"] == "PASS"
    assert readback["acceptance"]["ui_delivery_ack"] == "UNAVAILABLE"


def test_24_tampered_proof_fails_readback():
    sealed = seal_natural_report_acceptance_proof(_evidence())
    tampered = deepcopy(sealed)
    tampered["report_due"]["final_mode"] = "DEEP"
    readback = validate_natural_report_acceptance_proof_readback(
        tampered, expected_scheduler_occurrence=OCCURRENCE
    )
    assert readback["status"] == "FAIL"
    assert "NATURAL_ACCEPTANCE_PROOF_HASH_MISMATCH" in readback["failures"]


def test_25_historical_occurrence_cannot_be_retrofitted_without_existing_proof():
    sealed = seal_natural_report_acceptance_proof(
        _evidence(historical_immutable=True, proof_existed_at_occurrence=False)
    )
    assert sealed["immutable"] is False
    assert sealed["proof_hash"] is None
    assert "HISTORICAL_ACCEPTANCE_PROOF_BACKFILL_FORBIDDEN" in sealed["failures"]


def test_26_existing_exact_proof_is_idempotently_reused():
    sealed = seal_natural_report_acceptance_proof(_evidence())
    reused = seal_natural_report_acceptance_proof(_evidence(), existing_proof=sealed)
    assert reused["proof_hash"] == sealed["proof_hash"]
    assert reused["idempotent_reuse"] is True


def test_27_dynamic_match_logic_is_observed_not_recomputed():
    provisional = _fixture(
        finished=False,
        finished_provisional=True,
        minutes=90,
        status="FINISHED_PROVISIONAL",
    )
    proof = build_natural_report_acceptance_proof(
        _evidence(dynamic_trigger=False, final_report_due=False, final_mode=None,
                  render_attempted=False, render_completed=False,
                  dynamic_fixture_evidence=[provisional])
    )
    assert proof["report_due"]["dynamic_trigger"] is False
    assert proof["acceptance"]["routing_acceptance"] == "NOT_APPLICABLE"
    assert proof["dynamic_fixture_evidence"][0]["finished_provisional"] is True


def test_28_evidence_proof_does_not_become_authority():
    proof = build_natural_report_acceptance_proof(_evidence())
    for key in (
        "authoritative",
        "factual_authority",
        "report_authority",
        "methodology_authority",
        "decision_authority",
        "scheduler_authority",
    ):
        assert proof[key] is False


def _completion_ledger_evidence(**overrides):
    row = {
        "natural_occurrence_id": "natural-0030",
        "logical_data_slot": "2026-09-21T00:00:00+07:00",
        "logical_report_slot": OCCURRENCE,
        "v6_terminal_state": "PASS",
        "governed_v6_run_id": "run-123",
        "publication_readback_pass": True,
        "decision_context_hydrated": True,
        "decision_context_slot": OCCURRENCE,
        "report_prefetch_identity_match": True,
        "report_prefetch_logical_slot": OCCURRENCE,
        "report_prefetch_freshness": "CURRENT",
        "weather_attempted": True,
        "weather_status": "PASS",
        "pre_render_qa_pass": True,
        "canonical_render_completed": True,
        "canonical_render_hash": "c" * 64,
        "post_render_qa_pass": True,
        "report_contract_pass": True,
        "can_emit": True,
        "visible_emitted": True,
        "delivery_acknowledged": True,
        "delivery_proof_valid": True,
        "canonical_receipt_id": "d" * 64,
        "canonical_receipt_slot": OCCURRENCE,
        "report_slot_fulfilled": True,
        "natural_report_acceptance_evidence": _evidence(),
    }
    row.update(overrides)
    return row


def test_29_same_slot_ledger_attaches_one_sealed_acceptance_proof():
    ledger = seal_same_slot_completion_ledger(_completion_ledger_evidence())
    proof = ledger["natural_report_acceptance_proof"]
    assert ledger["status"] == "PASS"
    assert proof["immutable"] is True
    assert len(proof["proof_hash"]) == 64
    assert proof["acceptance"]["routing_acceptance"] == "PASS"
    assert proof["acceptance"]["render_acceptance"] == "PASS"


def test_30_missing_ui_delivery_does_not_erase_sealed_routing_render_proof():
    ledger = seal_same_slot_completion_ledger(
        _completion_ledger_evidence(
            delivery_acknowledged=False,
            delivery_proof_valid=False,
            report_slot_fulfilled=False,
        )
    )
    proof = ledger["natural_report_acceptance_proof"]
    assert ledger["status"] == "FAIL"
    assert proof["immutable"] is True
    assert proof["acceptance"]["routing_acceptance"] == "PASS"
    assert proof["acceptance"]["render_acceptance"] == "PASS"
    assert proof["acceptance"]["ui_delivery_ack"] == "UNAVAILABLE"


def test_31_acceptance_attachment_does_not_change_completion_ledger_semantics():
    without = seal_same_slot_completion_ledger(
        {
            key: value
            for key, value in _completion_ledger_evidence().items()
            if key != "natural_report_acceptance_evidence"
        }
    )
    with_proof = seal_same_slot_completion_ledger(_completion_ledger_evidence())
    assert without["status"] == with_proof["status"] == "PASS"
    assert without["report_slot_fulfilled"] is True
    assert with_proof["report_slot_fulfilled"] is True


def test_32_same_slot_ledger_persists_only_sealed_acceptance_proof():
    ledger = seal_same_slot_completion_ledger(_completion_ledger_evidence())
    assert "natural_report_acceptance_evidence" not in ledger
    assert ledger["natural_report_acceptance_proof"]["immutable"] is True




def test_33_natural_1230_cannot_reuse_1100_core_as_same_slot():
    proof = build_natural_report_acceptance_proof(
        _evidence(
            scheduler_occurrence="2026-09-21T12:30:00+07:00",
            observed_at="2026-09-21T12:33:05+07:00",
            core_logical_slot="2026-09-21T11:00:00+07:00",
            core_gate_resolution="ALREADY_FULFILLED",
            same_slot_fulfilled=True,
        )
    )
    assert proof["core"]["core_slot_relation"]["valid"] is False
    assert (
        proof["core"]["core_slot_relation"]["expected_core_logical_slot"]
        == "2026-09-21T12:00:00+07:00"
    )
    assert "CORE_LOGICAL_SLOT_MISMATCH" in proof["failures"]
    assert proof["evidence_integrity"] == "FAIL"


def test_34_natural_1230_exact_1200_core_passes_slot_relation():
    proof = build_natural_report_acceptance_proof(
        _evidence(
            scheduler_occurrence="2026-09-21T12:30:00+07:00",
            observed_at="2026-09-21T12:33:05+07:00",
            core_logical_slot="2026-09-21T05:00:00+00:00",
        )
    )
    relation = proof["core"]["core_slot_relation"]
    assert relation["valid"] is True
    assert relation["expected_core_logical_slot"] == "2026-09-21T12:00:00+07:00"


def test_35_under_rendered_deep_like_broken_1230_report_is_rejected():
    partial_sections = [
        "S01",
        "S11",
        "S12",
        "S13",
        "S15B",
        "S17",
        "S18",
        "S19",
    ]
    proof = build_natural_report_acceptance_proof(
        _evidence(
            preliminary_report_due=True,
            final_report_due=True,
            final_mode="DEEP",
            dynamic_trigger=False,
            rendered_mode="DEEP",
            rendered_section_ids=partial_sections,
            rendered_section_names=[f"Section {value}" for value in partial_sections],
            section_count=len(partial_sections),
        )
    )
    assert proof["render"]["render_proven"] is False
    assert proof["acceptance"]["render_acceptance"] == "FAIL"
    assert "S02" in proof["render"]["section_catalog"]["missing_section_ids"]
    assert "S14" in proof["render"]["section_catalog"]["missing_section_ids"]
    assert "S16" in proof["render"]["section_catalog"]["missing_section_ids"]
    assert any(
        failure.startswith("RENDER_SECTION_CATALOG_MISSING=")
        for failure in proof["failures"]
    )


def test_36_complete_deep_catalog_with_post_render_and_human_qa_is_render_proven():
    deep_sections = (
        [f"S{index:02d}" for index in range(1, 16)]
        + ["S15B"]
        + [f"S{index:02d}" for index in range(16, 20)]
    )
    proof = build_natural_report_acceptance_proof(
        _evidence(
            preliminary_report_due=True,
            final_report_due=True,
            final_mode="DEEP",
            dynamic_trigger=False,
            rendered_mode="DEEP",
            rendered_section_ids=deep_sections,
            rendered_section_names=[f"Section {value}" for value in deep_sections],
            section_count=len(deep_sections),
        )
    )
    assert proof["render"]["section_catalog"]["catalog_complete"] is True
    assert proof["render"]["section_catalog"]["catalog_order_exact"] is True
    assert proof["render"]["render_proven"] is True
    assert proof["acceptance"]["render_acceptance"] == "PASS"


def test_37_render_proof_requires_post_render_and_human_facing_qa():
    deep_sections = (
        [f"S{index:02d}" for index in range(1, 16)]
        + ["S15B"]
        + [f"S{index:02d}" for index in range(16, 20)]
    )
    proof = build_natural_report_acceptance_proof(
        _evidence(
            preliminary_report_due=True,
            final_report_due=True,
            final_mode="DEEP",
            dynamic_trigger=False,
            rendered_mode="DEEP",
            rendered_section_ids=deep_sections,
            rendered_section_names=[f"Section {value}" for value in deep_sections],
            section_count=len(deep_sections),
            post_render_qa_pass=False,
            human_facing_qa_pass=False,
        )
    )
    assert proof["render"]["render_proven"] is False
    assert "POST_RENDER_QA_NOT_PROVEN" in proof["failures"]
    assert "HUMAN_FACING_QA_NOT_PROVEN" in proof["failures"]
