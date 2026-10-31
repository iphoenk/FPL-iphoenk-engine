"""Independent external clock trigger: inactive by construction, bounded, idempotent, fail closed."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from ops import external_clock_gate as gate
from ops import verified_pointer as vp
from ops.render_external_clock import due_report_occurrences, resolve_tick

ROOT = Path(__file__).resolve().parents[1]
CLOCK = yaml.safe_load((ROOT / ".github/workflows/fpl-github-clock.yml").read_text())
CLOCK_TEXT = (ROOT / ".github/workflows/fpl-github-clock.yml").read_text()
FALLBACK_TEXT = (ROOT / ".github/workflows/fpl-external-clock-fallback.yml").read_text()
ORCH_TEXT = (ROOT / ".github/workflows/fpl-master-occurrence-orchestrator.yml").read_text()
ON = CLOCK.get("on") or CLOCK.get(True)
SLOT = "2026-10-25T21:30:00+07:00"
TICK = {"report_mode": "DEEP", "report_slot": SLOT}
EXT = gate.ORIGIN_EXTERNAL
ENABLED = {gate.ENABLE_VARIABLE: "ENABLED"}
TITLE = gate.run_title("DEEP", SLOT)


def _run(status, conclusion="", title=TITLE):
    return {"displayTitle": title, "status": status, "conclusion": conclusion}


# ---- eligibility ----------------------------------------------------------------------------------------------

def test_non_external_origins_are_never_affected():
    for origin in ("", "MANUAL_SMOKE"):
        assert gate.decide(origin, {"report_mode": "NONE"}, None, {})["action"] == "PROCEED"


@pytest.mark.parametrize("value", ["", "true", "enabled", "ENABLED ", "1"])
def test_external_trigger_needs_exactly_enabled(value):
    assert gate.decide(EXT, TICK, [], {gate.ENABLE_VARIABLE: value}) == {
        "action": "SKIP", "reason": "EXTERNAL_CLOCK_DISABLED"}
    assert gate.decide(EXT, TICK, [], {})["reason"] == "EXTERNAL_CLOCK_DISABLED"


def test_external_trigger_only_proceeds_for_a_due_report_never_for_plain_ticks():
    assert gate.decide(EXT, {"report_mode": "NONE", "report_slot": ""}, [], ENABLED)["reason"] == "NO_REPORT_DUE_IN_RESOLVER_WINDOW"
    assert gate.decide(EXT, {"report_mode": "MATCH", "report_slot": SLOT}, [], ENABLED)["action"] == "SKIP"
    assert gate.decide(EXT, TICK, [], ENABLED) == {"action": "PROCEED", "reason": "ELIGIBLE"}


@pytest.mark.parametrize("run,reason", [
    (_run("queued"), "OCCURRENCE_RUN_ACTIVE"),
    (_run("in_progress"), "OCCURRENCE_RUN_ACTIVE"),
    (_run("completed", "success"), "OCCURRENCE_ALREADY_SUCCEEDED"),
    (_run("completed", "failure"), "PRIOR_ATTEMPT_FAILED_NO_AUTOMATIC_RETRY"),
    (_run("completed", "cancelled"), "PRIOR_ATTEMPT_FAILED_NO_AUTOMATIC_RETRY"),
    (_run("completed", "timed_out"), "PRIOR_ATTEMPT_FAILED_NO_AUTOMATIC_RETRY"),
])
def test_any_prior_attempt_of_the_exact_occurrence_blocks_the_external_trigger(run, reason):
    assert gate.decide(EXT, TICK, [run], ENABLED) == {"action": "SKIP", "reason": reason}


def test_other_occurrences_do_not_block_and_unknown_run_state_fails_closed():
    other = _run("completed", "failure", title=gate.run_title("DEEP", "2026-10-25T12:30:00+07:00"))
    assert gate.decide(EXT, TICK, [other], ENABLED)["action"] == "PROCEED"
    assert gate.decide(EXT, TICK, None, ENABLED)["reason"] == "RUN_STATE_UNKNOWN_FAIL_CLOSED"


def test_fallback_guard_blocks_all_prior_exact_slot_attempts_fail_closed():
    """Regression: failed/cancelled runs must never be automatically re-dispatched."""
    assert 'runs_json="$(gh run list' in FALLBACK_TEXT
    assert '--limit 100' in FALLBACK_TEXT
    assert 'if type != "array" then error("invalid run listing")' in FALLBACK_TEXT
    assert 'if [[ "$existing" != "NONE" ]]; then' in FALLBACK_TEXT
    assert 'no automatic retry' in FALLBACK_TEXT
    guard = FALLBACK_TEXT.index('if [[ "$existing" != "NONE" ]]; then')
    dispatch = FALLBACK_TEXT.index('gh workflow run fpl-master-occurrence-orchestrator.yml')
    assert guard < dispatch
    assert '.status == "completed" and .conclusion == "success"' not in FALLBACK_TEXT


def test_run_title_equals_the_orchestrator_run_name_format_and_the_fallback_guard():
    assert "format('FPL {0} occurrence {1} {2}', inputs.scheduler_authority, inputs.report_mode, inputs.report_slot)" in ORCH_TEXT
    assert 'exact_title="FPL EXTERNAL_CLOCK_FALLBACK occurrence $REPORT_MODE $REPORT_SLOT"' in FALLBACK_TEXT
    assert "FPL Master occurrence $REPORT_MODE" not in FALLBACK_TEXT  # the dead pre-fix title


# ---- entry point: no dispatch capability, outage and permission behaviour -------------------------------------

class Proc:
    def __init__(self, rc=0, out="[]"):
        self.returncode, self.stdout = rc, out


def _main(tmp_path, env, run):
    out = tmp_path / "out.txt"
    rc = gate.main({**env, "GITHUB_OUTPUT": str(out), "GITHUB_REPOSITORY": "o/r"}, run)
    return rc, dict(line.split("=", 1) for line in out.read_text().splitlines())


def test_disabled_external_trigger_makes_no_network_call(tmp_path):
    def boom(*a, **k):
        raise AssertionError("gh called while disabled")

    rc, out = _main(tmp_path, {"TRIGGER_ORIGIN": EXT, **TICK_ENV()}, boom)
    assert rc == 0 and out["proceed"] == "false" and out["reason"] == "EXTERNAL_CLOCK_DISABLED"


def TICK_ENV():
    return {"REPORT_MODE": "DEEP", "REPORT_SLOT": SLOT}


@pytest.mark.parametrize("result", [Proc(1, ""), Proc(0, "not json"), Proc(0, "{}")])
def test_run_listing_failure_permission_denied_or_garbage_blocks(tmp_path, result):
    env = {"TRIGGER_ORIGIN": EXT, gate.ENABLE_VARIABLE: "ENABLED", **TICK_ENV()}
    _, out = _main(tmp_path, env, lambda *a, **k: result)
    assert out["proceed"] == "false" and out["reason"] == "RUN_STATE_UNKNOWN_FAIL_CLOSED"


def test_run_listing_timeout_blocks(tmp_path):
    def slow(*a, **k):
        raise subprocess.TimeoutExpired("gh", 60)

    env = {"TRIGGER_ORIGIN": EXT, gate.ENABLE_VARIABLE: "ENABLED", **TICK_ENV()}
    assert _main(tmp_path, env, slow)[1]["proceed"] == "false"


def test_enabled_eligible_trigger_proceeds_and_non_external_is_untouched(tmp_path):
    env = {"TRIGGER_ORIGIN": EXT, gate.ENABLE_VARIABLE: "ENABLED", **TICK_ENV()}
    assert _main(tmp_path, env, lambda *a, **k: Proc(0, "[]"))[1]["proceed"] == "true"
    assert _main(tmp_path, {"TRIGGER_ORIGIN": "", "REPORT_MODE": "NONE"}, None)[1]["proceed"] == "true"


def test_gate_module_has_no_dispatch_or_write_capability():
    text = (ROOT / "ops/external_clock_gate.py").read_text()
    for forbidden in ('"workflow", "run"', "/dispatches", '"issue", "comment"', "requests", "urllib"):
        assert forbidden not in text


# ---- race / duplicate simulation -----------------------------------------------------------------------------

def test_second_trigger_after_the_first_created_the_run_is_skipped_at_every_stage():
    stages = [[_run("queued")], [_run("in_progress")], [_run("completed", "success")]]
    for runs in stages:
        assert gate.decide(EXT, TICK, runs, ENABLED)["action"] == "SKIP"


def test_simultaneous_triggers_are_serialised_by_concurrency_and_receipt_guard():
    # Both reach PROCEED when neither run exists yet; atomicity comes from the serialising groups and the receipt guard.
    assert gate.decide(EXT, TICK, [], ENABLED)["action"] == "PROCEED"
    fallback = yaml.safe_load(FALLBACK_TEXT)
    assert fallback["concurrency"] == {"group": "fpl-external-clock-${{ inputs.logical_slot }}", "cancel-in-progress": False}
    orch = yaml.safe_load(ORCH_TEXT)
    assert orch["concurrency"] == {"group": "fpl-master-occurrence-orchestrator", "cancel-in-progress": False}
    assert "FPL_MASTER_RECEIPT occurrence_id=${OCCURRENCE_ID} status=READY_FULL" in ORCH_TEXT  # second run skips


# ---- workflow wiring: schedule unchanged, inactive by construction, permissions unchanged --------------------

def test_github_schedule_is_unchanged_and_default_dispatch_is_not_external():
    assert ON["schedule"] == [{"cron": "35 * * * *"}]
    inputs = ON["workflow_dispatch"]["inputs"]
    assert inputs["trigger_origin"]["default"] == "MANUAL_SMOKE"
    assert inputs["trigger_origin"]["options"] == ["MANUAL_SMOKE", "EXTERNAL_INDEPENDENT_CLOCK"]


def test_external_origin_is_blocked_at_job_level_without_the_repository_variable():
    cond = CLOCK["jobs"]["tick"]["if"]
    assert "inputs.trigger_origin != 'EXTERNAL_INDEPENDENT_CLOCK' || vars.FPL_EXTERNAL_CLOCK == 'ENABLED'" in cond
    assert "github.event_name == 'schedule'" in cond


def test_external_origin_never_reaches_audit_or_recovery_jobs():
    assert "inputs.trigger_origin != 'EXTERNAL_INDEPENDENT_CLOCK'" in CLOCK["jobs"]["missed-slot-audit"]["if"]
    assert CLOCK["jobs"]["recovery-dispatch"]["needs"] == "missed-slot-audit"


def test_dispatch_steps_fail_closed_for_external_and_unchanged_for_schedule():
    steps = {s.get("id") or s.get("name") or s["uses"]: s for s in CLOCK["jobs"]["tick"]["steps"]}
    guard = "steps.external.outputs.proceed == 'true' || inputs.trigger_origin != 'EXTERNAL_INDEPENDENT_CLOCK'"
    assert guard in steps["child"]["if"]
    assert guard in steps["Wait for exact fallback child"]["if"]
    announce = steps["Announce external trigger provenance before any dispatch"]
    names = [s.get("id") or s.get("name") or s["uses"] for s in CLOCK["jobs"]["tick"]["steps"]]
    assert names.index(announce["name"]) < names.index("child")  # announced before dispatch
    assert "gh issue comment 431" in announce["run"]
    assert steps["external"]["continue-on-error"] is True


def test_no_new_permissions_and_no_new_secret_in_the_clock_workflow():
    assert CLOCK["permissions"] == {"contents": "read", "actions": "write", "issues": "write"}
    assert sorted(set(re.findall(r"secrets\.(\w+)", CLOCK_TEXT))) == ["FPL_PRIVATE_REPORTS_TOKEN"]
    assert "EXTERNAL_INDEPENDENT_CLOCK" in CLOCK_TEXT and "schedule_origin=$origin" in CLOCK_TEXT


# ---- provenance ----------------------------------------------------------------------------------------------

def test_announcement_marks_external_origin_and_never_natural():
    text = gate.announcement(TICK, external_trigger_id="5,20@2026-10-25T14:35:00.000Z", actor="fpl-clock-bot")
    assert text.startswith("FPL_EXTERNAL_CLOCK_TRIGGER | label=EXTERNAL_INDEPENDENT_CLOCK")
    assert f"occurrence_id=DEEP|{SLOT} |" in text and "natural_proof=false" in text and "github_scheduled_natural=false" in text


def test_pointer_origin_external_precedence_and_exact_occurrence_match():
    oid = f"DEEP|{SLOT}"
    ann = gate.announcement(TICK, external_trigger_id="x", actor="a")
    assert vp.external_clock_announced([ann], oid)
    assert not vp.external_clock_announced([ann], "DEEP|2026-10-25T12:30:00+07:00")
    assert not vp.external_clock_announced(["FPL_GITHUB_CLOCK | schedule_origin=GITHUB_NATIVE_OPERATIONAL_SCHEDULE"], oid)


# ---- production-equivalent dry run (no dispatch) --------------------------------------------------------------

def _cron_matches(spec: str, when: datetime) -> bool:
    minute, hour, *_ = spec.split()
    ok = lambda field, value: value in {int(x) for x in field.split(",")}
    return ok(minute, when.minute) and ok(hour, when.hour)


def test_worker_schedule_gives_every_slot_at_least_four_in_window_pings_through_dst_changes():
    spec = tomllib.loads((ROOT / "deploy/external-clock/wrangler.toml").read_text())["triggers"]["crons"]
    assert len(spec) == 1  # one cron trigger of the 5 available on the free plan
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    seen = {}
    for day in range(0, 270, 1):
        for occ in due_report_occurrences(start + timedelta(days=day, hours=12), lookback_hours=36):
            seen[(occ["report_mode"], occ["report_slot"])] = occ
    assert len(seen) > 600
    for (mode, slot), _ in seen.items():
        s = datetime.fromisoformat(slot).astimezone(timezone.utc)
        pings = [s + timedelta(minutes=m) for m in range(-5, 61) if _cron_matches(spec[0], s + timedelta(minutes=m))]
        assert len(pings) >= 4, (mode, slot, len(pings))
        for p in pings:  # every ping resolves to exactly this occurrence (production resolver)
            tick = resolve_tick(p)
            assert (tick["report_mode"], tick["report_slot"]) == (mode, slot)


def test_pings_outside_report_windows_are_skipped_by_the_gate_so_no_work_is_created():
    spec = tomllib.loads((ROOT / "deploy/external-clock/wrangler.toml").read_text())["triggers"]["crons"][0]
    day = datetime(2026, 10, 26, tzinfo=timezone.utc)
    outside = 0
    for m in range(24 * 60):
        t = day + timedelta(minutes=m)
        if _cron_matches(spec, t) and resolve_tick(t)["report_mode"] == "NONE":
            outside += 1
            assert gate.decide(EXT, resolve_tick(t), [], ENABLED)["action"] == "SKIP"
    assert outside > 0  # the cron has pings outside report windows; each is skipped


# ---- reference worker (node, mocked fetch; no network) --------------------------------------------------------

NODE_TEST = r"""
import { trigger } from "./deploy/external-clock/worker.js";
const ev = { cron: "5,20,35,50 21 * * *", scheduledTime: 1792939000000 };
const calls = [];
const ok = async (u, o) => { calls.push([u, o]); return { status: 204 }; };
const out = {};
out.disabled = await trigger({ GITHUB_TOKEN: "t", EXTERNAL_CLOCK_ENABLED: "false" }, ev, ok);
out.nocred = await trigger({ EXTERNAL_CLOCK_ENABLED: "true" }, ev, ok);
out.noCallsYet = calls.length;
out.ok = await trigger({ GITHUB_TOKEN: "t", EXTERNAL_CLOCK_ENABLED: "true" }, ev, ok);
out.body = JSON.parse(calls[0][1].body);
out.url = calls[0][0];
out.rejected = await trigger({ GITHUB_TOKEN: "t", EXTERNAL_CLOCK_ENABLED: "true" }, ev, async () => ({ status: 403 }));
out.network = await trigger({ GITHUB_TOKEN: "t", EXTERNAL_CLOCK_ENABLED: "true" }, ev, async () => { throw new Error("down"); });
out.timeout = await trigger({ GITHUB_TOKEN: "t", EXTERNAL_CLOCK_ENABLED: "true" }, ev,
  (u, o) => new Promise((_, rej) => o.signal.addEventListener("abort", () => rej(Object.assign(new Error("a"), { name: "AbortError" })))));
