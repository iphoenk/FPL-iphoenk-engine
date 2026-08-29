from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.evaluation.shadow_parity import compare
from src.v5.official_auth import expected_team_id
from src.v5.release_integrity import runtime_fingerprint
from src.v5.services.orchestrator_beta import handle as beta_handle

MANIFEST_CONFIG = "config/v5_convergence_manifest.json"
TRIGGER_CONFIG = "config/v5_shadow_trigger.json"


def _load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise RuntimeError(f"expected object in {path}")
    return data


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    tmp.replace(path)


def _ids(rows: Any) -> set[int]:
    return {int(row["element"]) for row in (rows or []) if isinstance(row, dict) and row.get("element") is not None}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _official_auth_checks(v5: dict[str, Any], team_id: int, *, required_predeadline: bool) -> tuple[dict[str, bool], dict[str, Any]]:
    phase = str((v5.get("phase") or {}).get("phase") or "")
    authority = str(v5.get("decision_squad_authority") or v5.get("squad_authority") or "")
    auth = v5.get("authenticated_official") if isinstance(v5.get("authenticated_official"), dict) else {}
    expected_entry = _int_or_none(auth.get("expected_entry")) or int(team_id)
    verified_entry = _int_or_none(auth.get("verified_entry"))
    draft = auth.get("draft_integrity") if isinstance(auth.get("draft_integrity"), dict) else {}
    requirement_active = bool(required_predeadline and phase == "PRE_DEADLINE")

    checks: dict[str, bool] = {
        "predeadline_authority_resolved": phase != "PRE_DEADLINE" or authority in {"official_authenticated", "user_lock"},
        "user_lock_fallback_only_when_auth_not_valid": (
            phase != "PRE_DEADLINE"
            or authority != "user_lock"
            or str(auth.get("state") or "") != "VALID"
        ),
    }
    if requirement_active:
        checks.update(
            {
                "official_authenticated_authority_pre_deadline": authority == "official_authenticated",
                "official_authenticated_state_valid_pre_deadline": str(auth.get("state") or "") == "VALID",
                "official_authenticated_entry_verified_pre_deadline": verified_entry == expected_entry == int(team_id),
                "official_authenticated_draft_matches_authoritative_squad": draft.get("matches_authoritative_squad") is True,
            }
        )

    proof = {
        "required_predeadline": bool(required_predeadline),
        "requirement_active": requirement_active,
        "phase": phase,
        "authority": authority,
        "auth_state": auth.get("state"),
        "expected_entry": expected_entry,
        "verified_entry": verified_entry,
        "draft_count": draft.get("count"),
        "draft_matches_authoritative_squad": draft.get("matches_authoritative_squad"),
        "raw_authenticated_payload_persisted": auth.get("raw_authenticated_payload_persisted"),
    }
    return checks, proof


