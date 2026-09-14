from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .wave3_proof import Wave3ProofError, evaluate_proof_window


def _read_proof(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Wave3ProofError(f"invalid_wave3_proof:{path}") from exc
    if not isinstance(payload, dict):
        raise Wave3ProofError(f"wave3_proof_not_object:{path}")
    return payload


def collect_proofs(proof_dir: Path, current: Path) -> list[dict[str, Any]]:
    proofs: list[dict[str, Any]] = []
    if proof_dir.exists():
        for path in sorted(proof_dir.glob("*.json")):
            proofs.append(_read_proof(path))
    proofs.append(_read_proof(current))
    return proofs


def build_window_summary(proof_dir: Path, current: Path) -> dict[str, Any]:
    summary = evaluate_proof_window(collect_proofs(proof_dir, current))
    summary["proof_source"] = "IMMUTABLE_WAVE3_ACTION_ARTIFACTS_PLUS_CURRENT"
    summary["manual_or_controlled_runs_count"] = 0
    summary["future_slots_inferred"] = False
    summary["production_green_policy"] = "ONLY_WHEN_ROLLING_48_OF_48_COMPLETE"
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate Wave 3 immutable natural-slot proofs")
    parser.add_argument("--proof-dir", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    summary = build_window_summary(args.proof_dir, args.current)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