out.attempts = calls.length;
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
def test_reference_worker_is_inactive_by_default_bounded_and_fail_closed(tmp_path):
    script = tmp_path / "t.mjs"
    script.write_text(NODE_TEST.replace("./deploy", str(ROOT / "deploy")))
    proc = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["disabled"] == {"action": "DISABLED"} and out["nocred"] == {"action": "NO_CREDENTIAL"}
    assert out["noCallsYet"] == 0 and out["attempts"] == 1  # no call while disabled; exactly one attempt per invocation
    assert out["ok"] == {"action": "DISPATCHED", "status": 204}
    assert out["rejected"] == {"action": "REJECTED", "status": 403}
    assert out["network"] == {"action": "ERROR", "error": "NETWORK"}
    assert out["timeout"] == {"action": "ERROR", "error": "TIMEOUT"}
    assert out["url"].endswith("/repos/iphoenk/FPL-iphoenk-engine/actions/workflows/fpl-github-clock.yml/dispatches")
    assert out["body"]["ref"] == "main"
    assert out["body"]["inputs"]["trigger_origin"] == "EXTERNAL_INDEPENDENT_CLOCK"


def test_deploy_config_is_inactive_and_secret_free():
    cfg = tomllib.loads((ROOT / "deploy/external-clock/wrangler.toml").read_text())
    assert cfg["vars"]["EXTERNAL_CLOCK_ENABLED"] == "false"
    blob = (ROOT / "deploy/external-clock/worker.js").read_text() + (ROOT / "deploy/external-clock/wrangler.toml").read_text()
    assert not re.search(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_", blob)
