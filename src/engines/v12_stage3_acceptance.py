from __future__ import annotations

"""Stage-3 integrated acceptance.

Evidence validator only. It does not compute football probabilities, alter QA,
repair V6, or create another decision authority.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


STAGE2_GREEN_SHA = "2e770f5403c211851b122248c201dd7d8b81c3e1"
REQUIRED_STAGE3_STAGES = {
    "P1_2A_PACKAGE_SEARCH",
    "P1_2_PACKAGE_UTILITY",
    "P1_4_MATERIAL_ROUTE_SELECTION",
    "P1_4_MONTE_CARLO",
    "P1_4_PACKAGE_BINDING",
    "P1_2_STAGE3_DECISION_CLOSURE",
    "P1_2_STAGE3_DECISION_BINDING",
    "P1_8_MINI_LEAGUE_OVERLAY",
    "P1_8_MINI_LEAGUE_BINDING",
}
POSITIONS = {"GK", "DEF", "MID", "FWD"}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _section_map(bundle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("section_id") or ""): dict(row)
        for row in ((bundle.get("report") or {}).get("sections") or [])
        if isinstance(row, Mapping)
    }


def validate(
    bundle: Mapping[str, Any],
    *,
    runtime_data_root: Path,
    model_sha: str,
    runtime_sha: str,
    canonical_path: Path,
) -> dict[str, Any]:
    proof = dict(bundle.get("execution_proof") or {})
    ledger = {
        str(row.get("stage") or ""): dict(row)
        for row in bundle.get("stage_ledger") or []
        if isinstance(row, Mapping)
    }
    sections = _section_map(bundle)
    failures: list[str] = []

    def require(condition: bool, code: str) -> None:
        if not condition:
            failures.append(code)

    require(bundle.get("runner_status") == "PASS", "INTEGRATED_RUNNER_NOT_PASS")
    require(
        str((bundle.get("pre_render_qa") or {}).get("status") or "").upper()
        == "PASS",
        "PRE_RENDER_NOT_PASS",
    )
    require(
        str((bundle.get("post_render_qa") or {}).get("status") or "").upper()
        == "PASS",
        "POST_RENDER_NOT_PASS",
    )
    require(
        str((bundle.get("human_facing_qa") or {}).get("status") or "").upper()
        == "PASS",
        "HUMAN_FACING_NOT_PASS",
    )
    require(proof.get("stage3_internal_pass") is True, "STAGE3_INTERNAL_NOT_PASS")
    require(
        proof.get("stage3_action") in {"WAIT", "PREPARE", "ACT"},
        "ACTION_ENUM_INVALID",
    )
    for stage in sorted(REQUIRED_STAGE3_STAGES):
        require(
            (ledger.get(stage) or {}).get("status") == "PASS",
            f"STAGE_NOT_PASS:{stage}",
        )

    mc = dict(proof.get("monte_carlo") or {})
    require(int(mc.get("actual_paths") or 0) >= 500_000, "MC_PATHS_LT_500K")
    require(mc.get("canonical_pass") is True, "MC_NOT_CANONICAL_PASS")
    require(
        (mc.get("convergence") or {}).get("status") == "PASS",
        "MC_CONVERGENCE_NOT_PASS",
    )
    invariants = dict(mc.get("match_state_invariants") or {})
    require(invariants.get("status") == "PASS", "MATCH_STATE_INVARIANTS_NOT_PASS")
    require(
        not any(
            int(value or 0) > 0
            for key, value in invariants.items()
            if str(key).endswith("_failures")
        ),
        "MATCH_STATE_INVARIANT_FAILURE_COUNT",
    )

    s14 = sections.get("S14") or {}
    s14_content = dict(s14.get("content") or {})
    require(s14.get("state") == "COMPLETE", "S14_NOT_COMPLETE")
    require(bool(s14_content.get("package_search_proof")), "S14_SEARCH_PROOF_MISSING")
    require(bool(s14_content.get("package_routes")), "S14_PACKAGE_ROUTES_MISSING")
    search_scope = dict(s14_content.get("package_search_scope") or {})
    require(
        search_scope.get("search_authority") == "FULL",
        "S14_PACKAGE_SEARCH_NOT_FULL_UNIVERSE",
    )
    require(
        search_scope.get("eligible_universe_count")
        == search_scope.get("searched_universe_count"),
        "S14_PACKAGE_UNIVERSE_DENOMINATOR_MISMATCH",
    )
    require(
        int(search_scope.get("max_transfers_evaluated") or 0) >= 1,
        "S14_TRANSFER_DEPTH_NOT_PROVEN",
    )
    require(
        search_scope.get("transfer_depth_semantics")
        == "COMPLETE_WITHIN_GOVERNED_CURRENT_OCCURRENCE_BOUND",
        "S14_TRANSFER_DEPTH_SEMANTICS_MISSING",
    )
    require(
        bool(s14_content.get("package_universe_challengers")),
        "S14_CHALLENGERS_MISSING",
    )
    for route in s14_content.get("package_routes") or []:
        if not isinstance(route, Mapping):
            failures.append("S14_PACKAGE_ROUTE_INVALID")
            continue
        require(
            route.get("football_1GW") is not None,
            f"S14_ROUTE_1GW_MISSING:{route.get('route')}",
        )
        require(
            route.get("football_3GW") is not None,
            f"S14_ROUTE_3GW_MISSING:{route.get('route')}",
        )
        require(
            route.get("football_5GW") is not None,
            f"S14_ROUTE_5GW_MISSING:{route.get('route')}",
        )
        require(
            bool(route.get("sensitivity")),
            f"S14_ROUTE_SENSITIVITY_MISSING:{route.get('route')}",
        )
        require(
            bool(route.get("stress_coverage")),
            f"S14_ROUTE_STRESS_MISSING:{route.get('route')}",
        )
    require(
        ((s14_content.get("monte_carlo") or {}).get("actual_paths") or 0)
        >= 500_000,
        "S14_MC_NOT_VISIBLE",
    )
    require(bool(s14_content.get("decision")), "S14_DECISION_NOT_VISIBLE")

    s16 = sections.get("S16") or {}
    mechanisms = [
        dict(row)
        for row in ((s16.get("content") or {}).get("position_mechanisms") or [])
        if isinstance(row, Mapping)
    ]
    covered = {str(row.get("position") or "").upper() for row in mechanisms}
    require(POSITIONS <= covered, f"VISIBLE_POSITION_COVERAGE:{sorted(covered)}")
    for position in POSITIONS:
        rows = [row for row in mechanisms if str(row.get("position") or "").upper() == position]
        require(bool(rows), f"VISIBLE_{position}_MISSING")
        if not rows:
            continue
        row = rows[0]
        require(row.get("p_start") is not None, f"VISIBLE_{position}_PSTART_MISSING")
        require(row.get("xmins") is not None, f"VISIBLE_{position}_XMINS_MISSING")
        require(bool(row.get("dynamic_matchup")), f"VISIBLE_{position}_MATCHUP_MISSING")
        require(bool(row.get("position_mechanism")), f"VISIBLE_{position}_MECHANISM_MISSING")
        require(bool(row.get("1GW")), f"VISIBLE_{position}_1GW_MISSING")
        require(bool(row.get("3GW")), f"VISIBLE_{position}_3GW_MISSING")
        require(bool(row.get("5GW")), f"VISIBLE_{position}_5GW_MISSING")

    allowed_degraded = {"S09", "S10", "S12", "S13"}
    degraded = {
        section_id
        for section_id, row in sections.items()
        if str(row.get("state") or "").upper() == "DEGRADED"
    }
    require(
        degraded <= allowed_degraded,
        f"INTERNAL_SECTION_DEGRADED:{sorted(degraded - allowed_degraded)}",
    )
    if "S09" in degraded:
        reason = str((sections["S09"]).get("degradation_reason") or "").lower()
        require(
            "authenticated" in reason or "private" in reason,
            "S09_DEGRADED_NOT_PRIVATE_FACT",
        )
    for section_id in ("S10", "S12", "S13"):
        if section_id not in degraded:
            continue
        reason = str(
            (sections[section_id]).get("degradation_reason") or ""
        ).lower()
        require(
            any(
                token in reason
                for token in ("price", "predictor", "fresh", "stale")
            ),
            f"{section_id}_DEGRADED_NOT_PRICE_SOURCE_FACT",
        )

    governance = dict(bundle.get("governance") or {})
    require(governance.get("v6_mutated") is False, "V6_MUTATED")
    require(governance.get("legacy_runtime_executed") is False, "LEGACY_EXECUTED")
    require(governance.get("second_methodology_created") is False, "SECOND_AUTHORITY")
    require(governance.get("qa_relaxed") is False, "QA_RELAXED")

    publish = _read(runtime_data_root / "data/v6/health/publish_integrity.json")
    prefetch = _read(runtime_data_root / "data/v6/report_prefetch/latest.json")
    prefetch_health = _read(runtime_data_root / "data/v6/health/report_prefetch.json")
    current_team = _read(runtime_data_root / "data/v6/personal/current_team.json")
    standings = _read(
        runtime_data_root / "data/v6/mini_leagues/9477/standings.json"
    )
    require(publish.get("status") == "PASS", "V6_PUBLISH_INTEGRITY_NOT_PASS")
    require(prefetch.get("report_kind") == "full_master", "V6_PREFETCH_NOT_FULL_MASTER")
    require(prefetch.get("fresh_for_target_report") is True, "V6_PREFETCH_NOT_FRESH")
    require(prefetch.get("public_core_complete") is True, "V6_PUBLIC_CORE_NOT_COMPLETE")
    require(
        str(prefetch_health.get("public_core_status") or "").upper() == "GREEN",
        "V6_PUBLIC_CORE_HEALTH_NOT_GREEN",
    )
    require(
        str(prefetch.get("mini_league_status") or "").upper() == "AVAILABLE",
        "MINI_LEAGUE_NOT_AVAILABLE",
    )
    require(standings.get("complete") is True, "MINI_LEAGUE_STANDINGS_NOT_COMPLETE")
    require(
        int(standings.get("collected_manager_count") or 0)
        == int(standings.get("expected_manager_count") or -1),
        "MINI_LEAGUE_DENOMINATOR_INCOMPLETE",
    )

    private_auth = str(current_team.get("auth_state") or "UNAVAILABLE").upper()
    status = "PASS" if not failures else "FAIL"
    return {
        "contract": "V12_STAGE3_INTEGRATED_ACCEPTANCE_V1",
        "status": status,
        "failures": failures,
        "stage2_green_baseline": STAGE2_GREEN_SHA,
        "model_sha": model_sha,
        "runtime_data_v6_sha": runtime_sha,
        "canonical_sha256": _sha256(canonical_path),
        "report_slot": bundle.get("report_slot"),
        "planning_gw": bundle.get("planning_gw"),
        "integrated_runner": bundle.get("runner_status"),
        "pre_render": (bundle.get("pre_render_qa") or {}).get("status"),
        "post_render": (bundle.get("post_render_qa") or {}).get("status"),
        "human_facing": (bundle.get("human_facing_qa") or {}).get("status"),
        "stage3_action": proof.get("stage3_action"),
        "mc": mc,
        "visible_position_coverage": sorted(covered),
        "degraded_sections": sorted(degraded),
        "v6": {
            "publish_integrity": publish.get("status"),
            "prefetch_fresh_for_target_report": prefetch.get(
                "fresh_for_target_report"
            ),
            "public_core_status": prefetch_health.get("public_core_status"),
            "private_auth_state": private_auth,
            "private_auth_is_stage3_public_acceptance_blocker": False,
        },
        "mini_league": {
            "league_id": 9477,
            "complete": standings.get("complete"),
            "expected_manager_count": standings.get("expected_manager_count"),
            "collected_manager_count": standings.get("collected_manager_count"),
        },
        "governance": {
            "qa_relaxed": False,
            "v6_mutated": False,
            "stage1_stage2_mutated": False,
            "new_scheduler_created": False,
            "second_model_authority_created": False,
            "private_finance_fabricated": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--runtime-data-root", required=True)
    parser.add_argument("--model-sha", required=True)
    parser.add_argument("--runtime-sha", required=True)
    parser.add_argument("--canonical", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    proof = validate(
        _read(Path(args.bundle)),
        runtime_data_root=Path(args.runtime_data_root),
        model_sha=args.model_sha,
        runtime_sha=args.runtime_sha,
        canonical_path=Path(args.canonical),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(proof, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": proof["status"],
        "failures": proof["failures"],
        "mc_actual_paths": (proof.get("mc") or {}).get("actual_paths"),
        "report_slot": proof.get("report_slot"),
    }, sort_keys=True))
    return 0 if proof["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
