from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from src.utils import DATA, ROOT

SLO_PATH = ROOT / "config" / "runtime" / "performance_slo.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(performance: dict[str, Any], slo: dict[str, Any], profile: str) -> dict[str, Any]:
    profiles = slo.get("profiles") or {}
    cfg = profiles.get(profile)
    if not isinstance(cfg, dict):
        raise RuntimeError(f"unknown runtime profile in SLO registry: {profile}")
    total = float(performance.get("total_wall_ms") or 0)
    target = float(cfg.get("target_wall_ms") or 0)
    warning = float(cfg.get("warning_wall_ms") or target)
    ceiling = float(cfg.get("legacy_ceiling_ms") or target)
    resources = performance.get("resources") or {}
    missing_resource_metrics = [
        key for key in ("peak_rss_kb", "child_peak_rss_kb", "temporary_bytes", "seed_input_bytes", "promoted_output_bytes")
        if resources.get(key) is None
    ]
    return {
        "profile": profile,
        "total_wall_ms": total,
        "target_wall_ms": target,
        "warning_wall_ms": warning,
        "legacy_ceiling_ms": ceiling,
        "within_target_slo": total <= target,
        "within_warning": total <= warning,
        "within_legacy_ceiling": total <= ceiling,
        "missing_resource_metrics": missing_resource_metrics,
        "resource_observability_complete": not missing_resource_metrics,
        "enforcement": cfg.get("enforcement"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--performance", default=str(DATA / "runtime_performance.json"))
    parser.add_argument("--profile", default=os.getenv("FPL_EXECUTION_PROFILE"))
    parser.add_argument("--enforce-target", action="store_true", default=os.getenv("FPL_ENFORCE_TARGET_SLO", "").lower() == "true")
    args = parser.parse_args()
    performance = _load(Path(args.performance))
    profile = str(args.profile or performance.get("execution_profile") or "full_refresh")
    result = evaluate(performance, _load(SLO_PATH), profile)
    print(json.dumps(result, ensure_ascii=False))
    if not result["resource_observability_complete"]:
        return 3
    if not result["within_legacy_ceiling"]:
        return 2
    if args.enforce_target and not result["within_target_slo"]:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
