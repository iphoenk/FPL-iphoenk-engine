from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.evaluation.baseline_provenance import assess_candidate_readiness, build_baseline_candidate


def _load(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a governed V3 production prediction-baseline candidate without freezing it.")
    parser.add_argument("--production-accuracy", required=True)
    parser.add_argument("--runtime-manifest", required=True)
    parser.add_argument("--output", default="data/v5/prediction_baseline_candidate.json")
    args = parser.parse_args()

    manifest = load_json_config("config/v5_convergence_manifest.json")
    baselines = manifest.get("baselines") if isinstance(manifest.get("baselines"), dict) else {}
    accepted_sha = str(baselines.get("production_main_sha") or "")
    production_accuracy = _load(args.production_accuracy)
    runtime_manifest = _load(args.runtime_manifest)
    candidate = build_baseline_candidate(production_accuracy, runtime_manifest, accepted_production_sha=accepted_sha)
    registry = load_json_config("config/v5_prediction_baseline_provenance.json")
    requirements = registry.get("source_requirements") if isinstance(registry.get("source_requirements"), dict) else {}
    readiness = assess_candidate_readiness(
        candidate,
        requirements,
        expected_production_sha=accepted_sha,
        expected_runtime_engine_version=str(runtime_manifest.get("engine_version") or "") or None,
    )
    payload = {
        "schema_version": 1,
        "contract": "V5_PREDICTION_BASELINE_CANDIDATE_V1",
        "candidate": candidate,
        "readiness": readiness,
        "governance": {
            "this_artifact_does_not_freeze_baseline": True,
            "explicit_governed_freeze_required": True,
            "not_ready_must_not_be_promoted": True,
        },
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
