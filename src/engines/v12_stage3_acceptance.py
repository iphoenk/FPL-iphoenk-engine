from __future__ import annotations

"""Stage-3 integrated acceptance.

Evidence validator only. It does not compute football probabilities, alter QA,
repair V6, or create another decision authority.
"""

import argparse
import hashlib
import json
from datetime import datetime, timedelta
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



def _parse_aware(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _verified_s02_public_fallback(
    section: Mapping[str, Any],
    submitted: Mapping[str, Any],
    *,
    planning_gw: int,
    report_slot: str,
    expected_entry_id: int = 3462711,
) -> list[str]:
    """Prove submitted-squad identity; never upgrade to editable CURRENT15."""
    failures: list[str] = []
    content = dict(section.get("content") or {})
    authority = dict(content.get("current15_authority") or {})
    rows = [dict(r) for r in content.get("rows") or [] if isinstance(r, Mapping)]
    picks = [dict(p) for p in submitted.get("picks") or [] if isinstance(p, Mapping)]

    def check(ok: bool, code: str) -> None:
        if not ok:
            failures.append("S02_" + code)

    def ids(items: list[dict[str, Any]]) -> list[int]:
        out = []
        for row in items:
            try:
                out.append(int(row.get("element_id", row.get("element", 0))))
            except (TypeError, ValueError):
                out.append(0)
        return out

    row_ids, pick_ids = ids(rows), ids(picks)
    check(len(rows) == len(picks) == 15, "SUBMITTED_COUNT_INVALID")
    check(
        len(set(row_ids)) == 15 and min(row_ids or [0]) > 0
        and len(set(pick_ids)) == 15 and min(pick_ids or [0]) > 0,
        "SUBMITTED_DUPLICATE_OR_INVALID_PLAYER",
    )
    check(set(row_ids) == set(pick_ids), "OWNED_PLAYERS_NOT_BOUND_TO_PUBLIC_SOURCE")
    positions = [str(r.get("position") or "").upper() for r in rows]
    counts = {key: positions.count(key) for key in ("GK", "DEF", "MID", "FWD")}
    check(counts == {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}, "POSITION_DISTRIBUTION_INVALID")
    check(
        sum(p.get("captain") is True for p in picks) == 1
        and sum(p.get("vice_captain") is True for p in picks) == 1
        and not any(p.get("captain") and p.get("vice_captain") for p in picks),
        "CAPTAIN_VICE_INVALID",
    )
    check(
        sum(int(p.get("multiplier") or 0) > 0 for p in picks) == 11
        and sum(int(p.get("multiplier") or 0) == 0 for p in picks) == 4,
        "XI_BENCH_INVALID",
    )
    try:
        source_gw = int(submitted.get("gw"))
        displayed_gw = int(authority.get("applicable_gw"))
        report_gw = int(planning_gw)
    except (TypeError, ValueError):
        source_gw = displayed_gw = report_gw = -1
    check(
        source_gw in {report_gw, report_gw - 1}
        and displayed_gw == source_gw,
        "SOURCE_GW_MISMATCH",
    )
    check(
        int(submitted.get("entry_id") or -1) == expected_entry_id,
        "PUBLIC_TEAM_ID_MISMATCH",
    )
    check(
        str(authority.get("source_class") or "").upper() == "OFFICIAL_SUBMITTED_PICKS",
        "SOURCE_CLASS_NOT_OFFICIAL_SUBMITTED",
    )
    check(
        str(submitted.get("status") or "").upper() == "AVAILABLE",
        "PUBLIC_SOURCE_NOT_AVAILABLE",
    )
    lineage = dict(submitted.get("lineage") or {})
    check(
        lineage.get("authority") == "OFFICIAL_FPL"
        and lineage.get("endpoint_class") == "submitted_picks"
        and int(lineage.get("http_status") or 0) == 200
        and int(lineage.get("entry_id") or -1) == expected_entry_id
        and int(lineage.get("gw") or -1) == source_gw,
        "OFFICIAL_PROVENANCE_INVALID",
    )
    observed = _parse_aware(authority.get("observed_at"))
    generated = _parse_aware(submitted.get("generated_at"))
    slot = _parse_aware(report_slot)
    check(
        observed is not None and generated is not None and slot is not None
        and abs((observed - generated).total_seconds()) <= 5
        # The report_slot is logical. Governed acquisition can complete a few
        # minutes after it, without becoming future-dated or cross-occurrence.
        and generated <= slot + timedelta(minutes=15),
        "OBSERVATION_TIMESTAMP_INVALID",
    )
    check(
        authority.get("stale") is True,
        "PUBLIC_IDENTITY_MISREPRESENTED_AS_FRESH_CURRENT",
    )
    check(
        str(authority.get("finance_availability") or "").upper()
        not in {"AVAILABLE", "COMPLETE"},
        "PUBLIC_FINANCE_FABRICATED",
    )
    check(
        str(authority.get("resolution_status") or "").upper()
        != "CURRENT_VALID",
        "PUBLIC_EDITABLE_AUTHORITY_FABRICATED",
    )
    check(
        "authenticated-current" in str(section.get("degradation_reason") or "").lower(),
        "PUBLIC_AUTH_GAP_NOT_DISCLOSED",
    )
    return failures


def _verified_s05_pl_fixtures(
    section: Mapping[str, Any],
    official_payload: Mapping[str, Any],
    *,
    planning_gw: int,
) -> list[str]:
    """Cross-check degraded S05 PL rows against canonical Official V6 catalog."""
    failures: list[str] = []
    catalog = ((official_payload.get("official") or {}).get("fixtures") or [])
    official = [
        dict(row) for row in catalog
        if isinstance(row, Mapping) and row.get("event") == planning_gw
    ]
    rendered = [
        dict(row) for row in ((section.get("content") or {}).get("fixtures") or [])
        if isinstance(row, Mapping)
    ]

    def normalize(rows: list[dict[str, Any]]) -> dict[int, tuple[int, int, int, str]]:
        output = {}
        for row in rows:
            try:
                fixture = int(row["id"])
                home = int(row["team_h"])
                away = int(row["team_a"])
                event = int(row["event"])
            except (TypeError, ValueError, KeyError):
                failures.append("S05_PL_FIXTURE_IDENTITY_INVALID")
                continue
            if fixture <= 0 or home <= 0 or away <= 0 or home == away:
                failures.append("S05_PL_FIXTURE_IDENTITY_INVALID")
            if fixture in output:
                failures.append("S05_PL_FIXTURE_DUPLICATE")
            output[fixture] = (home, away, event, str(row.get("kickoff_time") or ""))
        return output

    expected = normalize(official)
    actual = normalize(rendered)
    if not official or not rendered:
        failures.append("S05_PL_FIXTURES_MISSING")
    if len(expected) != len(official) or len(actual) != len(rendered):
        failures.append("S05_PL_FIXTURE_CARDINALITY_INVALID")
    if actual != expected or any(row[2] != planning_gw for row in actual.values()):
        failures.append("S05_PL_FIXTURE_OFFICIAL_MISMATCH")
    coverage = dict((section.get("content") or {}).get("competition_coverage") or {})
    if coverage.get("official_pl") is not True:
        failures.append("S05_PL_AUTHORITY_NOT_COMPLETE")
    return sorted(set(failures))


def _truthful_source_degraded_sections(
    sections: Mapping[str, Mapping[str, Any]],
) -> tuple[set[str], list[str]]:
    """Return source-degraded sections that remain semantically acceptable.

    This never whitelists arbitrary DEGRADED output. S03 is allowed only when
    no prior visible DEEP survives the current semantic contract and no delta is
    invented. S05 is allowed only when PL truth is intact while optional
    verified non-PL schedule authority is absent.
    """
    allowed: set[str] = set()
    failures: list[str] = []

    s03 = dict(sections.get("S03") or {})
    if str(s03.get("state") or "").upper() == "DEGRADED":
        reason = str(s03.get("degradation_reason") or "").lower()
        delta = dict((s03.get("content") or {}).get("decision_delta") or {})
        truthful = (
            "previous valid visible deep baseline" in reason
            and "unavailable" in reason
            and str(delta.get("baseline_state") or "").upper() == "UNAVAILABLE"
            and str(delta.get("baseline_requirement") or "").upper()
            == "PREVIOUS_VALID_VISIBLE_DEEP"
            and not list(delta.get("rows") or [])
        )
        if truthful:
            allowed.add("S03")
        else:
            failures.append("S03_DEGRADED_NOT_TRUTHFUL_BASELINE_UNAVAILABILITY")

    s05 = dict(sections.get("S05") or {})
    if str(s05.get("state") or "").upper() == "DEGRADED":
        reason = str(s05.get("degradation_reason") or "").lower()
        coverage = dict((s05.get("content") or {}).get("competition_coverage") or {})
        truthful = (
            coverage.get("official_pl") is True
            and coverage.get("verified_non_pl_schedule_bound") is False
            and int(coverage.get("verified_non_pl_event_count") or 0) == 0
            and ("non-pl" in reason or "non pl" in reason)
            and ("not bound" in reason or "unavailable" in reason)
        )
        if truthful:
            allowed.add("S05")
        else:
            failures.append("S05_DEGRADED_NOT_TRUTHFUL_NON_PL_SOURCE_GAP")

    return allowed, failures


def validate(
    bundle: Mapping[str, Any],
    *,
    runtime_data_root: Path,
    private_data_root: Path | None = None,
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
    proof = dict(bundle.get("execution_proof") or {})
    require(
        str(proof.get("final_delivery_barrier_status") or "").upper() == "PASS",
        "FINAL_DELIVERY_BARRIER_NOT_PASS",
    )
    require(
        str((proof.get("final_delivery_barrier") or {}).get("status") or "").upper()
        == "PASS",
        "FINAL_DELIVERY_BARRIER_PROOF_NOT_PASS",
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

    degraded = {
        section_id
        for section_id, row in sections.items()
        if str(row.get("state") or "").upper() == "DEGRADED"
    }
    truthful_source_degraded, degradation_failures = (
        _truthful_source_degraded_sections(sections)
    )
    failures.extend(degradation_failures)
    if "S05" in degraded:
        try:
            official_catalog = _read(
                runtime_data_root / "data/v6/current/official_fpl.json"
            )
        except (OSError, ValueError, json.JSONDecodeError):
            official_catalog = {}
        failures.extend(_verified_s05_pl_fixtures(
            sections["S05"], official_catalog,
            planning_gw=int(bundle.get("planning_gw") or 0),
        ))
    # Public submitted picks are a valid identity fallback only when the
    # separately published Official FPL source agrees with every owned ID.
    # A generic DEGRADED S02, or a stale /my-team response, cannot pass.
    if "S02" in degraded:
        submitted_path = (
            (private_data_root / "personal/submitted_picks.json")
            if private_data_root is not None
            else (runtime_data_root / "data/v6/personal/submitted_picks.json")
        )
        try:
            submitted = _read(submitted_path)
        except (OSError, ValueError, json.JSONDecodeError):
            submitted = {}
        s02_failures = _verified_s02_public_fallback(
            sections["S02"],
            submitted,
            planning_gw=int(bundle.get("planning_gw") or 0),
            report_slot=str(bundle.get("report_slot") or ""),
        )
        if s02_failures:
            failures.extend(s02_failures)
        else:
            truthful_source_degraded.add("S02")
    allowed_degraded = {"S09"} | truthful_source_degraded
    require(
        degraded <= allowed_degraded,
        f"INTERNAL_SECTION_DEGRADED:{sorted(degraded - allowed_degraded)}",
    )
    if "S09" in degraded:
        reason = str((sections["S09"]).get("degradation_reason") or "").lower()
        chip_content = dict(sections["S09"].get("content") or {})
        require(
            ("authenticated" in reason or "private" in reason)
            and chip_content.get("chip") == "UNAVAILABLE"
            and chip_content.get("chip_ledger") == "UNAVAILABLE"
            and chip_content.get("chip_ledger_authority") == "UNAVAILABLE"
            and chip_content.get("considered_now") is False,
            "S09_DEGRADED_NOT_FAIL_CLOSED",
        )
    if "S02" in truthful_source_degraded:
        require(
            str(proof.get("stage3_action") or "") in {"WAIT", "PREPARE"},
            "S02_PUBLIC_FALLBACK_CANNOT_AUTHORIZE_ACT",
        )

    governance = dict(bundle.get("governance") or {})
    require(governance.get("v6_mutated") is False, "V6_MUTATED")
    require(governance.get("legacy_runtime_executed") is False, "LEGACY_EXECUTED")
    require(governance.get("second_methodology_created") is False, "SECOND_AUTHORITY")
    require(governance.get("qa_relaxed") is False, "QA_RELAXED")

    publish = _read(runtime_data_root / "data/v6/health/publish_integrity.json")
    prefetch = _read(runtime_data_root / "data/v6/report_prefetch/latest.json")
    prefetch_health = _read(runtime_data_root / "data/v6/health/report_prefetch.json")
    current_team = _read(
        (
            private_data_root / "personal/current_team.json"
            if private_data_root is not None
            else runtime_data_root / "data/v6/personal/current_team.json"
        )
    )
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
    auth_bound = (
        private_auth == "AUTH_AVAILABLE"
        and int(current_team.get("entry_id") or -1) == 3462711
        and (
            int(current_team.get("gw") or -1) == int(bundle.get("planning_gw") or -2)
            or int(current_team.get("editable_planning_gw") or -1)
            == int(bundle.get("planning_gw") or -2)
        )
    )
    private_auth_authority = (
        "AUTHENTICATED_CURRENT_TEAM" if auth_bound
        else "AUTH_AVAILABLE_BUT_NOT_BOUND" if private_auth == "AUTH_AVAILABLE"
        else private_auth
    )
    status = "PASS" if not failures else "FAIL"
    acceptance_class = (
        "INTEGRITY_FAIL" if failures
        else "VERIFIED_PUBLIC_FALLBACK" if "S02" in truthful_source_degraded
        else "AUTHENTICATED_BOUND" if auth_bound
        else "NON_AUTHENTICATED_ACCEPTANCE"
    )
    return {
        "contract": "V12_STAGE3_INTEGRATED_ACCEPTANCE_V1",
        "status": status,
        "acceptance_class": acceptance_class,
        "public_report_deliverable": (
            str((bundle.get("human_facing_qa") or {}).get("status") or "").upper() == "PASS"
        ),
        "private_auth_authority": private_auth_authority,
        "full_green_prod": False,
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
    parser.add_argument("--private-data-root", default="")
    parser.add_argument("--model-sha", required=True)
    parser.add_argument("--runtime-sha", required=True)
    parser.add_argument("--canonical", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    proof = validate(
        _read(Path(args.bundle)),
        runtime_data_root=Path(args.runtime_data_root),
        private_data_root=(
            Path(args.private_data_root)
            if args.private_data_root
            else None
        ),
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
