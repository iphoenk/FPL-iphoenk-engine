from __future__ import annotations

"""Non-sensitive P1-M synthetic acceptance.

Runs the same thin private publisher and public-proof builder used by delivery.
Private synthetic report material stays inside the ephemeral runner. Only the
allowlisted public proof is eligible for Actions artifact upload.
"""

import argparse
import json
from pathlib import Path

from src.engines.v12_delivery_security import build_public_proof_from_files
from src.engines.v12_private_publisher import publish_private_output, sha256_file

SECTION_IDS = [
    "S01", "S02", "S03", "S04", "S05", "S06", "S06B",
    "S07", "S08", "S09", "S10", "S11", "S12", "S13",
    "S14", "S14B", "S15", "S15B", "S16", "S16B",
    "S17", "S18", "S19",
]


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_fixture(canonical: Path) -> None:
    canonical.mkdir(parents=True, exist_ok=True)
    bundle = {
        "report_mode": "DEEP",
        "report_slot": "2026-09-26T12:30:00+07:00",
        "planning_gw": 6,
        "runner_status": "PASS",
        "section_manifest": [{"id": value} for value in SECTION_IDS],
        "pre_render_qa": {"status": "PASS"},
        "post_render_qa": {"status": "PASS"},
        "human_facing_qa": {"status": "PASS"},
        "execution_proof": {"stage3_action": "WAIT"},
        "report": {"S03": {"delta": "IDENTITY_FIXTURE"}},
    }
    proof = {
        "runner_status": "PASS",
        "stage3_action": "WAIT",
        "rendered_section_ids": SECTION_IDS,
        "pre_render_qa_status": "PASS",
        "post_render_qa_status": "PASS",
        "human_facing_qa_status": "PASS",
        "stages": [{"stage": "SYNTHETIC", "elapsed_seconds": 0.0}],
    }
    stage3 = {"status": "PASS", "stage3_action": "WAIT"}
    body = "# Synthetic canonical report\n\nDecision fixture is private.\n"
    _write_json(canonical / "report_bundle.json", bundle)
    (canonical / "report_body.md").write_text(body, encoding="utf-8")
    _write_json(canonical / "execution_proof.json", proof)
    _write_json(canonical / "stage3_acceptance.json", stage3)


def run(root: Path, *, run_id: str, model_sha: str, runtime_sha: str) -> dict:
    canonical = root / "canonical"
    private = root / "private"
    public = root / "public"
    _write_fixture(canonical)

    before_bundle = sha256_file(canonical / "report_bundle.json")
    before_body = sha256_file(canonical / "report_body.md")
    receipt = publish_private_output(
        canonical_dir=canonical,
        private_root=private,
        run_id=run_id,
        season="2026-27",
        model_sha=model_sha,
        runtime_sha=runtime_sha,
    )
    receipt_out = root / "receipt.json"
    _write_json(receipt_out, receipt)

    proof = build_public_proof_from_files(
        execution_proof_path=canonical / "execution_proof.json",
        stage3_acceptance_path=canonical / "stage3_acceptance.json",
        private_receipt_path=receipt_out,
        report_mode="DEEP",
        report_slot="2026-09-26T12:30:00+07:00",
        run_id=run_id,
        model_sha=model_sha,
        runtime_sha=runtime_sha,
        private_delivery_status="PASS",
        profile_mode="OFF",
    )
    public.mkdir(parents=True, exist_ok=True)
    _write_json(public / "public_proof.json", proof)

    destination = private / receipt["destination"]
    expected_private = {
        "digest.json",
        "digest.md",
        "report_bundle.json",
        "report_body.md",
        "execution_proof_private.json",
        "delivery_receipt.json",
        "execution_proof.json",
        "stage3_acceptance.json",
    }
    actual_private = {path.name for path in destination.iterdir()}
    missing = sorted(expected_private - actual_private)
    if missing:
        raise RuntimeError(f"synthetic private delivery incomplete: {missing}")
    if sha256_file(destination / "report_bundle.json") != before_bundle:
        raise RuntimeError("synthetic private bundle is not bit-identical")
    if sha256_file(destination / "report_body.md") != before_body:
        raise RuntimeError("synthetic private body is not bit-identical")
    if {path.name for path in public.iterdir()} != {"public_proof.json"}:
        raise RuntimeError("synthetic public surface contains non-proof files")
    if proof.get("private_delivery_status") != "PASS":
        raise RuntimeError("synthetic private delivery did not pass")
    if proof.get("human_facing_status") != "PASS":
        raise RuntimeError("synthetic fail-closed human delivery did not pass")

    return proof


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model-sha", required=True)
    parser.add_argument("--runtime-sha", required=True)
    args = parser.parse_args()
    proof = run(
        Path(args.root),
        run_id=args.run_id,
        model_sha=args.model_sha,
        runtime_sha=args.runtime_sha,
    )
    print(json.dumps({
        "status": "PASS",
        "run_id": proof["run_id"],
        "private_delivery_status": proof["private_delivery_status"],
        "private_receipt_hash": proof["private_receipt_hash"],
        "safe_fingerprints": proof["safe_fingerprints"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
