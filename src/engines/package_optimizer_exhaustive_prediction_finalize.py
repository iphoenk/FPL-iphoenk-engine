from __future__ import annotations

import json
import os

from src.engines.package_optimizer_exhaustive_accelerated import build_exhaustive
from src.utils import DATA, atomic_json, read_json

PROFILE = "exhaustive_precompute"


def run() -> dict:
    profile = str(os.getenv("FPL_EXECUTION_PROFILE") or "")
    if profile != PROFILE:
        return {"status": "SKIPPED", "reason": "PROFILE_NOT_EXHAUSTIVE_PRECOMPUTE", "profile": profile}

    projections = read_json(DATA / "projections.json", {})
    team = read_json(DATA / "team.json", {})
    if not projections or not team:
        raise RuntimeError("prediction-owned exhaustive finalizer requires projections.json and team.json")

    optimizer = build_exhaustive(projections, team)
    diagnostics = optimizer.get("search_diagnostics") or {}
    if (
        optimizer.get("status") != "READY"
        or diagnostics.get("search_authority") != "FULL"
        or diagnostics.get("lossy_pruning") is not False
        or diagnostics.get("all_step_legal_packages_scored") is not True
    ):
        raise RuntimeError("prediction-owned exhaustive finalizer refused non-FULL optimizer")

    optimizer.setdefault("governance", {}).update({
        "production_owner": "prediction",
        "execution_profile": PROFILE,
        "package_decision_writer": "lineup_governance",
        "finalizer_never_writes_package_decision": True,
    })
    atomic_json(DATA / "package_optimizer.json", optimizer)

    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {})["package_optimizer"] = "data/package_optimizer.json"
    intelligence = latest.setdefault("decision_intelligence", {})
    intelligence.update({
        "package_optimizer_status": optimizer.get("status"),
        "package_optimizer_search_authority": diagnostics.get("search_authority"),
        "package_optimizer_execution_profile": PROFILE,
        "package_count": optimizer.get("package_count", 0),
        "best_package": (optimizer.get("packages") or [{}])[0].get("id") if optimizer.get("packages") else None,
    })
    atomic_json(DATA / "latest.json", latest)
    return {
        "status": "READY",
        "profile": PROFILE,
        "search_authority": diagnostics.get("search_authority"),
        "package_count": optimizer.get("package_count"),
        "elapsed_ms": diagnostics.get("finalizer_elapsed_ms"),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
