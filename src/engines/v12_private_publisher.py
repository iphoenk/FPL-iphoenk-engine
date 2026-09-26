from __future__ import annotations

"""Thin private publisher for canonical V12 outputs.

The publisher copies already-computed, already-QA'd canonical material. It must
not import or invoke optimizers, Monte Carlo, lineup, package ranking, renderers,
or Stage3 decision functions.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping


class PrivatePublishError(RuntimeError):
    pass


_REQUIRED_CANONICAL_FILES = (
    "report_bundle.json",
    "report_body.md",
    "execution_proof.json",
    "stage3_acceptance.json",
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


def _atomic_replace_text(destination: Path, text: str) -> str:
    payload = text.encode("utf-8")
    digest = sha256_bytes(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(f".{destination.name}.tmp")
    tmp.write_bytes(payload)
    tmp.replace(destination)
    return digest


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
    if not report_mode or not report_slot or planning_gw <= 0:
        raise PrivatePublishError("canonical bundle missing mode/slot/planning_gw")

    if str(stage3.get("status") or "UNKNOWN").upper() not in {
        "PASS", "NOT_APPLICABLE"
    }:
        raise PrivatePublishError("Stage3 canonical acceptance is not publishable")

    season_value = str(season or "").strip() or _season_from_report_slot(report_slot)
    slot_token = _timestamp_token(report_slot)
    report_dir = (
        private_root
        / "reports"
        / season_value
        / f"gw_{planning_gw}"
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

    copied: dict[str, str] = {}
    for name in _REQUIRED_CANONICAL_FILES:
        payload = (canonical_dir / name).read_bytes()
        copied[name] = _safe_write_exact(report_dir / name, payload)

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
    execution_private_sha = _safe_write_text(
        report_dir / "execution_proof_private.json",
        execution_private_json,
    )
    digest_sha = _safe_write_text(report_dir / "digest.json", digest_json)
    digest_md_sha = _safe_write_text(report_dir / "digest.md", digest_md)

    mode_lower = report_mode.lower()
    _atomic_replace_text(latest_dir / f"{mode_lower}.json", digest_json)
    _atomic_replace_text(latest_dir / f"{mode_lower}.md", digest_md)

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
        "math_recomputed": False,
    }
    receipt_json = (
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    receipt_sha = _safe_write_text(
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
    args = parser.parse_args()

    receipt = publish_private_output(
        canonical_dir=Path(args.canonical_dir),
        private_root=Path(args.private_root),
        run_id=args.run_id,
        season=(args.season or None),
        model_sha=args.model_sha,
        runtime_sha=args.runtime_sha,
    )
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
