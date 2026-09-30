from __future__ import annotations

"""Thin private publisher for canonical V12 outputs.

The publisher copies already-computed, already-QA'd canonical material. It must
not import or invoke optimizers, Monte Carlo, lineup, package ranking, renderers,
or Stage3 decision functions.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
import shutil
from typing import Any, Mapping

from src.engines.v12_report_production_gate import evaluate_report_production_gate
from src.engines.v12_delivery_security import scan_secret_text


class PrivatePublishError(RuntimeError):
    pass


def classify_private_publish_error(error: BaseException) -> dict[str, Any]:
    """Return an allowlisted, non-sensitive publisher failure diagnostic."""
    message = str(error or "").strip()
    if message.startswith("REPORT_PRODUCTION_GATE failed:"):
        raw = message.split(":", 1)[1]
        failures = [
            token.strip()
            for token in raw.split(",")
            if re.fullmatch(r"[A-Z0-9_:-]+", token.strip())
        ]
        return {
            "code": "REPORT_PRODUCTION_GATE",
            "failures": failures or ["UNKNOWN"],
        }
    if message.startswith("report production gate missing serving artifacts:"):
        raw = message.split(":", 1)[1]
        allowed = set(_REPORT_FIRST_SERVING_FILES)
        missing = [
            Path(token.strip()).name
            for token in raw.split(",")
            if Path(token.strip()).name in allowed
        ]
        return {
            "code": "MISSING_SERVING_ARTIFACTS",
            "missing": missing or ["UNKNOWN"],
        }
    if message.startswith("PRIVACY_VALIDATION failed:"):
        return {"code": "PRIVACY_VALIDATION"}
    if "idempotency collision" in message:
        return {"code": "IDEMPOTENCY_COLLISION"}
    if message.startswith("canonical output incomplete"):
        return {"code": "CANONICAL_INCOMPLETE"}
    if "planning_gw" in message:
        return {"code": "PLANNING_GW_INVALID"}
    if "canonical bundle missing mode/slot" in message:
        return {"code": "CANONICAL_IDENTITY_INVALID"}
    if "publisher mutated canonical output" in message:
        return {"code": "CANONICAL_MUTATION_DETECTED"}
    return {"code": "PRIVATE_PUBLISHER_FAILURE"}


_REQUIRED_CANONICAL_FILES = (
    "report_bundle.json",
    "report_body.md",
    "execution_proof.json",
    "stage3_acceptance.json",
)
_OPTIONAL_SERVING_FILES = (
    "serving_report.json",
    "serving_report.md",
    "delivery_status.json",
    "delivery_state.json",
    "presentation_qa.json",
)
_REPORT_FIRST_SERVING_FILES = (
    "serving_report.json",
    "serving_report.md",
    "delivery_status.json",
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PrivatePublishError(f"expected JSON object: {path}")
    return value


def _season_from_report_slot(report_slot: str) -> str:
    token = str(report_slot or "").strip()
    if len(token) < 7 or not token[:4].isdigit() or token[4] != "-":
        raise PrivatePublishError("cannot derive season from report_slot")
    year = int(token[:4])
    month = int(token[5:7])
    start_year = year if month >= 7 else year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _timestamp_token(report_slot: str) -> str:
    token = str(report_slot or "").strip()
    if not token:
        raise PrivatePublishError("report_slot is required")
    return (
        token.replace(":", "")
        .replace("+", "_plus_")
        .replace("-", "")
        .replace("T", "_")
    )


def _safe_write_exact(destination: Path, payload: bytes) -> str:
    digest = sha256_bytes(payload)
    if destination.exists():
        existing = destination.read_bytes()
        if existing != payload:
            raise PrivatePublishError(
                f"idempotency collision at {destination}: existing content differs"
            )
        return digest
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(f".{destination.name}.tmp")
    tmp.write_bytes(payload)
    tmp.replace(destination)
    return digest


def _safe_write_text(destination: Path, text: str) -> str:
    return _safe_write_exact(destination, text.encode("utf-8"))


def _atomic_replace_bytes(destination: Path, payload: bytes) -> str:
    digest = sha256_bytes(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(f".{destination.name}.tmp")
    tmp.write_bytes(payload)
    tmp.replace(destination)
    return digest


def _atomic_replace_text(destination: Path, text: str) -> str:
    return _atomic_replace_bytes(destination, text.encode("utf-8"))


def build_private_digest(
    bundle: Mapping[str, Any],
    execution_proof: Mapping[str, Any],
    *,
    canonical_bundle_sha256: str,
    canonical_body_sha256: str,
) -> dict[str, Any]:
    """Copy canonical status/decision pointers without re-evaluating them."""
    section_manifest = bundle.get("section_manifest") or []
    section_ids = [
        str(row.get("id") or row.get("section_id") or "")
        for row in section_manifest
        if isinstance(row, Mapping)
    ]
    return {
        "schema_version": 1,
        "report_mode": bundle.get("report_mode"),
        "report_slot": bundle.get("report_slot"),
        "planning_gw": bundle.get("planning_gw"),
        "runner_status": bundle.get("runner_status"),
        "pre_render_status": (bundle.get("pre_render_qa") or {}).get("status"),
        "post_render_status": (bundle.get("post_render_qa") or {}).get("status"),
        "human_facing_status": (bundle.get("human_facing_qa") or {}).get("status"),
        "stage3_action": execution_proof.get("stage3_action"),
        "section_ids": section_ids,
        "canonical_bundle_sha256": canonical_bundle_sha256,
        "canonical_body_sha256": canonical_body_sha256,
        "decision_source": "CANONICAL_OUTPUT_COPY_ONLY",
        "math_recomputed": False,
    }


def render_private_digest_markdown(digest: Mapping[str, Any]) -> str:
    return (
        f"# V12 {digest.get('report_mode')} report\n\n"
        f"- Report slot: {digest.get('report_slot')}\n"
        f"- Planning GW: {digest.get('planning_gw')}\n"
        f"- Runner: {digest.get('runner_status')}\n"
        f"- Stage3 action: {digest.get('stage3_action')}\n"
        f"- Sections: {len(digest.get('section_ids') or [])}\n"
        f"- Canonical bundle SHA256: {digest.get('canonical_bundle_sha256')}\n"
        f"- Canonical body SHA256: {digest.get('canonical_body_sha256')}\n"
    )


def publish_private_output(
    *,
    canonical_dir: Path,
    private_root: Path,
    run_id: str,
    season: str | None,
    model_sha: str,
    runtime_sha: str,
    destination_relpath: str | None = None,
    update_latest: bool = True,
) -> dict[str, Any]:
    missing = [
        name for name in _REQUIRED_CANONICAL_FILES
        if not (canonical_dir / name).is_file()
    ]
    if missing:
        raise PrivatePublishError(
            f"canonical output incomplete; missing required files: {missing}"
        )

    before = {
        name: sha256_file(canonical_dir / name)
        for name in _REQUIRED_CANONICAL_FILES
    }
    bundle = _read_json(canonical_dir / "report_bundle.json")
    proof = _read_json(canonical_dir / "execution_proof.json")
    stage3 = _read_json(canonical_dir / "stage3_acceptance.json")

    report_mode = str(bundle.get("report_mode") or "").upper()
    report_slot = str(bundle.get("report_slot") or "")
    planning_gw = int(bundle.get("planning_gw") or 0)
    delivery_status = str(bundle.get("delivery_status") or "").upper()
    if not report_mode or not report_slot:
        raise PrivatePublishError("canonical bundle missing mode/slot")
    if planning_gw <= 0 and delivery_status != "READY_DEGRADED":
        raise PrivatePublishError("canonical full bundle missing planning_gw")

    stage3_status = str(stage3.get("status") or "UNKNOWN").upper()

    # REPORT-FIRST: P4/Stage3/PERF-F are engineering closure evidence, not
    # publication permission. Production DEEP occurrences must instead satisfy
    # the canonical report-serving contract and serving snapshot validation.
    production_delivery = report_mode == "DEEP" and bool(delivery_status)
    if production_delivery:
        missing_serving = [
            name for name in _REPORT_FIRST_SERVING_FILES
            if not (canonical_dir / name).is_file()
        ]
        if missing_serving:
            raise PrivatePublishError(
                "report production gate missing serving artifacts: "
                + ",".join(missing_serving)
            )

    presentation_qa = (
        _read_json(canonical_dir / "presentation_qa.json")
        if (canonical_dir / "presentation_qa.json").is_file()
        else None
    )
    serving_snapshot = (
        _read_json(canonical_dir / "serving_report.json")
        if (canonical_dir / "serving_report.json").is_file()
        else None
    )
    report_gate = evaluate_report_production_gate(
        bundle,
        presentation_qa=presentation_qa,
        serving_snapshot=serving_snapshot,
        visible_body_non_empty=bool(
            (canonical_dir / "report_body.md").read_text(encoding="utf-8").strip()
        ),
    )
    if report_gate.get("status") != "PASS":
        raise PrivatePublishError(
            "REPORT_PRODUCTION_GATE failed: "
            + ",".join(report_gate.get("failures") or ["UNKNOWN"])
        )

    privacy_findings: dict[str, list[int]] = {}
    for name in ("report_body.md", "serving_report.md", "serving_report.json"):
        path = canonical_dir / name
        if not path.is_file():
            continue
        findings = scan_secret_text(path.read_text(encoding="utf-8", errors="replace"))
        if findings:
            privacy_findings[name] = sorted({item.line_number for item in findings})
    if privacy_findings:
        raise PrivatePublishError(
            "PRIVACY_VALIDATION failed: client-serving credential material detected "
            + json.dumps(privacy_findings, sort_keys=True)
        )

    season_value = str(season or "").strip() or _season_from_report_slot(report_slot)
    slot_token = _timestamp_token(report_slot)
    if destination_relpath:
        relative = Path(str(destination_relpath))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise PrivatePublishError("controlled private destination must be a safe relative path")
        report_dir = private_root / relative
    else:
        report_dir = (
            private_root
            / "reports"
            / season_value
            / (f"gw_{planning_gw}" if planning_gw > 0 else "gw_unknown")
            / slot_token
        )
    latest_dir = private_root / "latest"

    canonical_bundle_sha = before["report_bundle.json"]
    canonical_body_sha = before["report_body.md"]
    digest = build_private_digest(
        bundle,
        proof,
        canonical_bundle_sha256=canonical_bundle_sha,
        canonical_body_sha256=canonical_body_sha,
    )
    digest_json = (
        json.dumps(digest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    digest_md = render_private_digest_markdown(digest)

    recovery_upgrade = False
    existing_bundle_path = report_dir / "report_bundle.json"
    if existing_bundle_path.exists():
        existing_bundle = _read_json(existing_bundle_path)
        same_occurrence = bool(
            str(existing_bundle.get("report_mode") or "").upper() == report_mode
            and str(existing_bundle.get("report_slot") or "") == report_slot
            and str(existing_bundle.get("occurrence_id") or f"{report_mode}|{report_slot}")
            == str(bundle.get("occurrence_id") or f"{report_mode}|{report_slot}")
        )
        recovery_upgrade = bool(
            same_occurrence
            and str(existing_bundle.get("delivery_status") or "").upper()
            == "READY_DEGRADED"
            and delivery_status == "READY_FULL"
        )
        if not same_occurrence and existing_bundle_path.read_bytes() != (
            canonical_dir / "report_bundle.json"
        ).read_bytes():
            raise PrivatePublishError(
                "idempotency collision across different report occurrence"
            )

    copied: dict[str, str] = {}
    for name in _REQUIRED_CANONICAL_FILES:
        payload = (canonical_dir / name).read_bytes()
        copied[name] = (
            _atomic_replace_bytes(report_dir / name, payload)
            if recovery_upgrade
            else _safe_write_exact(report_dir / name, payload)
        )
    for name in _OPTIONAL_SERVING_FILES:
        source = canonical_dir / name
        if source.is_file():
            payload = source.read_bytes()
            copied[name] = (
                _atomic_replace_bytes(report_dir / name, payload)
                if recovery_upgrade
                else _safe_write_exact(report_dir / name, payload)
            )

    write_text = _atomic_replace_text if recovery_upgrade else _safe_write_text

    execution_private = {
        "schema_version": 1,
        "run_id": str(run_id),
        "model_sha": str(model_sha),
        "runtime_sha": str(runtime_sha),
        "canonical_execution_proof_sha256": before["execution_proof.json"],
        "canonical_stage3_acceptance_sha256": before["stage3_acceptance.json"],
        "publisher": "V12_PRIVATE_THIN_COPY",
        "math_recomputed": False,
    }
    execution_private_json = (
        json.dumps(execution_private, indent=2, sort_keys=True) + "\n"
    )
    execution_private_sha = write_text(
        report_dir / "execution_proof_private.json",
        execution_private_json,
    )
    digest_sha = write_text(report_dir / "digest.json", digest_json)
    digest_md_sha = write_text(report_dir / "digest.md", digest_md)

    if update_latest:
        mode_lower = report_mode.lower()
        _atomic_replace_text(latest_dir / f"{mode_lower}.json", digest_json)
        _atomic_replace_text(latest_dir / f"{mode_lower}.md", digest_md)
        serving_map = {
            "serving_report.json": "report.json",
            "serving_report.md": "report.md",
            "delivery_status.json": "delivery_status.json",
            "delivery_state.json": "delivery_state.json",
            "presentation_qa.json": "presentation_qa.json",
        }
        for source_name, latest_name in serving_map.items():
            source = canonical_dir / source_name
            if source.is_file():
                _atomic_replace_bytes(latest_dir / latest_name, source.read_bytes())

    after = {
        name: sha256_file(canonical_dir / name)
        for name in _REQUIRED_CANONICAL_FILES
    }
    if before != after:
        raise PrivatePublishError(
            "publisher mutated canonical output; refusing delivery"
        )

    receipt = {
        "schema_version": 1,
        "run_id": str(run_id),
        "report_mode": report_mode,
        "report_slot": report_slot,
        "planning_gw": planning_gw,
        "season": season_value,
        "destination": str(report_dir.relative_to(private_root)),
        "canonical_bundle_sha256": canonical_bundle_sha,
        "canonical_body_sha256": canonical_body_sha,
        "digest_sha256": digest_sha,
        "digest_md_sha256": digest_md_sha,
        "execution_proof_private_sha256": execution_private_sha,
        "model_sha": str(model_sha),
        "runtime_sha": str(runtime_sha),
        "private_delivery_status": "PASS",
        "privacy_validation_status": "PASS",
        "report_prod_status": "REPORT GREEN",
        "report_production_gate": report_gate.get("contract"),
        "engineering_closure_status": stage3_status,
        "engineering_closure_blocks_report": False,
        "delivery_status": delivery_status or "LEGACY",
        "same_occurrence_recovery_upgrade": recovery_upgrade,
        "serving_snapshot_published": (canonical_dir / "serving_report.json").is_file(),
        "math_recomputed": False,
    }
    receipt_json = (
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    receipt_sha = write_text(
        report_dir / "delivery_receipt.json",
        receipt_json,
    )
    receipt["delivery_receipt_sha256"] = receipt_sha
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-dir", required=True)
    parser.add_argument("--private-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--season", default="")
    parser.add_argument("--model-sha", required=True)
    parser.add_argument("--runtime-sha", required=True)
    parser.add_argument("--receipt-out", required=True)
    parser.add_argument("--destination-relpath", default="")
    parser.add_argument("--no-update-latest", action="store_true")
    args = parser.parse_args()

    try:
        receipt = publish_private_output(
            canonical_dir=Path(args.canonical_dir),
            private_root=Path(args.private_root),
            run_id=args.run_id,
            season=(args.season or None),
            model_sha=args.model_sha,
            runtime_sha=args.runtime_sha,
            destination_relpath=(args.destination_relpath or None),
            update_latest=not args.no_update_latest,
        )
    except PrivatePublishError as exc:
        diagnostic = classify_private_publish_error(exc)
        print(
            "PRIVATE_PUBLISH_FAILURE="
            + json.dumps(diagnostic, sort_keys=True, separators=(",", ":")),
            file=sys.stderr,
            flush=True,
        )
        return 2
    out = Path(args.receipt_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "private_delivery_status": "PASS",
                "receipt_sha256": receipt["delivery_receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
