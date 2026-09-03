from __future__ import annotations

import argparse
import json
from typing import Any

from src.runtime_v3 import incremental_reuse
from src.utils import DATA, atomic_json, read_json

AUTHORITY_SERVICE = "prediction"
AUTHORITY_REGISTRY = "V3_FULL_OPTIMIZER_AUTHORITY_V1"
EXHAUSTIVE_PROFILE = "exhaustive_precompute"
WATCHLIST_POSITIONS = ("GK", "DEF", "MID", "FWD")


def _truthful_full_chain() -> dict[str, Any]:
    optimizer = read_json(DATA / "package_optimizer.json", {})
    diagnostics = optimizer.get("search_diagnostics") or {}
    required_false = (
        "lossy_pruning",
        "candidate_pruning_applied",
        "single_budget_applied",
        "pair_budget_applied",
        "exact_package_limit_applied",
    )
    if optimizer.get("status") != "READY" or diagnostics.get("search_authority") != "FULL":
        raise RuntimeError("runtime publication optimizer is not truthful FULL authority")
    if any(diagnostics.get(key) is not False for key in required_false):
        raise RuntimeError("runtime publication optimizer contains pruning/budget/cap authority")
    if diagnostics.get("all_step_legal_packages_scored") is not True:
        raise RuntimeError("runtime publication optimizer did not score every sequentially legal package")
    if diagnostics.get("watchlist_used_as_optimizer_input") is not False:
        raise RuntimeError("runtime publication optimizer used watchlist as optimizer input")

    package = read_json(DATA / "package_decision.json", {})
    if package.get("gate0_revalidated") is not True or package.get("current_squad_legal") is not True:
        raise RuntimeError("runtime publication package decision failed Gate0 revalidation")
    selectable = {str((optimizer.get("hold") or {}).get("id") or "")}
    selectable.update(str(row.get("id") or "") for row in optimizer.get("packages") or [] if isinstance(row, dict))
    if str(package.get("selected_package_id") or "") not in selectable:
        raise RuntimeError("runtime publication package decision is not derived from the FULL optimizer")

    framework = read_json(DATA / "framework_health.json", {})
    gate0 = framework.get("gate0") or {}
    if framework.get("overall") != "GREEN" or framework.get("decision_engine") != "HEALTHY":
        raise RuntimeError("runtime publication framework/decision health is not GREEN/HEALTHY")
    if gate0.get("pass") is not True or int((gate0.get("counts") or {}).get("PASS") or 0) != 16:
        raise RuntimeError("runtime publication Gate0 is not 16/16 PASS")

    team = read_json(DATA / "team.json", {})
    owned = {
        int(row.get("element") or -1)
        for row in (team.get("squad") or team.get("team_value_ledger") or [])
        if isinstance(row, dict) and int(row.get("element") or -1) > 0
    }
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    positions = watchlist.get("positions") or {}
    counts = {position: len(positions.get(position) or []) for position in WATCHLIST_POSITIONS}
    if counts != {position: 5 for position in WATCHLIST_POSITIONS}:
        raise RuntimeError(f"runtime publication watchlist is not exact 5x4: {counts}")
    watch_ids = [
        int(row.get("element") or -1)
        for position in WATCHLIST_POSITIONS
        for row in (positions.get(position) or [])
        if isinstance(row, dict)
    ]
    if len(watch_ids) != 20 or len(set(watch_ids)) != 20 or any(element <= 0 for element in watch_ids):
        raise RuntimeError("runtime publication watchlist does not contain 20 unique valid elements")
    if set(watch_ids) & owned:
        raise RuntimeError("runtime publication watchlist overlaps the owned squad")

    latest = read_json(DATA / "latest.json", {})
    intelligence = latest.get("decision_intelligence") or {}
    package_summary = latest.get("package_decision_summary") or {}
    if intelligence.get("package_optimizer_search_authority") != "FULL":
        raise RuntimeError("latest.json does not propagate FULL optimizer authority")
    if intelligence.get("package_optimizer_execution_profile") != EXHAUSTIVE_PROFILE:
        raise RuntimeError("latest.json lost exhaustive optimizer authority provenance")
    if package_summary.get("selected_package_id") != package.get("selected_package_id"):
        raise RuntimeError("latest.json package summary is inconsistent with package_decision.json")
    if package_summary.get("gate0_revalidated") is not True:
        raise RuntimeError("latest.json package summary lost Gate0 proof")

    return {
        "search_authority": "FULL",
        "lossy_pruning": False,
        "gate0_pass": 16,
        "framework": "GREEN",
        "decision_engine": "HEALTHY",
        "watchlist_counts": counts,
        "watchlist_non_owned_unique": True,
        "selected_package_id": package.get("selected_package_id"),
        "optimizer_generated_at": optimizer.get("generated_at"),
        "planning_gw": optimizer.get("planning_gw"),
        "ruleset_id": optimizer.get("ruleset_id"),
    }


