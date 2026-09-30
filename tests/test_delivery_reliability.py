from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.v12_delivery_reliability import (
    CANONICAL_DEEP_SECTIONS,
    PrefetchNotTerminal,
    assemble_degraded_deep_report,
    build_occurrence_state,
    build_presentation_qa_manifest,
    inspect_prefetch_terminal,
    validate_delivery_bundle,
    validate_presentation_qa_manifest,
    validate_serving_snapshot,
    wait_for_prefetch_terminal,
    write_serving_artifacts,
)
from src.engines.v12_private_publisher import (
    PrivatePublishError,
    publish_private_output,
)
from src.engines.v12_delivery_security import build_public_issue_proof, scan_public_text


SLOT = "2026-09-28T12:30:00+07:00"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_prefetch(root: Path, *, slot: str, publish: str = "PASS") -> None:
    _write_json(
        root / "data/v6/report_prefetch/latest.json",
        {
            "report_kind": "full_master",
            "target_logical_report_slot": slot,
            "personal_requested": True,
            "mini_league_requested": True,
            "public_core_complete": True,
            "fresh_for_target_report": True,
            "generated_at": slot,
            "authenticated_personal_required_for_public_green": False,
            "public_personal_status": "AVAILABLE",
            "mini_league_status": "AVAILABLE",
            "public_control_failures": [],
            "report_prefetch_run_id": "fixture-prefetch",
            "artifacts": [
                {
                    "artifact_class": "REPORT_PREFETCH",
                    "status": "PROVEN",
                    "publication_run_id": "fixture-publication",
                    "published_at": slot,
                }
            ],
        },
    )
    _write_json(
        root / "data/v6/health/report_prefetch.json",
        {"prefetch_status": "GREEN", "public_core_status": "GREEN"},
    )
    _write_json(
        root / "data/v6/health/publish_integrity.json",
        {"status": publish},
    )


def test_1230_race_waits_for_exact_terminal_prefetch_and_refetches(tmp_path: Path):
    old_slot = "2026-09-28T11:30:00+07:00"
    _write_prefetch(tmp_path, slot=old_slot)
    refresh_calls = []

    def refresh() -> None:
        refresh_calls.append(True)
        _write_prefetch(tmp_path, slot=SLOT)

    result = wait_for_prefetch_terminal(
        tmp_path,
        report_slot=SLOT,
        refresh_fn=refresh,
        timeout_seconds=30,
        poll_seconds=0.1,
        sleep_fn=lambda _: None,
        monotonic_fn=lambda: 0.0,
    )
    assert result["same_occurrence_bound"] is True
    assert result["target_logical_report_slot"] == SLOT
    assert result["defensive_wait"]["attempts"] == 1
    assert len(refresh_calls) == 1


def test_runner_does_not_consume_old_snapshot_when_budget_expires(tmp_path: Path):
    _write_prefetch(tmp_path, slot="2026-09-28T11:30:00+07:00")
    with pytest.raises(PrefetchNotTerminal, match="PREFETCH_NOT_TERMINAL"):
        wait_for_prefetch_terminal(
            tmp_path,
            report_slot=SLOT,
            timeout_seconds=0,
        )


def test_prefetch_gate_requires_terminal_publication(tmp_path: Path):
    _write_prefetch(tmp_path, slot=SLOT, publish="FAIL")
    state = inspect_prefetch_terminal(tmp_path, report_slot=SLOT)
    assert state["terminal"] is False
    assert "runtime_publication_terminal" in state["failed_checks"]


