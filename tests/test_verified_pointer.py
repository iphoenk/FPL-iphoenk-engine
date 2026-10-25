"""latest/verified.json: advancement only after independent verification."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone

import pytest

from ops import verified_pointer as vp
from test_p0b_missed_slot_reconciliation import (
    DEEP_SLOT,
    PRICE_SLOT,
    FakeReader,
    _j,
    private_files,
)

NOW = datetime(2026, 10, 25, 6, 0, tzinfo=timezone.utc)
LATER_DEEP = "2026-10-25T21:30:00+07:00"
EARLIER_DEEP = "2026-10-25T04:30:00+07:00"


def _entry(mode="DEEP", slot=DEEP_SLOT, **kw):
    return vp.build_entry(FakeReader(private_files(mode, slot, **kw)), mode, slot, now=NOW, orchestrator_run="9001")


class MemStore:
    def __init__(self, conflicts=0):
        self.files, self.conflicts, self.puts = {}, conflicts, 0

    def get(self, path):
        if path not in self.files:
            return None
        data, version = self.files[path]
        return data, f"blob{version}"

    def put(self, path, data, sha, message):
        if self.conflicts:
            self.conflicts -= 1
            raise vp.Conflict("CAS_CONFLICT")
        current = self.files.get(path)
        assert (current is None and sha is None) or (current and sha == f"blob{current[1]}")
        self.files[path] = (data, (current[1] + 1) if current else 1)
        self.puts += 1


def test_entry_for_verified_deep_binds_hashes_and_never_claims_natural_proof():
    entry = _entry()
    body_sha = hashlib.sha256(b"# report\n").hexdigest()
    assert entry["occurrence_id"] == f"DEEP|{DEEP_SLOT}"
    assert entry["canonical_body_sha256"] == entry["latest_report_md_sha256"] == body_sha
    assert entry["terminality"] == "READY_FULL" and entry["remote_readback"] == "PASS"
    assert entry["natural_scheduler_proof"] is False and entry["receipt_verified"] is True
    assert entry["native_transport"] == "ABSENT_TEXT_FALLBACK" and entry["native_manifest_sha256"] is None


def test_entry_for_price_has_no_deep_only_fields():
    entry = _entry("PRICE", PRICE_SLOT)
    assert entry["native_transport"] == "NOT_APPLICABLE" and entry["latest_report_md_sha256"] is None


def test_native_manifest_must_match_body_and_pass_readback():
    files = private_files("DEEP", DEEP_SLOT)
    body_sha = hashlib.sha256(b"# report\n").hexdigest()
    good = {"canonical_body_sha256": body_sha, "remote_readback": "PASS", "verification_status": "REMOTE_READBACK_PASS"}
    files["latest/native_content.manifest.json"] = _j(good)
    entry = vp.build_entry(FakeReader(files), "DEEP", DEEP_SLOT, now=NOW, orchestrator_run="1")
    assert entry["native_transport"] == "REMOTE_READBACK_PASS"
    assert entry["native_manifest_sha256"] == hashlib.sha256(_j(good)).hexdigest()
    for bad in (
        {**good, "canonical_body_sha256": "0" * 64},
        {**good, "remote_readback": "FAIL"},
        {**good, "verification_status": "PENDING"},
    ):
        files["latest/native_content.manifest.json"] = _j(bad)
        with pytest.raises(vp.Unverified, match="NATIVE_MANIFEST_NOT_VERIFIED"):
            vp.build_entry(FakeReader(files), "DEEP", DEEP_SLOT, now=NOW, orchestrator_run="1")


def test_tampered_body_missing_receipt_and_api_failure_never_produce_an_entry():
    files = private_files("DEEP", DEEP_SLOT)
    hist = next(k for k in files if k.endswith("/serving_report.md"))
    files[hist] = b"tampered\n"
    with pytest.raises(vp.Unverified):
        vp.build_entry(FakeReader(files), "DEEP", DEEP_SLOT, now=NOW, orchestrator_run="1")
    with pytest.raises(vp.Unverified, match="VERIFY_NOT_FOUND"):
        vp.build_entry(FakeReader({}), "DEEP", DEEP_SLOT, now=NOW, orchestrator_run="1")
    with pytest.raises(vp.Unverified, match="VERIFY_ERROR"):
        vp.build_entry(FakeReader(private_files("DEEP", DEEP_SLOT), fail=("reports/",)), "DEEP", DEEP_SLOT, now=NOW, orchestrator_run="1")


def test_ungoverned_degraded_occurrence_is_not_advanced():
    with pytest.raises(vp.Unverified):
        _entry(status="READY_DEGRADED")


def test_latest_that_moved_past_this_occurrence_is_not_advanced_from_this_run():
    with pytest.raises(vp.Unverified, match="LATEST_NOT_THIS_OCCURRENCE"):
        _entry(latest_slot=LATER_DEEP)


def test_latest_report_md_must_match_body():
    files = private_files("DEEP", DEEP_SLOT)
    files["latest/report.md"] = b"another report\n"
    with pytest.raises(vp.Unverified):
        vp.build_entry(FakeReader(files), "DEEP", DEEP_SLOT, now=NOW, orchestrator_run="1")


def _ent(mode, slot, body="a"):
    return {
        "occurrence_id": f"{mode}|{slot}", "report_mode": mode, "report_slot": slot,
        "canonical_body_sha256": body * 64, "verified_at_utc": "2026-10-25T06:00:00Z",
    }


def test_merge_is_monotonic_immutable_and_idempotent():
    doc, action = vp.merge_pointer(None, _ent("DEEP", EARLIER_DEEP))
    assert action == vp.ADVANCED and doc["modes"]["DEEP"]["sequence"] == 1 and doc["modes"]["DEEP"]["supersedes"] is None
    doc2, action = vp.merge_pointer(doc, _ent("DEEP", DEEP_SLOT, "b"))
    assert action == vp.ADVANCED and doc2["modes"]["DEEP"]["sequence"] == 2
    assert doc2["modes"]["DEEP"]["supersedes"] == f"DEEP|{EARLIER_DEEP}"
    assert vp.merge_pointer(doc2, _ent("DEEP", DEEP_SLOT, "b"))[1] == vp.NOOP
    assert vp.merge_pointer(doc2, _ent("DEEP", DEEP_SLOT, "c"))[1] == vp.REFUSED_IMMUTABLE
    assert vp.merge_pointer(doc2, _ent("DEEP", EARLIER_DEEP))[1] == vp.REFUSED_OLDER
    assert vp.merge_pointer(doc2, _ent("DEEP", EARLIER_DEEP))[0] == doc2  # refusal leaves it untouched


def test_modes_advance_independently():
    doc, _ = vp.merge_pointer(None, _ent("DEEP", DEEP_SLOT))
    doc, action = vp.merge_pointer(doc, _ent("PRICE", PRICE_SLOT))
    assert action == vp.ADVANCED and set(doc["modes"]) == {"DEEP", "PRICE"}
    assert doc["modes"]["DEEP"]["sequence"] == 1 and doc["modes"]["PRICE"]["sequence"] == 1


def test_advance_writes_once_then_is_idempotent_and_holds_no_report_content():
    store = MemStore()
    entry = _entry()
    assert vp.advance(store, entry) == vp.ADVANCED
    assert vp.advance(store, entry) == vp.NOOP and store.puts == 1
    raw = store.files[vp.POINTER_PATH][0]
    assert b"# report" not in raw and json.loads(raw)["schema"] == vp.SCHEMA


def test_compare_and_swap_retries_conflict_then_gives_up():
    store = MemStore(conflicts=2)
    assert vp.advance(store, _entry()) == vp.ADVANCED and store.puts == 1
    with pytest.raises(vp.WriteError, match="CAS_RETRIES_EXHAUSTED"):
        vp.advance(MemStore(conflicts=3), _entry())


def test_unknown_pointer_schema_is_never_overwritten():
    store = MemStore()
    store.files[vp.POINTER_PATH] = (b'{"schema": "OTHER"}', 1)
    with pytest.raises(vp.WriteError, match="POINTER_SCHEMA_UNKNOWN"):
        vp.advance(store, _entry())
    assert store.puts == 0


def test_receipt_must_match_occurrence_run_and_publishable_status():
    oid = f"DEEP|{DEEP_SLOT}"

    def comment(status, run, occurrence=oid):
        return f"<!-- FPL_MASTER_RECEIPT occurrence_id={occurrence} status={status} -->\n- orchestrator_run: `{run}`\n"

    assert vp.receipt_present([comment("READY_FULL", "9001")], oid, "9001")
    assert vp.receipt_present([comment("READY_DEGRADED", "9001")], oid, "9001")
    assert not vp.receipt_present([comment("READY_FULL", "9002")], oid, "9001")
    assert not vp.receipt_present([comment("FAILED_VERIFY", "9001")], oid, "9001")
    assert not vp.receipt_present([comment("READY_REUSED", "9001")], oid, "9001")
    assert not vp.receipt_present([comment("READY_FULL", "9001", "DEEP|2026-10-25T04:30:00+07:00")], oid, "9001")
    assert not vp.receipt_present([], oid, "9001")


class _Proc:
    def __init__(self, rc=0, out=b"", err=b""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_gh_store_get_put_and_error_mapping_without_token_on_argv():
    secret = "ghp_SECRET"
    calls = []

    def run(cmd, env=None, input=None, **kw):
        calls.append((cmd, env["GH_TOKEN"], input))
        path = cmd[-1] if "--input" not in cmd else cmd[cmd.index("--input") - 1]
        if "missing" in path:
            return _Proc(1, b"", b"HTTP 404")
        if "conflict" in path:
            return _Proc(1, b"", b"HTTP 409")
        if "forbidden" in path:
            return _Proc(1, b"", b"HTTP 403")
        if "-X" in cmd:
            return _Proc(0, b"{}")
        return _Proc(0, json.dumps({"content": base64.b64encode(b"hello").decode(), "sha": "abc"}).encode())

    store = vp.GhStore(secret, run=run)
    assert store.get("latest/x") == (b"hello", "abc")
    assert store.get("latest/missing") is None
    store.put("latest/ok", b"data", "abc", "msg")
    put_cmd, _, put_input = calls[-1]
    body = json.loads(put_input)
    assert body["sha"] == "abc" and base64.b64decode(body["content"]) == b"data" and body["branch"] == "main"
    with pytest.raises(vp.Conflict):
        store.put("latest/conflict", b"d", None, "m")
    with pytest.raises(vp.ReadOnly):
        store.put("latest/forbidden", b"d", None, "m")
    assert all(token == secret and secret not in " ".join(cmd) for cmd, token, _ in calls)


def test_cli_without_token_never_fails_the_orchestrator(monkeypatch, capsys):
    monkeypatch.delenv("FPL_PRIVATE_REPORTS_TOKEN", raising=False)
    rc = vp.main(["--mode", "DEEP", "--slot", DEEP_SLOT, "--run-id", "1"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["action"] == "NOT_ADVANCED_NOT_WRITABLE"
