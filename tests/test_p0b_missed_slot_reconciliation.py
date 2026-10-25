"""P0-B: bounded missed-slot detection, five-state classification, private
readback verification independent of workflow success, and resolver/downstream
window reconciliation. Audit only: nothing here may dispatch or back-fill."""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ops import audit_due_occurrences as aud
from ops.occurrence_reconciliation import (
    ACTIVE,
    FAILED,
    MISSING,
    STATES,
    UNKNOWN,
    VERIFIED_PUBLISHED,
    build_audit_record,
    classify_due_occurrences,
    occurrence_id,
)
from ops.render_external_clock import (
    DOWNSTREAM_WINDOW_MINUTES,
    RESOLVER_WINDOW_MINUTES,
    due_report_occurrences,
    resolve_tick,
)

WIB = ZoneInfo("Asia/Jakarta")
ROOT = Path(__file__).resolve().parents[1]


def at(*args):
    return datetime(*args, tzinfo=WIB)


# ---------------- due-slot enumeration (reused from PR 1172, extended) ----


def test_delayed_clock_enumerates_multiple_due_deep_slots():
    rows = due_report_occurrences(at(2026, 10, 25, 23, 12), 24)
    deep = [r["checkpoint_time"] for r in rows if r["report_mode"] == "DEEP"]
    assert deep == ["04:30", "12:30", "21:30"]
    assert len({(r["report_mode"], r["report_slot"]) for r in rows}) == len(rows)


@pytest.mark.parametrize(
    "when,expected",
    [
        (at(2026, 10, 25, 6, 45), "05:30"),   # BST still in force (ends 01:00 UTC 25 Oct)
        (at(2026, 10, 26, 7, 15), "06:30"),   # GMT after the autumn transition
        (at(2026, 3, 28, 7, 15), "06:30"),    # GMT before the spring transition
        (at(2026, 3, 30, 6, 45), "05:30"),    # BST after the spring transition
    ],
)
def test_price_slot_tracks_london_dst_transitions(when, expected):
    rows = due_report_occurrences(when, 3)
    assert [r["checkpoint_time"] for r in rows if r["report_mode"] == "PRICE"] == [expected]


def test_future_occurrences_are_never_emitted():
    rows = due_report_occurrences(at(2026, 10, 25, 11, 0), 2)
    assert not any(r["checkpoint_time"] == "12:30" for r in rows)


@pytest.mark.parametrize("hours", [0, 73])
def test_lookback_is_bounded(hours):
    with pytest.raises(ValueError):
        due_report_occurrences(at(2026, 10, 25, 12, 0), hours)


def test_naive_time_rejected():
    with pytest.raises(ValueError):
        due_report_occurrences(datetime(2026, 10, 25, 12, 0))


def test_slots_use_wib_iso_identity():
    for row in due_report_occurrences(at(2026, 10, 25, 23, 12), 36):
        assert row["report_slot"].endswith("+07:00")
        assert occurrence_id(row["report_mode"], row["report_slot"]) == f'{row["report_mode"]}|{row["report_slot"]}'


# ---------------- resolver vs downstream window reconciliation -----------


def test_resolver_window_is_subset_of_downstream_window():
    assert RESOLVER_WINDOW_MINUTES[0] >= DOWNSTREAM_WINDOW_MINUTES[0]
    assert RESOLVER_WINDOW_MINUTES[1] <= DOWNSTREAM_WINDOW_MINUTES[1]


def test_downstream_constant_matches_fallback_workflow_literal():
    text = (ROOT / ".github/workflows/fpl-external-clock-fallback.yml").read_text(encoding="utf-8")
    match = re.search(
        r"timedelta\(minutes=(-?\d+)\) <= report_delta <= timedelta\(minutes=(\d+)\)", text
    )
    assert match, "downstream report-window literal not found"
    assert (int(match.group(1)), int(match.group(2))) == DOWNSTREAM_WINDOW_MINUTES


