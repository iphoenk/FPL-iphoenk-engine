"""Advance `latest/verified.json` in the private repo only after independent verification.

`latest/*` is advanced by the runner BEFORE the orchestrator verifies the
occurrence, so it can describe an occurrence that later FAILED verification
(observed: DEEP 2026-10-23T21:30). `latest/verified.json` is the read-only
consumer contract: an entry exists only when, for the exact occurrence,
terminality verification, cross-artifact bindings, body/manifest hashes, remote
readback and the orchestrator receipt on issue #431 all passed.

The file holds identifiers and hashes only (no report content). It never
claims natural scheduler proof and is never written by the ChatGPT task.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence

from ops.audit_due_occurrences import (
    _SERVING,
    GhReader,
    NotFound,
    PRIVATE_REPO,
    ReadError,
    Reader,
    find_history_dir,
    verify_occurrence,
)
from ops.occurrence_reconciliation import occurrence_id

SCHEMA = "FPL_VERIFIED_POINTER_V1"
POINTER_PATH = "latest/verified.json"
PUBLISHABLE = frozenset({"READY_FULL", "READY_DEGRADED", "READY_DEGRADED_PUBLIC_FIRST"})
ADVANCED = "ADVANCED"
NOOP = "NOOP_IDEMPOTENT"
REFUSED_OLDER = "REFUSED_OLDER_SLOT"
REFUSED_IMMUTABLE = "REFUSED_IMMUTABLE_CONFLICT"
MAX_CAS_ATTEMPTS = 3


class Unverified(Exception):
    def __init__(self, reasons: Sequence[str]):
        super().__init__(",".join(reasons))
        self.reasons = list(reasons)


class WriteError(Exception):
    pass


class Conflict(WriteError):
    pass


class ReadOnly(WriteError):
    pass


class Store(Protocol):
    def get(self, path: str) -> tuple[bytes, str] | None: ...
    def put(self, path: str, data: bytes, sha: str | None, message: str) -> None: ...


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def receipt_present(comments: Sequence[str], oid: str, run_id: str) -> bool:
    """True only for a receipt comment of THIS orchestrator run and occurrence."""
    for body in comments:
        if f"occurrence_id={oid} status=" not in body:
            continue
        status = body.split(f"occurrence_id={oid} status=", 1)[1].split()[0]
        if status in PUBLISHABLE and f"orchestrator_run: `{run_id}`" in body:
            return True
    return False


def _require_presentation_qa(reader: Reader, history: str) -> None:
    """DEEP requires the occurrence's own presentation QA: 22 sections, exact order, no root failure."""
    try:
        qa = json.loads(reader.read_bytes(f"{history}/presentation_qa.json"))
    except NotFound:
        raise Unverified(["PRESENTATION_QA_MISSING"])
    except ValueError:
        raise Unverified(["PRESENTATION_QA_INVALID"])
    ok = (
        qa.get("section_count") == qa.get("expected_section_count") == 22
        and qa.get("section_order_exact") is True
        and qa.get("root_failure_count") == 0
        and qa.get("visible_report_body_non_empty") is True
    )
    if not ok:
        raise Unverified(["PRESENTATION_QA_FAILED"])


def _require_five_section_contract(reader: Reader, history: str, slot: str) -> None:
    """Fail closed unless the DEEP body satisfies the mandatory five-section presentation contract."""
    import re

    from src.engines import v12_five_section_presentation as contract

    match = re.search(r"/gw_(\d+)/", history)
    wib = datetime.fromisoformat(slot).astimezone(timezone(timedelta(hours=7)))
    slot_text = f"{wib.day} {wib:%b %Y}, {wib:%H:%M} WIB"
    body = reader.read_bytes(f"{history}/serving_report.md").decode("utf-8")
    failures = contract.gate(body, expected_gw=int(match.group(1)) if match else -1, expected_slot_wib=slot_text)
    if failures:
        raise Unverified(["PRESENTATION_CONTRACT_FAILED"] + failures)


