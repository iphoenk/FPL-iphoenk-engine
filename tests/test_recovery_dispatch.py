"""Recovery dispatch is prepared but disabled; when enabled it is bounded and idempotent."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ops import recovery_dispatch as rd
from ops import recovery_plan as rp

SLOT = "2026-10-25T12:30:00+07:00"
OID = f"DEEP|{SLOT}"
CAND = {
    "occurrence_id": OID, "report_mode": "DEEP", "report_slot": SLOT, "overdue_minutes": 110.0,
    "decision": rp.ELIGIBLE, "idempotency_key": f"RECOVERY|{OID}", "label": "RECOVERY",
    "natural_acceptance_eligible": False,
}
PLAN = {"dispatch_enabled": False, "eligible": [CAND]}
WORKFLOW = Path(".github/workflows/fpl-github-clock.yml")


class Proc:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout = rc, out


class Recorder:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        return Proc(1 if self.fail_on and self.fail_on in argv else 0)


def test_variable_must_be_exactly_enabled():
    for value in ("", "true", "enabled", "ENABLED ", "1"):
        assert not rd.enabled({rd.ENABLE_VARIABLE: value})
    assert not rd.enabled({})
    assert rd.enabled({rd.ENABLE_VARIABLE: "ENABLED"})


def test_disabled_entry_point_makes_no_call_and_reads_nothing(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("network/subprocess used while disabled")

    monkeypatch.setattr(rd.subprocess, "run", boom)
    rc = rd.main(["--audit", str(tmp_path / "does-not-exist.json")], environ={})
    assert rc == 0 and json.loads(capsys.readouterr().out)["action"] == "DISABLED"


def test_enabled_dispatch_announces_first_then_dispatches_exact_command_once():
    rec = Recorder()
    out = rd.execute(PLAN, [], "o/r", run=rec)
    assert out == {"action": "DISPATCHED_RECOVERY", "occurrence_id": OID}
    assert [c[1] for c in rec.calls] == ["issue", "workflow"]  # evidence before dispatch
    comment = rec.calls[0][-1]
    assert "label=RECOVERY" in comment and "natural_proof=false" in comment and f"idempotency_key=RECOVERY|{OID}" in comment
    assert rec.calls[1] == [
        "gh", "workflow", "run", rd.ORCHESTRATOR, "--repo", "o/r", "--ref", "main",
        "-f", "report_mode=DEEP", "-f", f"report_slot={SLOT}", "-f", "checkpoint_time=12:30",
        "-f", "scheduler_authority=EXTERNAL_CLOCK_FALLBACK",
    ]


@pytest.mark.parametrize("conclusion", ["success", "failure", "cancelled", None])
def test_any_prior_run_for_the_exact_occurrence_blocks_dispatch_including_failed(conclusion):
    rec = Recorder()
    runs = [{"displayTitle": rd.run_title(CAND), "conclusion": conclusion}]
    assert rd.execute(PLAN, runs, "o/r", run=rec)["action"] == "SKIPPED_ALREADY_ATTEMPTED"
    assert rec.calls == []


def test_other_occurrences_runs_do_not_block():
    other = {"displayTitle": "FPL EXTERNAL_CLOCK_FALLBACK occurrence DEEP 2026-10-25T04:30:00+07:00"}
    assert rd.execute(PLAN, [other], "o/r", run=Recorder())["action"] == "DISPATCHED_RECOVERY"


def test_evidence_failure_prevents_dispatch_and_dispatch_failure_is_reported():
    rec = Recorder(fail_on="comment")
    assert rd.execute(PLAN, [], "o/r", run=rec)["action"] == "NOT_DISPATCHED_EVIDENCE_COMMENT_FAILED"
    assert all(c[1] != "workflow" for c in rec.calls)
    assert rd.execute(PLAN, [], "o/r", run=Recorder(fail_on="workflow"))["action"] == "DISPATCH_FAILED"


def test_only_wellformed_advisory_candidates_are_selected_and_at_most_one():
    assert rd.execute({"dispatch_enabled": False, "eligible": []}, [], "o/r", run=Recorder())["action"] == "NO_ELIGIBLE_CANDIDATE"
    for bad in (
        {**CAND, "decision": rp.HISTORICAL},
        {**CAND, "label": "NATURAL"},
        {**CAND, "idempotency_key": "other"},
        {**CAND, "natural_acceptance_eligible": True},
    ):
        assert rd.select({"dispatch_enabled": False, "eligible": [bad]}) is None
    assert rd.select({"dispatch_enabled": True, "eligible": [CAND]}) is None  # not the advisory artifact
    newer = {**CAND, "occurrence_id": "PRICE|2026-10-25T05:30:00+07:00", "report_mode": "PRICE",
             "report_slot": "2026-10-25T13:30:00+07:00", "idempotency_key": "RECOVERY|PRICE|2026-10-25T05:30:00+07:00"}
    chosen = rd.select({"dispatch_enabled": False, "eligible": [CAND, newer]})
    assert chosen["report_slot"] == "2026-10-25T13:30:00+07:00"  # exactly one, never a batch


def test_enabled_main_reports_errors_without_raising(tmp_path, capsys):
    rc = rd.main(["--audit", str(tmp_path / "missing.json")], environ={rd.ENABLE_VARIABLE: "ENABLED"})
    assert rc == 0 and json.loads(capsys.readouterr().out)["action"] == "NOT_DISPATCHED_ERROR"


def test_workflow_job_is_gated_serialized_and_leaves_the_tick_job_untouched():
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = spec["jobs"]["recovery-dispatch"]
    assert "vars.FPL_RECOVERY_DISPATCH == 'ENABLED'" in job["if"]
    assert job["needs"] == "missed-slot-audit"
    assert job["concurrency"] == {"group": "fpl-recovery-dispatch", "cancel-in-progress": False}
    assert job["permissions"] == {"contents": "read", "actions": "write", "issues": "write"}
    # the audit job stays read-only and the tick job never references recovery
    assert spec["jobs"]["missed-slot-audit"]["permissions"] == {"contents": "read", "actions": "read"}
    assert "recovery" not in json.dumps(spec["jobs"]["tick"]).lower()
    # no other scheduler: still exactly the existing hourly cron
    assert spec[True]["schedule"] == [{"cron": "35 * * * *"}]


def test_module_does_not_import_a_scheduler_or_other_dispatch_surface():
    source = Path(rd.__file__).read_text(encoding="utf-8")
    assert "cron" not in source and "schedule:" not in source