def test_resolver_behaviour_unchanged_at_window_edges():
    slot = at(2026, 10, 25, 12, 30)
    assert resolve_tick(slot + timedelta(minutes=60))["report_slot"] == slot.isoformat()
    assert resolve_tick(slot + timedelta(minutes=61))["report_mode"] == "NONE"
    assert resolve_tick(slot - timedelta(minutes=5))["report_slot"] == slot.isoformat()


# ---------------- five-state classification --------------------------------

NOW = at(2026, 10, 25, 13, 45)


def _slot(mode, hhmm):
    for row in due_report_occurrences(NOW, 12):
        if row["report_mode"] == mode and row["checkpoint_time"] == hhmm:
            return row
    raise AssertionError((mode, hhmm))


def _ok(row):
    return {
        "terminality": "READY_FULL",
        "failures": [],
        "report_mode": row["report_mode"],
        "report_slot": row["report_slot"],
    }


def _state(rows, row):
    oid = occurrence_id(row["report_mode"], row["report_slot"])
    return next(r for r in rows if r["occurrence_id"] == oid)


def test_all_five_states_and_precedence():
    deep = _slot("DEEP", "12:30")        # 75 min old at NOW -> past grace
    older = _slot("DEEP", "04:30")
    oid = lambda r: occurrence_id(r["report_mode"], r["report_slot"])  # noqa: E731
    rows = classify_due_occurrences(
        NOW,
        verified={oid(older): _ok(older)},
        active=set(),
        failed=set(),
        lookback_hours=12,
    )
    assert _state(rows, older)["state"] == VERIFIED_PUBLISHED
    assert _state(rows, deep)["state"] == MISSING

    rows = classify_due_occurrences(NOW, verified={}, active={oid(deep)}, failed={oid(deep)}, lookback_hours=12)
    assert _state(rows, deep)["state"] == ACTIVE          # active beats failed

    rows = classify_due_occurrences(NOW, verified={}, failed={oid(deep)}, lookback_hours=12)
    assert _state(rows, deep)["state"] == FAILED

    rows = classify_due_occurrences(NOW, verified={}, unknown={oid(deep): "RUNS_API:x"}, lookback_hours=12)
    assert _state(rows, deep)["state"] == UNKNOWN
    assert set(STATES) == {VERIFIED_PUBLISHED, ACTIVE, FAILED, MISSING, UNKNOWN}


def test_ontime_slot_inside_pipeline_window_is_unknown_not_missing():
    now = at(2026, 10, 25, 12, 36)  # nominal HH:35 tick, nothing published yet
    rows = classify_due_occurrences(now, verified={}, lookback_hours=12)
    row = next(r for r in rows if r["checkpoint_time"] == "12:30")
    assert (row["state"], row["reason"]) == (UNKNOWN, "WITHIN_PIPELINE_WINDOW")


def test_skipped_tick_becomes_missing_after_grace():
    now = at(2026, 10, 25, 13, 45)
    rows = classify_due_occurrences(now, verified={}, lookback_hours=12)
    row = next(r for r in rows if r["checkpoint_time"] == "12:30")
    assert row["state"] == MISSING


def test_workflow_success_is_not_publication_evidence():
    # classify_due_occurrences has no input for "workflow succeeded": a green
    # run with no private verification must remain MISSING.
    deep = _slot("DEEP", "12:30")
    assert _state(classify_due_occurrences(NOW, verified={}), deep)["state"] == MISSING


@pytest.mark.parametrize(
    "result",
    [
        {"terminality": "FAILED_VERIFY", "failures": ["BODY_DIGEST_MISMATCH"]},
        {"terminality": "READY_FULL", "failures": ["EXACT_SLOT_MISMATCH"]},
        {"terminality": "READY_FULL", "failures": []},  # bound to other slot
        {"terminality": "", "failures": []},
    ],
)
def test_partial_or_invalid_publication_is_failed(result):
    deep = _slot("DEEP", "12:30")
    bound = {**result, "report_mode": "DEEP", "report_slot": deep["report_slot"]}
    if result == {"terminality": "READY_FULL", "failures": []}:
        bound["report_slot"] = _slot("DEEP", "04:30")["report_slot"]
    rows = classify_due_occurrences(NOW, verified={occurrence_id("DEEP", deep["report_slot"]): bound})
    assert _state(rows, deep)["state"] == FAILED