@pytest.mark.parametrize(
    ("root_failure", "root_stage"),
    [
        ("PREFETCH_NOT_TERMINAL", "V6_REPORT_PREFETCH_BINDING"),
        ("MINI_LEAGUE_UNAVAILABLE", "P1_8_MINI_LEAGUE_OVERLAY"),
        ("SCANNER_FAILURE", "WATCHLIST20"),
        ("P1_7_FAILURE", "P1_7_LINEUP"),
        ("OPTIMIZER_FAILURE", "P1_2_PACKAGE_UTILITY"),
        ("MC_FAILURE", "P1_4_MONTE_CARLO"),
        ("PRICE_PREDICTOR_UNAVAILABLE", "OFFICIAL_FPL_PREDICTOR"),
        ("RENDER_QA_FAILURE", "POST_RENDER_QA"),
        ("PRIVATE_PUBLISHER_FAILURE", "PRIVATE_PUBLISHER"),
    ],
)
def test_failure_injection_always_materializes_23_section_report(
    tmp_path: Path,
    root_failure: str,
    root_stage: str,
):
    output = tmp_path / "out"
    bundle = assemble_degraded_deep_report(
        runtime_root=tmp_path / "runtime",
        report_slot=SLOT,
        output_dir=output,
        root_failure=root_failure,
        root_stage=root_stage,
    )
    assert bundle["delivery_status"] == "READY_DEGRADED"
    assert len(bundle["report"]["sections"]) == 23
    assert bundle["report"]["sections"][0]["section_id"] == "S01"
    assert bundle["report"]["sections"][-1]["section_id"] == "S19"
    assert bundle["report"]["sections"][0]["content"]["decision"] == "WAIT"
    assert bundle["report"]["sections"][-1]["content"]["final_judgement"]
    assert output.joinpath("report_body.md").read_text(encoding="utf-8").strip()
    failed = [
        row for row in bundle["stage_ledger"]
        if row["status"] == "FAILED"
    ]
    assert len(failed) == 1
    assert failed[0]["stage"] == root_stage
    assert validate_delivery_bundle(bundle) == []


def test_degraded_status_taxonomy_never_marks_blocked_downstream_red(tmp_path: Path):
    bundle = assemble_degraded_deep_report(
        runtime_root=tmp_path / "runtime",
        report_slot=SLOT,
        output_dir=tmp_path / "out",
        root_failure="PREFETCH_NOT_TERMINAL",
        root_stage="V6_REPORT_PREFETCH_BINDING",
    )
    statuses = {
        row["stage"]: row["status"] for row in bundle["stage_ledger"]
    }
    assert statuses["V6_REPORT_PREFETCH_BINDING"] == "FAILED"
    assert statuses["WATCHLIST20"] == "NOT_RUN"
    assert statuses["P1_7_LINEUP"] == "NOT_RUN"
    assert statuses["P1_2_PACKAGE_UTILITY"] == "NOT_RUN"
    assert statuses["P1_4_MONTE_CARLO"] == "NOT_RUN"


def test_serving_snapshot_is_decision_first_and_exact_23(tmp_path: Path):
    bundle = assemble_degraded_deep_report(
        runtime_root=tmp_path / "runtime",
        report_slot=SLOT,
        output_dir=tmp_path / "out",
        root_failure="PREFETCH_NOT_TERMINAL",
    )
    snapshot = write_serving_artifacts(
        bundle=bundle,
        output_dir=tmp_path / "out",
    )
    assert snapshot["schema_version"] == 2
    assert snapshot["delivery_status"] == "READY_DEGRADED"
    assert snapshot["decision"] == "WAIT"
    assert "GW" in snapshot
    assert snapshot["freeze_time"] == "UNAVAILABLE"
    assert isinstance(snapshot["source_freshness"], dict)
    assert isinstance(snapshot["lineage"], dict)
    assert "supersedes" in snapshot
    assert list(snapshot["sections"]) == [
        section_id for section_id, _ in CANONICAL_DEEP_SECTIONS
    ]
    assert list(snapshot["section_states"]) == [
        section_id for section_id, _ in CANONICAL_DEEP_SECTIONS
    ]
    assert list(snapshot["source_freshness"]["sections"]) == [
        section_id for section_id, _ in CANONICAL_DEEP_SECTIONS
    ]
    assert validate_serving_snapshot(snapshot) == []
    assert (tmp_path / "out/serving_report.json").is_file()
    assert (tmp_path / "out/serving_report.md").is_file()
    assert (tmp_path / "out/delivery_status.json").is_file()
    assert (tmp_path / "out/delivery_state.json").is_file()
    assert (tmp_path / "out/presentation_qa.json").is_file()
    occurrence = build_occurrence_state(bundle)
    assert occurrence["current_state"] == "PUBLISHED_DEGRADED"
    assert occurrence["occurrence_id"] == f"DEEP|{SLOT}"
    qa = build_presentation_qa_manifest(bundle)
    assert qa["section_count"] == 23
    assert qa["decision_first"] is True
    assert qa["root_failure_count"] == 1
    assert validate_presentation_qa_manifest(qa) == []


