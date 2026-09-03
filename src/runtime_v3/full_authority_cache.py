from __future__ import annotations

import argparse
import json
from typing import Any

from src.runtime_v3 import incremental_reuse
from src.runtime_v3.publication_verify import EXHAUSTIVE_PROFILE, _verify_exhaustive_precompute_contract
from src.utils import DATA, atomic_json, read_json

AUTHORITY_SERVICE = "prediction"
AUTHORITY_REGISTRY = "V3_FULL_OPTIMIZER_AUTHORITY_V1"


def _record_full_prediction_fingerprint(profile: str) -> dict[str, Any]:
    current = incremental_reuse.fingerprint(AUTHORITY_SERVICE)
    if not current:
        raise RuntimeError("FULL optimizer authority fingerprint is unavailable")

    state = read_json(incremental_reuse.STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state["schema_version"] = 1
    state["registry"] = "V3_INCREMENTAL_REUSE_STATE_V1"
    optimizer = read_json(DATA / "package_optimizer.json", {})
    state.setdefault("services", {})[AUTHORITY_SERVICE] = {
        "fingerprint": current,
        "authority_registry": AUTHORITY_REGISTRY,
        "search_authority": "FULL",
        "recorded_profile": profile,
        "optimizer_generated_at": optimizer.get("generated_at"),
        "planning_gw": optimizer.get("planning_gw"),
        "ruleset_id": optimizer.get("ruleset_id"),
    }
    atomic_json(incremental_reuse.STATE_PATH, state)
    return {
        "fingerprint": current,
        "fingerprint_prefix": current[:12],
        "recorded": True,
    }


def verify_full_authority(profile: str) -> dict[str, Any]:
    """Fail closed unless the canonical runtime still carries truthful FULL authority.

    Exhaustive execution is allowed to establish a new exact prediction fingerprint
    only after the full optimizer -> package decision -> Gate0 -> framework ->
    watchlist chain has been validated. Non-exhaustive execution may publish only
    when that exact fingerprint still matches, proving the FULL prediction artifacts
    were reused against materially identical governed inputs.
    """

    assurance = _verify_exhaustive_precompute_contract(DATA)
    current = incremental_reuse.fingerprint(AUTHORITY_SERVICE)
    if not current:
        raise RuntimeError("current prediction fingerprint unavailable for FULL authority gate")

    if profile == EXHAUSTIVE_PROFILE:
        fingerprint_state = _record_full_prediction_fingerprint(profile)
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
        fingerprint_state = {
            "fingerprint": current,
            "fingerprint_prefix": current[:12],
            "recorded": False,
        }

    return {
        "status": "PASS",
        "registry": AUTHORITY_REGISTRY,
        "profile": profile,
        "search_authority": assurance.get("search_authority"),
        "lossy_pruning": assurance.get("lossy_pruning"),
        "gate0_pass": assurance.get("gate0_pass"),
        "framework": assurance.get("framework"),
        "decision_engine": assurance.get("decision_engine"),
        "watchlist_counts": assurance.get("watchlist_counts"),
        "watchlist_non_owned_unique": assurance.get("watchlist_non_owned_unique"),
        "selected_package_id": assurance.get("selected_package_id"),
        "prediction_fingerprint_prefix": fingerprint_state["fingerprint_prefix"],
        "fingerprint_recorded": fingerprint_state["recorded"],
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
