from __future__ import annotations

"""P1 delivery/privacy boundary controls.

This module is intentionally outside V12 mathematics. It classifies publication
surfaces and validates what may leave the public repository. It must never
choose a route, alter a score, rewrite a section, or change Stage3 semantics.
"""

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "config/security/v12_delivery_classification.json"


class DeliverySecurityError(RuntimeError):
    pass


def load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _walk_keys(value: Any, prefix: str = ""):
    if isinstance(value, Mapping):
        for key, child in value.items():
            token = str(key)
            path = f"{prefix}.{token}" if prefix else token
            yield path, token
            yield from _walk_keys(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_keys(child, f"{prefix}[{index}]")


def validate_public_proof(proof: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed unless the proof is entirely within the public allowlist."""
    contract = load_contract()
    allowed = set(contract["public_proof_allowed_fields"])
    forbidden = {
        str(key).lower()
        for key in contract["public_proof_forbidden_semantic_keys"]
    }

    extras = sorted(set(map(str, proof.keys())) - allowed)
    if extras:
        raise DeliverySecurityError(
            f"public proof contains non-allowlisted top-level fields: {extras}"
        )

    bad_paths: list[str] = []
    for path, key in _walk_keys(proof):
        if key.lower() in forbidden:
            bad_paths.append(path)
    if bad_paths:
        raise DeliverySecurityError(
            f"public proof contains sensitive semantic keys: {sorted(bad_paths)}"
        )

    fingerprints = proof.get("safe_fingerprints")
    if fingerprints is not None:
        if not isinstance(fingerprints, Mapping):
            raise DeliverySecurityError("safe_fingerprints must be a mapping")
        for key, value in fingerprints.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise DeliverySecurityError(
                    "safe_fingerprints must contain string keys and values"
                )

    timing = proof.get("timing")
    if timing is not None:
        if not isinstance(timing, Mapping):
            raise DeliverySecurityError("timing must be a mapping")
        for key, value in timing.items():
            if not isinstance(key, str) or not isinstance(value, (int, float)):
                raise DeliverySecurityError(
                    "timing must contain string keys and numeric values"
                )

    return dict(proof)


_DECISION_TEXT_PATTERNS = (
    re.compile(r"(?i)\bSTAGE3_ACTION\b\s*[:=]"),
    re.compile(r"(?i)\baction\s*=\s*(?:WAIT|PREPARE|ACT|HOLD)\b"),
    re.compile(r"(?i)\b(?:selected_route|selected_route_id|final_judgement)\b\s*[:=]"),
    re.compile(r"(?i)\b(?:starting_xi|vice_captain|staging_rows|pending_transfer)\b\s*[:=]"),
    re.compile(r"(?i)\b(?:captain|vice|chip|bank|selling_price|purchase_price|free_transfers)\b\s*[:=]"),
    re.compile(r"(?i)\bPRIMARY\s+DECISION\b"),
    re.compile(r"(?i)\bOUT\b\s*(?:->|→)\s*\bIN\b"),
)

_SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)\\bAuthorization\\s*:\\s*(?!(?:basic\\s+)?(?:\\*{3,}|\\[REDACTED\\]))\\S+(?:\\s+\\S+)?"),
    re.compile(r"(?i)\bCookie\s*:\s*(?!\*{3,}|\[REDACTED\])\S+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{20,}\b"),
)


@dataclass(frozen=True)
class TextLeakFinding:
    line_number: int
    category: str
    pattern: str


def scan_public_text(text: str) -> list[TextLeakFinding]:
    findings: list[TextLeakFinding] = []
    for line_number, line in enumerate(str(text).splitlines(), start=1):
        for pattern in _DECISION_TEXT_PATTERNS:
            if pattern.search(line):
                findings.append(
                    TextLeakFinding(line_number, "PRIVATE_DECISION", pattern.pattern)
                )
        for pattern in _SECRET_TEXT_PATTERNS:
            if pattern.search(line):
                findings.append(
                    TextLeakFinding(line_number, "SECRET", pattern.pattern)
                )
    return findings


def build_public_issue_proof(
    *,
    analytics_status: str,
    report_mode: str,
    report_slot: str,
    run_id: str | int,
    stage3_validation: str,
    private_delivery_status: str,
    private_receipt_hash: str = "",
) -> str:
    """Build a compact public issue line without any decision value."""
    allowed_stage3 = set(
        load_contract()["public_issue_proof_rule"]["allowed_stage3_values"]
    )
    stage3 = str(stage3_validation or "UNKNOWN").upper()
    if stage3 not in allowed_stage3:
        raise DeliverySecurityError(f"invalid public Stage3 validation state: {stage3}")
    fields = {
        "analytics": str(analytics_status or "UNKNOWN").upper(),
        "report_mode": str(report_mode or "UNKNOWN").upper(),
        "report_slot": str(report_slot or ""),
        "run_id": str(run_id),
        "stage3_validation": stage3,
        "private_delivery": str(private_delivery_status or "UNKNOWN").upper(),
        "receipt": str(private_receipt_hash or ""),
    }
    return "V12_PUBLIC_PROOF | " + " | ".join(
        f"{key}={value}" for key, value in fields.items()
    )


def workflow_pull_request_target_hits(
    workflows_root: Path | None = None,
) -> list[str]:
    """Return repo-relative workflow paths containing pull_request_target."""
    root = workflows_root or (ROOT / ".github/workflows")
    hits: list[str] = []
    if not root.exists():
        raise DeliverySecurityError(f"workflow directory missing: {root}")
    pattern = re.compile(r"(?m)^\s*[\"']?pull_request_target[\"']?\s*:")
    for path in sorted(root.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            hits.append(str(path.relative_to(ROOT)))
    return hits


def assert_no_pull_request_target(
    workflows_root: Path | None = None,
) -> None:
    hits = workflow_pull_request_target_hits(workflows_root)
    if hits:
        raise DeliverySecurityError(
            f"pull_request_target is forbidden for P1 public workflows: {hits}"
        )


def cache_security_manifest() -> dict[str, str]:
    return dict(load_contract()["cache_target_classification"])



def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DeliverySecurityError(f"expected JSON object: {path}")
    return value


def build_public_proof_from_files(
    *,
    execution_proof_path: Path,
    stage3_acceptance_path: Path,
    private_receipt_path: Path | None,
    report_mode: str,
    report_slot: str,
    run_id: str,
    model_sha: str,
    runtime_sha: str,
    private_delivery_status: str,
    profile_mode: str = "OFF",
) -> dict[str, Any]:
    proof = _read_json_object(execution_proof_path)
    stage3 = _read_json_object(stage3_acceptance_path)
    delivery = str(private_delivery_status or "FAIL").upper()

    receipt_hash = ""
    safe_fingerprints: dict[str, str] = {}
    if private_receipt_path is not None and private_receipt_path.is_file():
        receipt_bytes = private_receipt_path.read_bytes()
        receipt_hash = hashlib.sha256(receipt_bytes).hexdigest()
        receipt = _read_json_object(private_receipt_path)
        if str(receipt.get("private_delivery_status") or "").upper() == "PASS":
            for source, target in (
                ("canonical_bundle_sha256", "canonical_bundle"),
                ("canonical_body_sha256", "canonical_body"),
            ):
                value = receipt.get(source)
                if isinstance(value, str) and value:
                    safe_fingerprints[target] = value

    stage_rows = proof.get("stages") or []
    elapsed = sum(
        float(row.get("elapsed_seconds") or 0.0)
        for row in stage_rows
        if isinstance(row, Mapping)
    )
    canonical_human = str(
        proof.get("human_facing_qa_status") or "UNKNOWN"
    ).upper()
    human_delivery = canonical_human if delivery == "PASS" else "FAIL"

    public = {
        "report_mode": str(report_mode or "").upper(),
        "report_slot": str(report_slot or ""),
        "run_id": str(run_id),
        "analytics_status": str(proof.get("runner_status") or "UNKNOWN").upper(),
        "pre_render_status": str(
            proof.get("pre_render_qa_status") or "UNKNOWN"
        ).upper(),
        "post_render_status": str(
            proof.get("post_render_qa_status") or "UNKNOWN"
        ).upper(),
        "human_facing_status": human_delivery,
        "stage3_validation_status": str(
            stage3.get("status") or "UNKNOWN"
        ).upper(),
        "model_sha": str(model_sha or ""),
        "runtime_sha": str(runtime_sha or ""),
        "safe_fingerprints": safe_fingerprints,
        "private_delivery_status": delivery,
        "private_receipt_hash": receipt_hash,
        "timing": {"stage_elapsed_seconds": round(elapsed, 6)},
        "profile_mode": str(profile_mode or "OFF").upper(),
    }
    return validate_public_proof(public)


def _main_build_proof(args: argparse.Namespace) -> int:
    receipt = Path(args.private_receipt) if args.private_receipt else None
    proof = build_public_proof_from_files(
        execution_proof_path=Path(args.execution_proof),
        stage3_acceptance_path=Path(args.stage3_acceptance),
        private_receipt_path=receipt,
        report_mode=args.report_mode,
        report_slot=args.report_slot,
        run_id=args.run_id,
        model_sha=args.model_sha,
        runtime_sha=args.runtime_sha,
        private_delivery_status=args.private_delivery_status,
        profile_mode=args.profile_mode,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"public_proof_status": "PASS"}, sort_keys=True))
    return 0


def _main_scan_log(args: argparse.Namespace) -> int:
    findings = scan_public_text(Path(args.path).read_text(
        encoding="utf-8", errors="replace"
    ))
    summary = {
        "status": "PASS" if not findings else "FAIL",
        "finding_count": len(findings),
        "categories": sorted({item.category for item in findings}),
        "line_numbers": sorted({item.line_number for item in findings}),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if not findings else 1


def _main_scan_workflows(_: argparse.Namespace) -> int:
    hits = workflow_pull_request_target_hits()
    print(json.dumps(
        {
            "status": "PASS" if not hits else "FAIL",
            "pull_request_target_hits": hits,
        },
        sort_keys=True,
    ))
    return 0 if not hits else 1


def _main_issue_proof(args: argparse.Namespace) -> int:
    proof = validate_public_proof(_read_json_object(Path(args.public_proof)))
    line = build_public_issue_proof(
        analytics_status=str(proof.get("analytics_status") or "UNKNOWN"),
        report_mode=str(proof.get("report_mode") or "UNKNOWN"),
        report_slot=str(proof.get("report_slot") or ""),
        run_id=str(proof.get("run_id") or ""),
        stage3_validation=str(
            proof.get("stage3_validation_status") or "UNKNOWN"
        ),
        private_delivery_status=str(
            proof.get("private_delivery_status") or "UNKNOWN"
        ),
        private_receipt_hash=str(proof.get("private_receipt_hash") or ""),
    )
    Path(args.output).write_text(line + "\n", encoding="utf-8")
    print(json.dumps({"issue_proof_status": "PASS"}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-proof")
    build.add_argument("--execution-proof", required=True)
    build.add_argument("--stage3-acceptance", required=True)
    build.add_argument("--private-receipt", default="")
    build.add_argument("--report-mode", required=True)
    build.add_argument("--report-slot", required=True)
    build.add_argument("--run-id", required=True)
    build.add_argument("--model-sha", required=True)
    build.add_argument("--runtime-sha", required=True)
    build.add_argument("--private-delivery-status", required=True)
    build.add_argument("--profile-mode", default="OFF")
    build.add_argument("--output", required=True)
    build.set_defaults(func=_main_build_proof)

    scan = sub.add_parser("scan-log")
    scan.add_argument("--path", required=True)
    scan.set_defaults(func=_main_scan_log)

    workflows = sub.add_parser("scan-workflows")
    workflows.set_defaults(func=_main_scan_workflows)

    issue = sub.add_parser("issue-proof")
    issue.add_argument("--public-proof", required=True)
    issue.add_argument("--output", required=True)
    issue.set_defaults(func=_main_issue_proof)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
