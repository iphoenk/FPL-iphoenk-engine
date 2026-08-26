from __future__ import annotations

import json
from pathlib import Path

from src.rules import GOAL_POINTS, RULESET_ID, RULESET_SEASON, ruleset_metadata
from src.v5 import V5_VERSION
from src.v5.contracts import AcceptanceCheck, AcceptanceReport, Plane
from src.v5.module_registry import module_specs

ROOT = Path(__file__).resolve().parents[2]


def _json(path: str) -> dict:
    with (ROOT / path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def run_bootstrap_acceptance() -> AcceptanceReport:
    manifest = _json("config/v5_convergence_manifest.json")
    architecture = _json("config/v5_architecture_principles.json")
    projection_source = (ROOT / "src/models/projection.py").read_text(encoding="utf-8")
    metadata = ruleset_metadata()
    modules = module_specs()
    module_map = {m.name: m for m in modules}
    modular_policy = architecture.get("principles", {}).get("modular_authority", {})
    truth_modules = tuple(
        module_map.get(name)
        for name in (
            "rules",
            "source_authority",
            "public_api",
            "official_authenticated",
            "finance",
            "phase_state",
            "squad",
        )
    )

    checks = (
        AcceptanceCheck(
            "v5_manifest",
            manifest.get("version") == V5_VERSION,
            Plane.GOVERNANCE,
            "V5 package version matches convergence manifest",
        ),
        AcceptanceCheck(
            "v3_truth_baseline_declared",
            str(manifest.get("baselines", {}).get("production_truth", "")).startswith("v3"),
            Plane.TRUTH,
            "Production truth baseline remains explicitly V3",
        ),
        AcceptanceCheck(
            "v4_prediction_baseline_declared",
            manifest.get("baselines", {}).get("prediction_intelligence") == "v4-prediction-engine",
            Plane.INTELLIGENCE,
            "Prediction benchmark remains V4",
        ),
        AcceptanceCheck(
            "rules_registry_active",
            RULESET_ID == "FPL_2026_27" and RULESET_SEASON == "2026/27",
            Plane.TRUTH,
            "Verified 2026/27 ruleset is the active single authority",
        ),
        AcceptanceCheck(
            "goalkeeper_goal_rule",
            GOAL_POINTS.get(1) == 10,
            Plane.TRUTH,
            "Goalkeeper goal scoring is 10 points for 2026/27",
        ),
        AcceptanceCheck(
            "rules_fingerprint_present",
            bool(metadata.get("fingerprint_sha256")),
            Plane.GOVERNANCE,
            "Active ruleset exposes an auditable fingerprint",
        ),
        AcceptanceCheck(
            "projection_uses_rules_registry",
            "from src.rules import" in projection_source and "GOAL_POINTS" in projection_source,
            Plane.INTELLIGENCE,
            "Projection imports scoring constants from the unified rules authority",
        ),
        AcceptanceCheck(
            "no_legacy_goal_map_in_projection",
            "{1:6,2:6,3:5,4:4}" not in projection_source.replace(" ", ""),
            Plane.GOVERNANCE,
            "Legacy hardcoded goal-points map is absent from projection",
        ),
        AcceptanceCheck(
            "modular_separation_default",
            modular_policy.get("default_action") == "SEPARATE_WHEN_PRACTICAL",
            Plane.GOVERNANCE,
            "V5 defaults to dedicated modules/registries for separable domains",
        ),
        AcceptanceCheck(
            "module_registry_discoverable",
            len(modules) >= 10 and all(m.entrypoint and m.config and m.adjustment_surface for m in modules),
            Plane.GOVERNANCE,
            "Every registered V5 domain exposes entrypoint, config and adjustment surface",
        ),
        AcceptanceCheck(
            "truth_plane_authorities_active",
            all(
                m is not None
                and m.status == "ACTIVE"
                and not m.entrypoint.startswith("planned")
                and not m.config.startswith("planned")
                and (ROOT / m.config).exists()
                for m in truth_modules
            ),
            Plane.TRUTH,
            "Rules, public sources, authenticated Official, finance, phase-state and squad authorities are active",
        ),
        AcceptanceCheck(
            "production_promotion_locked",
            manifest.get("production_promotion", {}).get("allowed") is False,
            Plane.GOVERNANCE,
            "V5 alpha cannot replace V3 production before convergence acceptance",
        ),
    )
    return AcceptanceReport(version=V5_VERSION, checks=checks)


def main() -> int:
    report = run_bootstrap_acceptance()
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
