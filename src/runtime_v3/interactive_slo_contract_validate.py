from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.utils import ROOT

SLO_REGISTRY = ROOT / "config" / "runtime" / "performance_slo.json"
INSTANT_REGISTRY = ROOT / "config" / "runtime" / "instant_serving.json"
INTERACTIVE_REGISTRY = ROOT / "config" / "runtime" / "interactive_service_registry.json"
CANONICAL_SLO_PATH = "config/runtime/performance_slo.json"
PROFILE = "instant_serving"
DUPLICATE_NUMERIC_KEYS = {
    "preferred_end_to_end_target_ms",
    "hard_end_to_end_ceiling_ms",
    "preferred_target_ms",
    "hard_ceiling_ms",
    "target_wall_ms",
}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"registry must be an object: {path}")
    return payload


def run() -> dict[str, Any]:
    errors: list[str] = []
    slo = _load(SLO_REGISTRY)
    instant = _load(INSTANT_REGISTRY)
    interactive = _load(INTERACTIVE_REGISTRY)

    if slo.get("registry") != "RUNTIME_PERFORMANCE_SLO_V1":
        errors.append("unexpected canonical performance SLO registry")
    profile = ((slo.get("profiles") or {}).get(PROFILE) or {})
    target = float(profile.get("target_wall_ms") or 0)
    ceiling = float(profile.get("legacy_ceiling_ms") or 0)
    if target <= 0 or ceiling <= 0 or target > ceiling:
        errors.append("invalid canonical instant_serving SLO")

    instant_perf = instant.get("performance") if isinstance(instant.get("performance"), dict) else {}
    interactive_policy = interactive.get("policy") if isinstance(interactive.get("policy"), dict) else {}
    if instant_perf.get("slo_registry") != CANONICAL_SLO_PATH or instant_perf.get("slo_profile") != PROFILE:
        errors.append("instant_serving SLO pointer drift")
    if interactive_policy.get("performance_slo_registry") != CANONICAL_SLO_PATH or interactive_policy.get("performance_slo_profile") != PROFILE:
        errors.append("interactive service SLO pointer drift")

    for key in DUPLICATE_NUMERIC_KEYS:
        if key in instant_perf:
            errors.append(f"instant_serving duplicates canonical SLO number: {key}")
        if key in interactive_policy:
            errors.append(f"interactive policy duplicates canonical SLO number: {key}")
    for service, spec in (interactive.get("services") or {}).items():
        if not isinstance(spec, dict):
            errors.append(f"invalid interactive service spec: {service}")
            continue
        duplicated = sorted(DUPLICATE_NUMERIC_KEYS & set(spec))
        if duplicated:
            errors.append(f"interactive service {service} duplicates canonical SLO numbers: {duplicated}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "canonical_profile": PROFILE,
        "target_wall_ms": target,
        "hard_ceiling_ms": ceiling,
        "single_numeric_authority": not errors,
    }


def main() -> int:
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
