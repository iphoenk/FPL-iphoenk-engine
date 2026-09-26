from __future__ import annotations

"""P1 delivery/privacy boundary controls.

This module is intentionally outside V12 mathematics. It classifies publication
surfaces and validates what may leave the public repository. It must never
choose a route, alter a score, rewrite a section, or change Stage3 semantics.
"""

from dataclasses import dataclass
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
    re.compile(r"(?i)\bAuthorization\s*:\s*(?!\*{3,}|\[REDACTED\])\S+"),
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