def run(v3_latest_path: str, v3_lineup_path: str, output_dir: str, team_id: int) -> dict[str, Any]:
    v3_latest = _load(v3_latest_path)
    v3_lineup = _load(v3_lineup_path)
    # latest.json owns scoring/live squad truth; lineup_decision owns the planning
    # decision authority. Keep both so shadow parity never conflates the two.
    v3_reference = {
        **v3_latest,
        **v3_lineup,
        "squad_authority": v3_latest.get("squad_authority") or v3_lineup.get("squad_authority"),
        "decision_squad_authority": v3_lineup.get("squad_authority") or v3_latest.get("squad_authority"),
    }
    manifest = load_json_config(MANIFEST_CONFIG)
    trigger = load_json_config(TRIGGER_CONFIG)
    baselines = manifest.get("baselines") if isinstance(manifest.get("baselines"), dict) else {}
    release = runtime_fingerprint()

    v5 = beta_handle("run", {"mode": "daily", "team_id": team_id, "persist": True})
    if not isinstance(v5, dict):
        raise RuntimeError("V5 beta orchestrator returned a non-object")
    if not v5.get("ruleset_id"):
        v5["ruleset_id"] = ((v5.get("prediction_summary") or {}).get("ruleset_id"))
    v5["decision_squad_authority"] = v5.get("squad_authority")

    parity = compare(v3_reference, v5)
    generated_at = datetime.now(timezone.utc).isoformat()
    cycle_id = generated_at.replace(":", "").replace("+00:00", "Z").replace("-", "")
    v5_team = v5.get("team_summary") if isinstance(v5.get("team_summary"), dict) else {}
    owned_ids = [int(x) for x in (v5_team.get("owned_ids") or [])]
    decision = v5.get("decision_summary") if isinstance(v5.get("decision_summary"), dict) else {}
    lineup = decision.get("lineup") if isinstance(decision.get("lineup"), dict) else {}
    lineup_ids = _ids(lineup.get("starters")) | _ids(lineup.get("bench"))
    watch = v5.get("watchlist_summary") if isinstance(v5.get("watchlist_summary"), dict) else {}
    require_official_auth = bool(trigger.get("require_authenticated_official_predeadline", False))
    auth_checks, auth_proof = _official_auth_checks(v5, team_id, required_predeadline=require_official_auth)
    invariants = {
        "owned_exactly_15": len(owned_ids) == 15 and len(set(owned_ids)) == 15,
        "lineup_confined_to_owned": len(lineup_ids) == 15 and lineup_ids == set(owned_ids),
        "watchlist_exactly_20": int(watch.get("candidate_count") or 0) == 20,
        **auth_checks,
    }
    invariant_pass = all(invariants.values())
    cycle_pass = bool(parity.get("pass")) and invariant_pass
    post_status = "PENDING" if cycle_pass else "NOT_ELIGIBLE"

    result = {
        "schema_version": 7,
        "cycle_id": cycle_id,
        "generated_at": generated_at,
        "mode": "REAL_SHADOW",
        "production_remains_v3": True,
        "acceptance_context": {
            "production_baseline_version": baselines.get("production_truth"),
            "production_main_sha": baselines.get("production_main_sha"),
            "production_runtime_label": baselines.get("production_runtime"),
            "production_runtime_engine_version": v3_latest.get("engine_version"),
            "production_runtime_schema_version": v3_latest.get("schema_version"),
            "v5_version": v5.get("engine_version"),
            "release_fingerprint": release["fingerprint"],
            "release_fingerprint_contract": release["contract"],
            "release_fingerprint_files": release["files_hashed"],
            "official_auth_validation_required": require_official_auth,
            "official_auth_proof_contract": "V5_OFFICIAL_AUTH_SHADOW_PROOF_V1",
        },
        "post_validation": {"status": post_status, "validated_at": None, "validator_contract": "V5_REAL_SHADOW_POSTVALIDATION_V5"},
        "v3": {"engine_version": v3_latest.get("engine_version"), "generated_at": v3_latest.get("generated_at"), "planning_gw": (v3_latest.get("phase") or {}).get("planning_gw"), "formation": v3_lineup.get("formation"), "starting_xi": v3_lineup.get("starting_xi") or [], "captain": v3_lineup.get("captain"), "vice_captain": v3_lineup.get("vice_captain"), "ruleset_id": v3_lineup.get("ruleset_id"), "squad_authority": v3_reference.get("squad_authority"), "decision_squad_authority": v3_reference.get("decision_squad_authority")},
        "v5": {"engine_version": v5.get("engine_version"), "release_fingerprint": release["fingerprint"], "runner_status": v5.get("runner_status"), "planning_gw": (v5.get("phase") or {}).get("planning_gw"), "phase": (v5.get("phase") or {}).get("phase"), "squad_authority": v5.get("squad_authority"), "decision_squad_authority": v5.get("decision_squad_authority"), "owned_count": len(owned_ids), "owned_ids": owned_ids, "decision": decision, "watchlist": watch, "user_report": v5.get("user_report") or {}, "source_fusion_health": v5.get("source_fusion_health") or {}, "governance": v5.get("governance") or {}, "framework_health": v5.get("framework_health") or {}, "service_performance": v5.get("service_performance") or {}, "authenticated_official": v5.get("authenticated_official") or {}},
        "official_auth_proof": auth_proof,
        "parity": parity,
        "operational_invariants": {"pass": invariant_pass, "checks": invariants},
        "acceptance_progress": {"cycle_pass": cycle_pass, "required_real_cycles": int(parity.get("required_real_cycles") or 3), "real_cycle_recorded": True, "post_validation_required": True, "post_validation_status": post_status, "counts_as_successful_acceptance_cycle": False, "production_candidate_auto_promoted": False},
    }
    out = Path(output_dir)
    cycle_path = out / "cycles" / f"{cycle_id}.json"
    _atomic_write(cycle_path, result)
    _atomic_write(out / "latest_shadow_cycle.json", result)
    print(json.dumps({"cycle_id": cycle_id, "cycle_pass": cycle_pass, "post_validation_status": post_status, "parity_pass": parity.get("pass"), "official_auth_proof": auth_proof, "release_fingerprint": release["fingerprint"], "output": str(cycle_path)}, ensure_ascii=False))
    return result


def cli() -> None:
    parser = argparse.ArgumentParser(description="Run one real V3/V5 shadow cycle without promoting V5")
    parser.add_argument("--v3-latest", default=".shadow/v3_latest.json")
    parser.add_argument("--v3-lineup", default=".shadow/v3_lineup_decision.json")
    parser.add_argument("--output-dir", default="data/v5/shadow")
    parser.add_argument("--team-id", type=int, default=int(os.getenv("FPL_TEAM_ID") or expected_team_id()))
    args = parser.parse_args()
    run(args.v3_latest, args.v3_lineup, args.output_dir, args.team_id)


if __name__ == "__main__":
    cli()