def _optional_json(reader: Reader, path: str) -> dict[str, Any]:
    try:
        data = json.loads(reader.read_bytes(path))
    except (NotFound, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _generated_at(reader: Reader, history: str, mode: str) -> str | None:
    name = "delivery_status.json" if mode == "DEEP" else "execution_proof.json"
    value = _optional_json(reader, f"{history}/{name}").get("generated_at")
    return str(value) if value else None


def _runtime_sha(reader: Reader, history: str) -> str | None:
    value = _optional_json(reader, f"{history}/delivery_receipt.json").get("runtime_sha")
    return str(value) if value else None


def recovery_announced(comments: Sequence[str], oid: str) -> bool:
    """True when #431 carries the RECOVERY announcement for this exact occurrence."""
    marker = f"occurrence_id={oid} |"
    return any(c.startswith("FPL_RECOVERY_DISPATCH") and "label=RECOVERY" in c and marker in c for c in comments)


def external_clock_announced(comments: Sequence[str], oid: str) -> bool:
    """True when #431 carries the pre-dispatch EXTERNAL_INDEPENDENT_CLOCK announcement for this exact occurrence."""
    marker = f"occurrence_id={oid} |"
    return any(
        c.startswith("FPL_EXTERNAL_CLOCK_TRIGGER") and "label=EXTERNAL_INDEPENDENT_CLOCK" in c and marker in c
        for c in comments
    )


def build_entry(
    reader: Reader, mode: str, slot: str, *, now: datetime, orchestrator_run: str, origin: str = "SCHEDULED_OR_FALLBACK"
) -> dict[str, Any]:
    oid = occurrence_id(mode, slot)
    outcome, result = verify_occurrence(reader, mode, slot)
    if outcome != "VERIFIED":
        raise Unverified([f"VERIFY_{outcome}"])
    if result["failures"] or result["terminality"] not in PUBLISHABLE:
        raise Unverified(result["failures"] or [f"TERMINALITY_{result['terminality']}"])

    history = find_history_dir(reader, slot)
    digest_bytes = reader.read_bytes(f"{history}/digest.json")
    digest = json.loads(digest_bytes)
    body_name = "serving_report.md" if mode == "DEEP" else "report_body.md"
    body_sha = _sha(reader.read_bytes(f"{history}/{body_name}"))
    if body_sha != str(digest.get("canonical_body_sha256") or ""):
        raise Unverified(["BODY_SHA_MISMATCH"])

    if mode == "DEEP":
        _require_presentation_qa(reader, history)
        _require_five_section_contract(reader, history, slot)

    latest_bytes = reader.read_bytes(f"latest/{_SERVING[mode]}")
    latest = json.loads(latest_bytes)
    if latest.get("occurrence_id") != oid or latest.get("canonical_body_sha256") != body_sha:
        raise Unverified(["LATEST_NOT_THIS_OCCURRENCE"])

    report_md_sha = None
    manifest_sha = None
    native = "NOT_APPLICABLE"
    if mode == "DEEP":
        report_md_sha = _sha(reader.read_bytes("latest/report.md"))
        if report_md_sha != body_sha:
            raise Unverified(["LATEST_REPORT_MD_MISMATCH"])
        try:
            manifest_bytes = reader.read_bytes("latest/native_content.manifest.json")
        except NotFound:
            native = "ABSENT_TEXT_FALLBACK"
        else:
            manifest = json.loads(manifest_bytes)
            if (
                manifest.get("canonical_body_sha256") != body_sha
                or manifest.get("remote_readback") != "PASS"
                or manifest.get("verification_status") != "REMOTE_READBACK_PASS"
            ):
                raise Unverified(["NATIVE_MANIFEST_NOT_VERIFIED"])
            manifest_sha = _sha(manifest_bytes)
            native = "REMOTE_READBACK_PASS"

    return {
        "occurrence_id": oid,
        "report_mode": mode,
        "report_slot": slot,
        "terminality": result["terminality"],
        "history_path": history,
        "body_path": f"{history}/{body_name}",
        "generated_at": _generated_at(reader, history, mode),
        "runtime_sha": _runtime_sha(reader, history),
        "origin": origin,
        "presentation_contract": "FIVE_SECTION_V1_PASS" if mode == "DEEP" else "NOT_APPLICABLE",
        "canonical_body_sha256": body_sha,
        "canonical_bundle_sha256": str(digest.get("canonical_bundle_sha256") or ""),
        "digest_sha256": _sha(digest_bytes),
        "latest_serving_sha256": _sha(latest_bytes),
        "latest_report_md_sha256": report_md_sha,
        "native_manifest_sha256": manifest_sha,
        "native_transport": native,
        "remote_readback": "PASS",
        "receipt_verified": True,
        "orchestrator_run": str(orchestrator_run),
        "verified_at_utc": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "natural_scheduler_proof": False,
    }


def merge_pointer(current: Mapping[str, Any] | None, entry: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    modes = dict((current or {}).get("modes") or {})
    prior = modes.get(entry["report_mode"])
    if prior:
        new_slot = datetime.fromisoformat(entry["report_slot"])
        old_slot = datetime.fromisoformat(prior["report_slot"])
        if new_slot < old_slot:
            return dict(current or {}), REFUSED_OLDER
        if new_slot == old_slot:
            same = (
                prior["occurrence_id"] == entry["occurrence_id"]
                and prior["canonical_body_sha256"] == entry["canonical_body_sha256"]
            )
            return dict(current or {}), (NOOP if same else REFUSED_IMMUTABLE)
        advanced = dict(entry)
        advanced["sequence"] = int(prior.get("sequence") or 0) + 1
        advanced["supersedes"] = prior["occurrence_id"]
    else:
        advanced = dict(entry)
        advanced["sequence"] = 1
        advanced["supersedes"] = None
    modes[entry["report_mode"]] = advanced
    doc = {"schema": SCHEMA, "updated_at_utc": entry["verified_at_utc"], "modes": modes}
    return doc, ADVANCED


def advance(store: Store, entry: Mapping[str, Any]) -> str:
    """Compare-and-swap on the blob sha so concurrent verifiers cannot interleave."""
    for _ in range(MAX_CAS_ATTEMPTS):
        existing = store.get(POINTER_PATH)
        current = json.loads(existing[0]) if existing else None
        if current is not None and current.get("schema") != SCHEMA:
            raise WriteError("POINTER_SCHEMA_UNKNOWN")
        doc, action = merge_pointer(current, entry)
        if action != ADVANCED:
            return action
        payload = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
        try:
            store.put(
                POINTER_PATH,
                payload,
                existing[1] if existing else None,
                f"verified pointer {entry['occurrence_id']}",
            )
        except Conflict:
            continue
        return action
    raise WriteError("CAS_RETRIES_EXHAUSTED")


class GhStore:
    def __init__(self, token: str, repo: str = PRIVATE_REPO, run: Callable[..., Any] = subprocess.run):
        self._token, self._repo, self._run = token, repo, run

    def _call(self, args: list[str], stdin: bytes | None = None) -> bytes:
        env = {**os.environ, "GH_TOKEN": self._token}
        proc = self._run(["gh", "api", *args], env=env, input=stdin, capture_output=True, timeout=60)
        if proc.returncode:
            text = ((proc.stderr or b"") + (proc.stdout or b"")).decode("utf-8", "replace")
            if "HTTP 404" in text and "PUT" not in args:
                raise NotFound(args[-1])
            if "HTTP 409" in text or "HTTP 422" in text:
                raise Conflict("CAS_CONFLICT")
            if "HTTP 403" in text or "HTTP 404" in text:
                raise ReadOnly("PRIVATE_TOKEN_NOT_WRITABLE")
            raise WriteError("GH_API_FAILED")
        return proc.stdout

    def get(self, path: str) -> tuple[bytes, str] | None:
        try:
            out = self._call([f"/repos/{self._repo}/contents/{path}?ref=main"])
        except NotFound:
            return None
        meta = json.loads(out)
        return base64.b64decode(meta["content"]), str(meta["sha"])

    def put(self, path: str, data: bytes, sha: str | None, message: str) -> None:
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(data).decode("ascii"),
            "branch": "main",
        }
        if sha:
            body["sha"] = sha
        self._call(["-X", "PUT", f"/repos/{self._repo}/contents/{path}", "--input", "-"], json.dumps(body).encode())


RECEIPT_LOOKBACK = timedelta(hours=6)


def issue_comments(
    repo: str, since: datetime, run: Callable[..., Any] = subprocess.run
) -> list[str]:
    """Receipt comments of the current run only.

    Issue #431 holds >1400 comments; reading them all every run is slow and,
    through a paginating proxy, truncated. The receipt is posted seconds before
    this step, so a bounded `since` window is sufficient and deterministic.
    """
    stamp = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    proc = run(
        [
            "gh", "api", "--paginate",
            f"/repos/{repo}/issues/431/comments?per_page=100&since={stamp}",
            "--jq", ".[].body | @json",
        ],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode:
        raise ReadError("RECEIPT_COMMENTS_API_FAILED")
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=sorted(_SERVING))
    parser.add_argument("--slot", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    token = os.environ.get("FPL_PRIVATE_REPORTS_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "iphoenk/FPL-iphoenk-engine")
    oid = occurrence_id(args.mode, args.slot)
    event: dict[str, Any] = {"event": "FPL_VERIFIED_POINTER", "occurrence_id": oid}
    try:
        if not token:
            raise ReadOnly("PRIVATE_TOKEN_UNAVAILABLE")
        now = datetime.now(timezone.utc)
        comments = issue_comments(repo, now - RECEIPT_LOOKBACK)
        if not receipt_present(comments, oid, args.run_id):
            raise Unverified(["RECEIPT_NOT_FOUND"])
        # Most conservative label wins: any recovery or external-clock involvement is never reported as scheduled.
        if recovery_announced(comments, oid):
            origin = "RECOVERY"
        elif external_clock_announced(comments, oid):
            origin = "EXTERNAL_CLOCK"
        else:
            origin = "SCHEDULED_OR_FALLBACK"
        entry = build_entry(
            GhReader(token), args.mode, args.slot, now=now, orchestrator_run=args.run_id, origin=origin
        )
        event["action"] = advance(GhStore(token), entry)
    except Unverified as exc:
        event.update(action="NOT_ADVANCED_UNVERIFIED", reasons=exc.reasons)
    except ReadOnly as exc:
        event.update(action="NOT_ADVANCED_NOT_WRITABLE", reason=str(exc))
    except (WriteError, ReadError, NotFound) as exc:
        event.update(action="NOT_ADVANCED_ERROR", reason=type(exc).__name__ + ":" + str(exc)[:80])
    print(json.dumps(event, sort_keys=True))
    return 0  # never alters the orchestrator verdict; the receipt stays authoritative


if __name__ == "__main__":
    sys.exit(main())
