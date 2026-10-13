#!/usr/bin/env python3
"""Fail-closed deterministic sharding of the exact pre-repair V12 required suite.

The prior 51-file V12 suite is expanded to 52 required files and 1391 collected
pytest node IDs, including the reviewed provisional-fixture lifecycle and active-runner S02
history finality regression cases (13 Oct 2026) on top of the 1379-node baseline. No tests are
skipped, deselected, or replaced by subset fixtures.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

REQUIRED_FILES = [
    "tests/test_legacy_execution_isolation.py",
    "tests/test_active_native_p1_isolation.py",
    "tests/test_fpl_master_v12_decision_conformance.py",
    "tests/test_transfer_search_evidence_contract.py",
    "tests/test_player_comparator_orchestration.py",
    "tests/test_natural_deep_report_orchestration.py",
    "tests/test_natural_report_acceptance_observability.py",
    "tests/test_model_evidence_execution_binding.py",
    "tests/test_model_evidence_calibration.py",
    "tests/test_package_search_exact.py",
    "tests/test_package_utility_canonical.py",
    "tests/test_lineup_distributional_optimizer.py",
    "tests/test_p0_5_canonical_delivery_stage2.py",
    "tests/test_p0_5_scoring_integrity_stage3.py",
    "tests/test_tactical_role_canonical_scorer.py",
    "tests/test_contextual_player_dynamics.py",
    "tests/test_player_minutes_finite_state.py",
    "tests/test_player_events_posterior_predictive.py",
    "tests/test_integrated_report_runner.py",
    "tests/test_historical_performance_context.py",
    "tests/test_captain_goalkeeper_tail_review.py",
    "tests/test_captain_visible_provisional_baseline.py",
    "tests/test_lineup_watchlist_and_governance.py",
    "tests/test_stage3_upstream_diagnostics.py",
    "tests/test_delivery_reliability.py",
    "tests/test_match_mode_live_score_contract.py",
    "tests/test_public_match_delivery.py",
    "tests/test_deep_decision_content_delivery_barrier.py",
    "tests/test_p1_section_evidence_repair.py",
    "tests/test_s18_visible_route_summary.py",
    "tests/test_deep_rendered_schema_lock.py",
    "tests/test_price_delivery_barrier.py",
    "tests/test_stage1_analytics_foundation.py",
    "tests/test_monte_carlo_engine.py",
    "tests/test_cache_runtime_identity.py",
    "tests/test_cache_lineage_invalidation.py",
    "tests/test_cache_partial_change_contract.py",
    "tests/test_report_runtime_conformance.py",
    "tests/test_visible_content_proof.py",
    "tests/test_visible_report_content_contract.py",
    "tests/test_visible_report_ux_pause_action_state.py",
    "tests/test_personal_data_plane.py",
    "tests/test_private_delivery_security.py",
    "tests/test_private_publisher.py",
    "tests/test_native_content_remote_readback.py",
    "tests/test_data_platform_scheduler_authority.py",
    "tests/test_data_platform_scheduler_recovery_guard.py",
    "tests/test_data_platform_scheduler_watchdog.py",
    "tests/test_data_platform_scheduler_redundancy.py",
    "tests/test_delivery_schedule_policy.py",
    "tests/test_data_platform_precompute_control.py",
    "tests/test_runtime_cross_cpu_proof_registry.py"
]
BASELINE_TOTAL = 1391
CORE_SHARDS = tuple(f"core-{i:02}" for i in range(12))
HOT_SHARDS = (
    "hot-35", "hot-36-1207", "hot-36-4319", "hot-36-6471",
    "hot-37", "hot-38",
)
SHARDS = CORE_SHARDS + HOT_SHARDS


def collect() -> list[str]:
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", *REQUIRED_FILES]
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"Original complete V12 collection failed: {proc.returncode}")
    source = set(REQUIRED_FILES)
    nodes = [
        line.strip() for line in proc.stdout.splitlines()
        if line.strip().startswith("tests/")
        and "::" in line
        and line.strip().split("::", 1)[0] in source
    ]
    if len(nodes) != BASELINE_TOTAL:
        raise SystemExit(
            f"Fail closed: V12 original collected count {len(nodes)} "
            f"!= reviewed P1 expanded baseline {BASELINE_TOTAL}. "
            "Legitimate test additions require reviewing and updating baseline."
        )
    if len(nodes) != len(set(nodes)):
        raise SystemExit("Duplicate pytest node ID in original suite collection")
    observed_files = {node.split("::", 1)[0] for node in nodes}
    if observed_files != source:
        raise SystemExit(f"Required file selection drift: missing={source-observed_files} extra={observed_files-source}")
    return nodes


def which_shard(node: str) -> str:
    prefix = "tests/test_package_utility_canonical.py::"
    if node.startswith(prefix + "test_35_prepared_compact_bench_and_cvc_match_canonical_all_550_xi"):
        return "hot-35"
    if node.startswith(prefix + "test_36_prepared_p17_full_decision_matches_pre_repair_reference"):
        for seed in ("1207", "4319", "6471"):
            if node.endswith("[" + seed + "]"):
                return "hot-36-" + seed
        raise ValueError("Unexpected parameterization for exact reference comparison: " + node)
    if node.startswith(prefix + "test_37_prepared_p17_preserves_1_2_3_5gw_cumulative_outputs"):
        return "hot-37"
    if node.startswith(prefix + "test_38_prepared_exact_p17_has_material_runtime_margin"):
        return "hot-38"
    digest = sha256(node.encode("utf-8")).digest()
    return CORE_SHARDS[int.from_bytes(digest[:8], "big") % len(CORE_SHARDS)]


def manifest() -> tuple[dict[str, list[str]], list[str]]:
    original = collect()
    groups: dict[str, list[str]] = {label: [] for label in SHARDS}
    for node in original:
        groups[which_shard(node)].append(node)
    all_shards = [node for group in groups.values() for node in group]
    counts = Counter(all_shards)
    missing = set(original) - set(all_shards)
    additional = set(all_shards) - set(original)
    duplicate = [node for node, count in counts.items() if count != 1]
    if missing or additional or duplicate or len(all_shards) != len(original):
        raise SystemExit(
            f"Fail closed: missing={missing} additional={additional} "
            f"duplicates={duplicate} original={len(original)} union={len(all_shards)}"
        )
    if any(not group for group in groups.values()):
        raise SystemExit("Fail closed: empty mandatory V12 test shard")
    return groups, original


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("coverage", "run"))
    parser.add_argument("--shard", choices=SHARDS)
    parser.add_argument("--output", default="v12-shard-coverage.json")
    args = parser.parse_args()
    groups, original = manifest()
    evidence = {
        "schema": "FPL_V12_REQUIRED_TEST_SHARD_COVERAGE_V1",
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "original_required_file_count": len(REQUIRED_FILES),
        "original_collected_test_node_count": len(original),
        "union_count": sum(map(len, groups.values())),
        "duplicate_node_id_count": 0,
        "missing_node_id_count": 0,
        "shard_counts": {label: len(nodes) for label, nodes in groups.items()},
        "node_id_sha256": sha256("\n".join(sorted(original)).encode("utf-8")).hexdigest(),
        "status": "PASS",
    }
    Path(args.output).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps(evidence, sort_keys=True), flush=True)
    if args.mode == "coverage":
        return
    if not args.shard:
        raise SystemExit("Must supply --shard for execution")
    target = groups[args.shard]
    cpu = next(
        (line.partition(":")[2].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
         if line.startswith("model name")),
        platform.processor() or "unknown",
    )
    print(f"V12 SHARD {args.shard}: {len(target)} exact nodes on {cpu}", flush=True)
    junit = Path(f"v12-junit-{args.shard}.xml")
    t0 = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--durations=0",
         f"--junitxml={junit}", *target],
        check=False,
    )
    elapsed = time.perf_counter() - t0
    print(f"V12 SHARD {args.shard}: pytest exit={result.returncode} wall_seconds={elapsed:.3f} CPU={cpu}", flush=True)
    if result.returncode != 0:
        raise SystemExit(f"V12 shard failure: {args.shard} exit={result.returncode}")
    actual_cases = ET.parse(junit).findall(".//testcase")
    if len(actual_cases) != len(target):
        raise SystemExit(
            f"V12 shard JUnit coverage mismatch: {args.shard} "
            f"actual={len(actual_cases)} expected={len(target)}"
        )
    print(f"V12 SHARD {args.shard} VERIFIED: {len(actual_cases)} cases completed", flush=True)


if __name__ == "__main__":
    main()