def test_verified_beats_failed_and_active_and_unknown():
    deep = _slot("DEEP", "12:30")
    oid = occurrence_id("DEEP", deep["report_slot"])
    rows = classify_due_occurrences(
        NOW, verified={oid: _ok(deep)}, active={oid}, failed={oid}, unknown={oid: "x"}
    )
    assert _state(rows, deep)["state"] == VERIFIED_PUBLISHED


def test_duplicate_evidence_does_not_duplicate_rows():
    deep = _slot("DEEP", "12:30")
    oid = occurrence_id("DEEP", deep["report_slot"])
    rows = classify_due_occurrences(NOW, verified={}, active=[oid, oid, oid])
    assert [r["occurrence_id"] for r in rows].count(oid) == 1


def test_audit_record_never_claims_execution_or_dispatch():
    rows = classify_due_occurrences(NOW, verified={})
    record = build_audit_record(NOW, rows, 36)
    assert record["natural_execution_created"] is False
    assert record["natural_acceptance_eligible"] is False
    assert record["historical_dispatch"] is False and record["backfill"] is False
    assert record["all_due_verified"] is False
    assert sum(record["counts"].values()) == len(rows)


def test_concurrent_classification_is_deterministic():
    deep = _slot("DEEP", "12:30")
    oid = occurrence_id("DEEP", deep["report_slot"])

    def run(i):
        rows = classify_due_occurrences(NOW, verified={oid: _ok(deep)} if i % 2 else {})
        return _state(rows, deep)["state"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        states = list(pool.map(run, range(64)))
    assert states == [VERIFIED_PUBLISHED if i % 2 else MISSING for i in range(64)]


# ---------------- private readback verification ----------------------------


class FakeReader:
    def __init__(self, files, fail=()):
        self.files, self.fail = dict(files), set(fail)

    def read_bytes(self, path):
        if any(path.startswith(p) for p in self.fail):
            raise aud.ReadError("API_DOWN")
        if path not in self.files:
            raise aud.NotFound(path)
        return self.files[path]

    def list_dir(self, path):
        if any(path.startswith(p) for p in self.fail):
            raise aud.ReadError("API_DOWN")
        prefix = path.rstrip("/") + "/"
        names = {k[len(prefix):].split("/", 1)[0] for k in self.files if k.startswith(prefix)}
        if not names:
            raise aud.NotFound(path)
        return sorted(names)


def _j(obj):
    return (json.dumps(obj, sort_keys=True) + "\n").encode()


def private_files(mode, slot, *, gw=7, latest_slot=None, body=b"# report\n", status="READY_FULL"):
    sha = hashlib.sha256(body).hexdigest()
    oid = occurrence_id(mode, slot)
    d = f"reports/{aud.season_for(slot)}/gw_{gw}/{aud.slot_token(slot)}"
    bundle = b'{"bundle": true}\n'
    stage3_bytes = _j({"status": "PASS"})
    digest = {
        "section_ids": [f"S{i:02d}" for i in range(1, 4)] if mode == "DEEP" else [f"{mode}{i}" for i in range(1, 4)],
        "canonical_bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "report_mode": mode,
        "report_slot": slot,
        "occurrence_id": oid,
        "runner_status": "PASS",
        "pre_render_status": "PASS",
        "post_render_status": "PASS",
        "human_facing_status": "PASS",
        "canonical_body_sha256": sha,
        "delivery_status": status,
    }
    receipt = {
        "private_delivery_status": "PASS",
        "serving_snapshot_published": True,
        "canonical_body_sha256": sha,
        "report_slot": slot,
        "report_mode": mode,
        "privacy_validation_status": "PASS",
    }
    body_name = "serving_report.md" if mode == "DEEP" else "report_body.md"
    files = {
        f"{d}/digest.json": _j(digest),
        f"{d}/delivery_receipt.json": _j(receipt),
        f"{d}/stage3_acceptance.json": stage3_bytes,
        f"{d}/report_bundle.json": bundle,
        f"{d}/execution_proof_private.json": _j(
            {"canonical_stage3_acceptance_sha256": hashlib.sha256(stage3_bytes).hexdigest()}
        ),
        f"{d}/{body_name}": body,
    }
    if mode == "DEEP":
        files[f"{d}/delivery_status.json"] = _j({"delivery_status": status, "root_failure": ""})
        files["latest/report.md"] = body
    latest_digest = dict(digest)
    if latest_slot:
        latest_digest.update(report_slot=latest_slot, occurrence_id=occurrence_id(mode, latest_slot))
    files[f"latest/{aud._SERVING[mode]}"] = _j(latest_digest)
    return files


DEEP_SLOT = "2026-10-25T12:30:00+07:00"
PRICE_SLOT = "2026-10-25T05:30:00+07:00"


@pytest.mark.parametrize("mode,slot", [("DEEP", DEEP_SLOT), ("PRICE", PRICE_SLOT)])
def test_exact_private_publication_verifies(mode, slot):
    outcome, result = aud.verify_occurrence(FakeReader(private_files(mode, slot)), mode, slot)
    assert outcome == "VERIFIED"
    assert result["terminality"] == "READY_FULL" and not result["failures"]


def test_pointer_superseded_by_later_occurrence_still_verifies_but_stale_pointer_fails():
    later = "2026-10-25T21:30:00+07:00"
    ok = FakeReader(private_files("DEEP", DEEP_SLOT, latest_slot=later))
    assert aud.verify_occurrence(ok, "DEEP", DEEP_SLOT)[1]["terminality"] == "READY_FULL"
    stale = FakeReader(private_files("DEEP", DEEP_SLOT, latest_slot="2026-10-25T04:30:00+07:00"))
    result = aud.verify_occurrence(stale, "DEEP", DEEP_SLOT)[1]
    assert "LATEST_ADVANCEMENT_INVALID" in result["failures"]


def test_tampered_body_hash_mismatch_is_rejected():
    files = private_files("PRICE", PRICE_SLOT)
    d = f"reports/{aud.season_for(PRICE_SLOT)}/gw_7/{aud.slot_token(PRICE_SLOT)}"
    files[f"{d}/report_body.md"] = b"tampered\n"
    result = aud.verify_occurrence(FakeReader(files), "PRICE", PRICE_SLOT)[1]
    assert result["terminality"] == "FAILED_VERIFY" and "BODY_DIGEST_MISMATCH" in result["failures"]


def test_receipt_for_other_slot_is_rejected():
    files = private_files("PRICE", PRICE_SLOT)
    d = f"reports/{aud.season_for(PRICE_SLOT)}/gw_7/{aud.slot_token(PRICE_SLOT)}"
    receipt = json.loads(files[f"{d}/delivery_receipt.json"])
    receipt["report_slot"] = "2026-10-24T05:30:00+07:00"
    files[f"{d}/delivery_receipt.json"] = _j(receipt)
    result = aud.verify_occurrence(FakeReader(files), "PRICE", PRICE_SLOT)[1]
    assert "HISTORICAL_RECEIPT_SLOT_MISMATCH" in result["failures"]


def test_privacy_violation_is_rejected():
    files = private_files("PRICE", PRICE_SLOT)
    d = f"reports/{aud.season_for(PRICE_SLOT)}/gw_7/{aud.slot_token(PRICE_SLOT)}"
    receipt = json.loads(files[f"{d}/delivery_receipt.json"])
    receipt["privacy_validation_status"] = "FAIL"
    files[f"{d}/delivery_receipt.json"] = _j(receipt)
    assert "PRIVACY_BOUNDARY_VIOLATION" in aud.verify_occurrence(FakeReader(files), "PRICE", PRICE_SLOT)[1]["failures"]


def test_missing_receipt_is_not_found_and_api_failure_is_error_not_absence():
    files = private_files("PRICE", PRICE_SLOT)
    d = f"reports/{aud.season_for(PRICE_SLOT)}/gw_7/{aud.slot_token(PRICE_SLOT)}"
    del files[f"{d}/delivery_receipt.json"]
    assert aud.verify_occurrence(FakeReader(files), "PRICE", PRICE_SLOT)[0] == "NOT_FOUND"
    assert aud.verify_occurrence(FakeReader({}), "PRICE", PRICE_SLOT)[0] == "NOT_FOUND"
    down = FakeReader(private_files("PRICE", PRICE_SLOT), fail=("reports/",))
    assert aud.verify_occurrence(down, "PRICE", PRICE_SLOT)[0] == "ERROR"


def test_invalid_json_is_error_not_verified():
    files = private_files("PRICE", PRICE_SLOT)
    d = f"reports/{aud.season_for(PRICE_SLOT)}/gw_7/{aud.slot_token(PRICE_SLOT)}"
    files[f"{d}/digest.json"] = b"{not json"
    assert aud.verify_occurrence(FakeReader(files), "PRICE", PRICE_SLOT)[0] == "ERROR"


def _dir(mode, slot, gw=7):
    return f"reports/{aud.season_for(slot)}/gw_{gw}/{aud.slot_token(slot)}"


def test_stage3_file_from_another_occurrence_is_rejected_by_hash_binding():
    files = private_files("DEEP", DEEP_SLOT)
    files[f"{_dir('DEEP', DEEP_SLOT)}/stage3_acceptance.json"] = _j({"status": "PASS", "other": 1})
    result = aud.verify_occurrence(FakeReader(files), "DEEP", DEEP_SLOT)[1]
    assert result["terminality"] == "FAILED_VERIFY" and "STAGE3_BINDING_MISMATCH" in result["failures"]


def test_bundle_not_matching_digest_is_rejected():
    files = private_files("DEEP", DEEP_SLOT)
    files[f"{_dir('DEEP', DEEP_SLOT)}/report_bundle.json"] = b'{"bundle": "other"}\n'
    result = aud.verify_occurrence(FakeReader(files), "DEEP", DEEP_SLOT)[1]
    assert "BUNDLE_DIGEST_BINDING_MISMATCH" in result["failures"]


def test_deep_digest_with_match_section_ids_is_the_p0c_contamination_signature():
    files = private_files("DEEP", DEEP_SLOT)
    path = f"{_dir('DEEP', DEEP_SLOT)}/digest.json"
    digest = json.loads(files[path])
    digest["section_ids"] = ["S01", "MATCH1", "MATCH2"]
    files[path] = _j(digest)
    files["latest/deep.json"] = _j(digest)
    result = aud.verify_occurrence(FakeReader(files), "DEEP", DEEP_SLOT)[1]
    assert "SECTION_CATALOG_FAMILY_MISMATCH" in result["failures"]
    assert result["terminality"] == "FAILED_VERIFY"


def test_occurrence_found_in_previous_gw_directory():
    files = private_files("DEEP", DEEP_SLOT, gw=6)
    files.update({"reports/2026-27/gw_7/placeholder/x": b"1"})
    assert aud.verify_occurrence(FakeReader(files), "DEEP", DEEP_SLOT)[0] == "VERIFIED"


# ---------------- orchestrator runs ---------------------------------------


def test_runs_classification_ignores_success_and_foreign_titles():
    runs = [
        {"display_title": f"FPL EXTERNAL_CLOCK_FALLBACK occurrence DEEP {DEEP_SLOT}", "status": "in_progress", "conclusion": None},
        {"display_title": f"FPL OWNER_CONTROLLED occurrence PRICE {PRICE_SLOT}", "status": "completed", "conclusion": "failure"},
        {"display_title": "FPL OWNER_CONTROLLED occurrence DEEP 2026-10-25T04:30:00+07:00", "status": "completed", "conclusion": "success"},
        {"display_title": "FPL Master occurrence comment 123", "status": "queued", "conclusion": None},
    ]
    active, failed = aud.classify_runs(runs)
    assert active == {f"DEEP|{DEEP_SLOT}"}
    assert failed == {f"PRICE|{PRICE_SLOT}"}


# ---------------- end-to-end audit with injected evidence ------------------


def test_end_to_end_audit_with_runs_api_failure_marks_unresolved_unknown():
    now = at(2026, 10, 25, 13, 45)
    reader = FakeReader(private_files("DEEP", DEEP_SLOT))

    def boom():
        raise aud.ReadError("RUNS_API_FAILED")

    record = aud.audit(now, reader, boom, 12)
    by_id = {r["occurrence_id"]: r for r in record["rows"]}
    assert by_id[f"DEEP|{DEEP_SLOT}"]["state"] == VERIFIED_PUBLISHED
    unresolved = [r for r in record["rows"] if r["state"] != VERIFIED_PUBLISHED]
    assert all(r["state"] == UNKNOWN and "RUNS_API" in r["reason"] for r in unresolved)
    assert record["natural_execution_created"] is False


def test_end_to_end_audit_reports_missing_skipped_slot():
    now = at(2026, 10, 25, 13, 45)
    record = aud.audit(now, FakeReader({}), lambda: [], 12)
    states = {r["occurrence_id"]: r["state"] for r in record["rows"]}
    assert states[f"DEEP|{DEEP_SLOT}"] == MISSING


def test_cli_never_breaks_the_clock_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("FPL_PRIVATE_REPORTS_TOKEN", raising=False)
    out = tmp_path / "audit.json"
    assert aud.main(["--output", str(out), "--lookback-hours", "24"]) == 0
    data = json.loads(out.read_text())
    assert data["historical_dispatch"] is False
    assert all(r["state"] == UNKNOWN for r in data["rows"])


# ---------------- gh-backed adapters (no network) --------------------------


class _Proc:
    def __init__(self, rc=0, out=b"", err=b""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_gh_reader_uses_raw_media_type_maps_errors_and_never_leaks_token():
    secret = "ghp_SECRET_TOKEN_VALUE"
    calls = []

    def run(cmd, env=None, **kw):
        calls.append((cmd, env["GH_TOKEN"]))
        path = cmd[-1]
        if "missing" in path:
            return _Proc(1, b"", b"gh: Not Found (HTTP 404)")
        if "boom" in path:
            return _Proc(1, b"", b"gh: Server Error (HTTP 502)")
        if "empty" in path:
            return _Proc(0, b"")
        if "--jq" in cmd:
            return _Proc(0, b"gw_7\ngw_8\n")
        return _Proc(0, b"\x00raw\xffbytes")

    reader = aud.GhReader(secret, run=run)
    assert reader.read_bytes("a/ok") == b"\x00raw\xffbytes"  # binary-safe, no decode
    assert reader.list_dir("a/dir") == ["gw_7", "gw_8"]
    with pytest.raises(aud.NotFound):
        reader.read_bytes("a/missing")
    with pytest.raises(aud.ReadError) as err:
        reader.read_bytes("a/boom")
    with pytest.raises(aud.ReadError, match="EMPTY_READ"):
        reader.read_bytes("a/empty")  # >1MB contents-API symptom must never hash as b""
    assert secret not in str(err.value)
    raw_calls = [cmd for cmd, _ in calls if "contents/a/ok" in cmd[-1]]
    assert "Accept: application/vnd.github.raw" in raw_calls[0]
    assert all(token == secret for _, token in calls)
    assert all(secret not in " ".join(cmd) for cmd, _ in calls)  # never on argv


def test_gh_runs_parses_jsonl_and_failure_raises_read_error():
    since = at(2026, 10, 25, 1, 0)
    ok = lambda cmd, **kw: _Proc(0, '{"display_title":"t","status":"queued","conclusion":null}\n')  # noqa: E731
    assert aud.gh_runs("o/r", since, run=ok)[0]["status"] == "queued"
    bad = lambda cmd, **kw: _Proc(1, "", "x")  # noqa: E731
    with pytest.raises(aud.ReadError):
        aud.gh_runs("o/r", since, run=bad)