def _canonical_dir(
    root: Path,
    *,
    delivery_status: str,
    runner_status: str,
    stage3_status: str,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    sections = [
        {
            "section_id": section_id,
            "label": label,
            "state": "COMPLETE" if delivery_status == "READY_FULL" else "DEGRADED",
            "content": {"decision": "WAIT"} if section_id == "S01" else (
                {"final_judgement": "WAIT"} if section_id == "S19" else {}
            ),
        }
        for section_id, label in CANONICAL_DEEP_SECTIONS
    ]
    bundle = {
        "schema": "TEST",
        "occurrence_id": f"DEEP|{SLOT}",
        "report_mode": "DEEP",
        "report_slot": SLOT,
        "planning_gw": 6,
        "runner_status": runner_status,
        "delivery_status": delivery_status,
        "root_failure": (
            "ANALYTICS_PIPELINE_FAILURE:TEST"
            if delivery_status == "READY_DEGRADED"
            else None
        ),
        "pre_render_qa": {
            "status": (
                "PASS"
                if delivery_status == "READY_FULL"
                else "DEGRADED_PRESENTATION_PASS"
            )
        },
        "post_render_qa": {
            "status": (
                "PASS"
                if delivery_status == "READY_FULL"
                else "DEGRADED_PRESENTATION_PASS"
            )
        },
        "human_facing_qa": {"status": "PASS", "failures": []},
        "section_manifest": [
            {"section_id": row["section_id"], "status": row["state"]}
            for row in sections
        ],
        "report": {"sections": sections},
        "visible_body": f"{delivery_status}\n",
    }
    _write_json(root / "report_bundle.json", bundle)
    (root / "report_body.md").write_text(
        f"# FPL MASTER V12\n{delivery_status}\n", encoding="utf-8"
    )
    _write_json(
        root / "execution_proof.json",
        {
            "runner_status": runner_status,
            "stage3_action": "WAIT" if runner_status == "PASS" else None,
            "prior_analytics_relabelled_fresh": False,
        },
    )
    stage3 = {"status": stage3_status}
    if stage3_status == "DEGRADED":
        stage3.update(
            {
                "stage3_executed": False,
                "stage3_pass_claimed": False,
                "mc_pass_claimed": False,
            }
        )
    _write_json(root / "stage3_acceptance.json", stage3)
    _write_json(
        root / "serving_report.json",
        {
            "schema_version": 1,
            "occurrence_id": f"DEEP|{SLOT}",
            "report_slot": SLOT,
            "report_mode": "DEEP",
            "delivery_status": delivery_status,
            "decision": "WAIT",
            "root_failure": (
                "ANALYTICS_PIPELINE_FAILURE:TEST"
                if delivery_status == "READY_DEGRADED"
                else None
            ),
            "sections": {row["section_id"]: row for row in sections},
        },
    )
    (root / "serving_report.md").write_text(
        f"{delivery_status}\n", encoding="utf-8"
    )
    _write_json(
        root / "delivery_status.json",
        {
            "occurrence_id": f"DEEP|{SLOT}",
            "delivery_status": delivery_status,
        },
    )
    return root


def test_private_publisher_upgrades_same_occurrence_degraded_to_full(tmp_path: Path):
    private = tmp_path / "private"
    degraded = _canonical_dir(
        tmp_path / "degraded",
        delivery_status="READY_DEGRADED",
        runner_status="DEGRADED",
        stage3_status="DEGRADED",
    )
    first = publish_private_output(
        canonical_dir=degraded,
        private_root=private,
        run_id="1",
        season=None,
        model_sha="m1",
        runtime_sha="r1",
    )
    assert first["private_delivery_status"] == "PASS"
    assert first["delivery_status"] == "READY_DEGRADED"
    assert json.loads(
        (private / "latest/delivery_status.json").read_text(encoding="utf-8")
    )["delivery_status"] == "READY_DEGRADED"

    full = _canonical_dir(
        tmp_path / "full",
        delivery_status="READY_FULL",
        runner_status="PASS",
        stage3_status="PASS",
    )
    second = publish_private_output(
        canonical_dir=full,
        private_root=private,
        run_id="2",
        season=None,
        model_sha="m2",
        runtime_sha="r2",
    )
    assert second["private_delivery_status"] == "PASS"
    assert second["same_occurrence_recovery_upgrade"] is True
    assert json.loads(
        (private / "latest/delivery_status.json").read_text(encoding="utf-8")
    )["delivery_status"] == "READY_FULL"


def test_last_known_good_latest_is_not_overwritten_by_invalid_candidate(tmp_path: Path):
    private = tmp_path / "private"
    valid = _canonical_dir(
        tmp_path / "valid",
        delivery_status="READY_FULL",
        runner_status="PASS",
        stage3_status="PASS",
    )
    publish_private_output(
        canonical_dir=valid,
        private_root=private,
        run_id="lkg-valid",
        season=None,
        model_sha="m1",
        runtime_sha="r1",
    )
    latest_paths = [
        private / "latest/report.json",
        private / "latest/report.md",
        private / "latest/delivery_status.json",
    ]
    before = {path.name: path.read_bytes() for path in latest_paths}

    invalid = _canonical_dir(
        tmp_path / "invalid",
        delivery_status="READY_FULL",
        runner_status="PASS",
        stage3_status="PASS",
    )
    bundle_path = invalid / "report_bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["report"]["sections"] = [
        row for row in bundle["report"]["sections"]
        if row.get("section_id") != "S19"
    ]
    bundle["section_manifest"] = [
        row for row in bundle["section_manifest"]
        if row.get("section_id") != "S19"
    ]
    bundle_path.write_text(
        json.dumps(bundle, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PrivatePublishError, match="REPORT_PRODUCTION_GATE"):
        publish_private_output(
            canonical_dir=invalid,
            private_root=private,
            run_id="lkg-invalid",
            season=None,
            model_sha="m2",
            runtime_sha="r2",
        )

    after = {path.name: path.read_bytes() for path in latest_paths}
    assert after == before


def test_last_known_good_latest_is_not_overwritten_by_privacy_failure(tmp_path: Path):
    private = tmp_path / "private"
    valid = _canonical_dir(
        tmp_path / "privacy-valid",
        delivery_status="READY_FULL",
        runner_status="PASS",
        stage3_status="PASS",
    )
    receipt = publish_private_output(
        canonical_dir=valid,
        private_root=private,
        run_id="privacy-valid",
        season=None,
        model_sha="m1",
        runtime_sha="r1",
    )
    assert receipt["privacy_validation_status"] == "PASS"
    latest_paths = [
        private / "latest/report.json",
        private / "latest/report.md",
        private / "latest/delivery_status.json",
    ]
    before = {path.name: path.read_bytes() for path in latest_paths}

    invalid = _canonical_dir(
        tmp_path / "privacy-invalid",
        delivery_status="READY_FULL",
        runner_status="PASS",
        stage3_status="PASS",
    )
    serving_md = invalid / "serving_report.md"
    serving_md.write_text(
        serving_md.read_text(encoding="utf-8")
        + "\nAuthorization: Bearer abcdefghijklmnopqrstuvwxyz123456\n",
        encoding="utf-8",
    )

    with pytest.raises(PrivatePublishError, match="PRIVACY_VALIDATION"):
        publish_private_output(
            canonical_dir=invalid,
            private_root=private,
            run_id="privacy-invalid",
            season=None,
            model_sha="m2",
            runtime_sha="r2",
        )

    after = {path.name: path.read_bytes() for path in latest_paths}
    assert after == before


def test_integrated_workflow_has_orchestrator_guard_before_runner():
    workflow = Path(".github/workflows/v12-integrated-report-runner.yml").read_text(
        encoding="utf-8"
    )
    guard = workflow.index("Await exact terminal occurrence prefetch")
    runner = workflow.index("Execute occurrence-bound integrated report")
    assert guard < runner
    assert "BLOCKED_UPSTREAM" in workflow
    assert "runner owns a second bounded guard" in workflow


def test_integrated_workflow_keeps_stage3_engineering_nonblocking():
    workflow = Path(".github/workflows/v12-integrated-report-runner.yml").read_text(
        encoding="utf-8"
    )
    assert "Record Stage3 engineering closure evidence" in workflow
    assert "stage3_rc=$?" in workflow
    assert '"engineering_closure_blocks_report": False' in workflow
    assert "REPORT-FIRST: Stage3/P4 engineering closure is observable here" in workflow

    final_gate = workflow.split("Enforce fail-closed human delivery", 1)[1]
    assert "PRIVATE_DELIVERY_STATUS" in final_gate
    assert "PUBLIC_PROOF_OUTCOME" in final_gate
    assert "STAGE3" not in final_gate


def test_degraded_public_proof_remains_operational_only():
    line = build_public_issue_proof(
        analytics_status="DEGRADED",
        report_mode="DEEP",
        report_slot=SLOT,
        run_id="fixture",
        stage3_validation="DEGRADED",
        private_delivery_status="PASS",
        private_receipt_hash="abc123",
    )
    assert "stage3_validation=DEGRADED" in line
    assert "captain" not in line.lower()
    assert "selected_route" not in line.lower()
    assert "current_team" not in line.lower()
    assert scan_public_text(line) == []