def _record_full_prediction_fingerprint(profile: str, chain: dict[str, Any]) -> str:
    current = incremental_reuse.fingerprint(AUTHORITY_SERVICE)
    if not current:
        raise RuntimeError("FULL optimizer authority fingerprint is unavailable")
    state = read_json(incremental_reuse.STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state["schema_version"] = 1
    state["registry"] = "V3_INCREMENTAL_REUSE_STATE_V1"
    state.setdefault("services", {})[AUTHORITY_SERVICE] = {
        "fingerprint": current,
        "authority_registry": AUTHORITY_REGISTRY,
        "search_authority": "FULL",
        "recorded_profile": profile,
        "optimizer_generated_at": chain.get("optimizer_generated_at"),
        "planning_gw": chain.get("planning_gw"),
        "ruleset_id": chain.get("ruleset_id"),
    }
    atomic_json(incremental_reuse.STATE_PATH, state)
    return current


def verify_full_authority(profile: str) -> dict[str, Any]:
    """Protect rolling runtime publication from silent FULL -> PARTIAL downgrade."""
    chain = _truthful_full_chain()
    current = incremental_reuse.fingerprint(AUTHORITY_SERVICE)
    if not current:
        raise RuntimeError("current prediction fingerprint unavailable for FULL authority gate")

    recorded = False
    if profile == EXHAUSTIVE_PROFILE:
        current = _record_full_prediction_fingerprint(profile, chain)
        recorded = True
    else:
        stored = incremental_reuse.stored_fingerprint(AUTHORITY_SERVICE)
        if not stored:
            raise RuntimeError("non-exhaustive publication has no stored FULL prediction fingerprint")
        if stored != current:
            raise RuntimeError(
                "non-exhaustive publication would downgrade FULL optimizer authority: "
                f"stored={stored[:12]} current={current[:12]}"
            )
        row = ((read_json(incremental_reuse.STATE_PATH, {}) or {}).get("services") or {}).get(AUTHORITY_SERVICE) or {}
        if row.get("authority_registry") != AUTHORITY_REGISTRY or row.get("search_authority") != "FULL":
            raise RuntimeError("stored prediction fingerprint is not attested as FULL optimizer authority")

    return {
        "status": "PASS",
        "registry": AUTHORITY_REGISTRY,
        "profile": profile,
        "search_authority": chain["search_authority"],
        "lossy_pruning": chain["lossy_pruning"],
        "gate0_pass": chain["gate0_pass"],
        "framework": chain["framework"],
        "decision_engine": chain["decision_engine"],
        "watchlist_counts": chain["watchlist_counts"],
        "watchlist_non_owned_unique": chain["watchlist_non_owned_unique"],
        "selected_package_id": chain["selected_package_id"],
        "prediction_fingerprint_prefix": current[:12],
        "fingerprint_recorded": recorded,
        "non_exhaustive_requires_exact_full_fingerprint": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify and preserve V3 FULL optimizer authority")
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    print(json.dumps(verify_full_authority(str(args.profile)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
