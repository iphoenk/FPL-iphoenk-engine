from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one replacement in {relative}, found {count}: {old[:160]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def write(relative: str, content: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# 1) Exact core: deterministically partition only the OUTGOING package set.
core = "src/engines/v4_full_universe_package_search_core.py"
replace_once(
    core,
    '''    max_replacements: int | None = None,\n    top_per_size: int = 12,\n) -> dict:\n''',
    '''    max_replacements: int | None = None,\n    top_per_size: int = 12,\n    outgoing_shard_index: int = 0,\n    outgoing_shard_count: int = 1,\n) -> dict:\n''',
)
replace_once(
    core,
    '''    if max_replacements < 1:\n        raise ValueError("full-universe package search requires at least one transfer package size")\n\n    reconciled, affordability = reconcile_owned_costs(candidates, locked)\n''',
    '''    if max_replacements < 1:\n        raise ValueError("full-universe package search requires at least one transfer package size")\n    outgoing_shard_count = int(outgoing_shard_count)\n    outgoing_shard_index = int(outgoing_shard_index)\n    if outgoing_shard_count < 1 or not 0 <= outgoing_shard_index < outgoing_shard_count:\n        raise ValueError("invalid outgoing shard index/count")\n\n    reconciled, affordability = reconcile_owned_costs(candidates, locked)\n''',
)
replace_once(
    core,
    '''        "potential_cutoff_diagnostics": [],\n    }\n''',
    '''        "potential_cutoff_diagnostics": [],\n        "outgoing_shard_index": outgoing_shard_index,\n        "outgoing_shard_count": outgoing_shard_count,\n        "outgoing_jobs_total": 0,\n        "outgoing_jobs_selected": 0,\n        "outgoing_job_keys": [],\n    }\n''',
)
replace_once(
    core,
    '''        for outs_raw in combinations(current, k):\n            outs = tuple(sorted(outs_raw, key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element)))\n            out_ids = tuple(sorted(player.element for player in outs))\n            keep = tuple(player for player in current if player.element not in set(out_ids))\n''',
    '''        for outs_raw in combinations(current, k):\n            outs = tuple(sorted(outs_raw, key=lambda row: (_POSITION_ORDER.get(row.position, 99), row.element)))\n            out_ids = tuple(sorted(player.element for player in outs))\n            job_ordinal = diagnostics["outgoing_jobs_total"]\n            diagnostics["outgoing_jobs_total"] += 1\n            if job_ordinal % outgoing_shard_count != outgoing_shard_index:\n                continue\n            diagnostics["outgoing_jobs_selected"] += 1\n            diagnostics["outgoing_job_keys"].append(f"{k}:" + ",".join(str(element) for element in out_ids))\n            keep = tuple(player for player in current if player.element not in set(out_ids))\n''',
)
replace_once(
    core,
    '''    global_proof = (\n        not bool(search_cfg.get("allow_heuristic_candidate_cutoff"))\n        and not bool(search_cfg.get("allow_beam_cutoff"))\n        and all(proof.get("safe_legality_equivalence") is True for proof in pruning_proofs)\n    )\n    search_state = str(search_cfg.get("full_universe_proven_state") or "FULL_UNIVERSE_PROVEN") if global_proof else str(search_cfg.get("heuristic_state") or "FULL_UNIVERSE_HEURISTIC")\n''',
    '''    full_outgoing_space = outgoing_shard_count == 1\n    global_proof = (\n        full_outgoing_space\n        and not bool(search_cfg.get("allow_heuristic_candidate_cutoff"))\n        and not bool(search_cfg.get("allow_beam_cutoff"))\n        and all(proof.get("safe_legality_equivalence") is True for proof in pruning_proofs)\n    )\n    if not full_outgoing_space:\n        search_state = "SHARD_PARTIAL_EXACT"\n    else:\n        search_state = str(search_cfg.get("full_universe_proven_state") or "FULL_UNIVERSE_PROVEN") if global_proof else str(search_cfg.get("heuristic_state") or "FULL_UNIVERSE_HEURISTIC")\n''',
)
replace_once(
    core,
    '''            "maximum_replacements": max_replacements,\n            "safe_pruning_rule": "SAME_TEAM_SAME_POSITION_PARETO_DOMINANCE",\n''',
    '''            "maximum_replacements": max_replacements,\n            "outgoing_shard_index": outgoing_shard_index,\n            "outgoing_shard_count": outgoing_shard_count,\n            "full_outgoing_space_in_this_result": full_outgoing_space,\n            "safe_pruning_rule": "SAME_TEAM_SAME_POSITION_PARETO_DOMINANCE",\n''',
)

# 2) Public facade: shard results remain explicit non-authoritative diagnostics;
# only fan-in may assert FULL_UNIVERSE_PROVEN.
facade = "src/engines/v4_full_universe_package_search.py"
replace_once(
    facade,
    '''    max_replacements: int | None = None,\n    top_per_size: int = 12,\n) -> dict:\n''',
    '''    max_replacements: int | None = None,\n    top_per_size: int = 12,\n    outgoing_shard_index: int = 0,\n    outgoing_shard_count: int = 1,\n) -> dict:\n''',
)
replace_once(
    facade,
    '''                max_replacements=max_replacements,\n                top_per_size=top_per_size,\n            )\n''',
    '''                max_replacements=max_replacements,\n                top_per_size=top_per_size,\n                outgoing_shard_index=outgoing_shard_index,\n                outgoing_shard_count=outgoing_shard_count,\n            )\n''',
)
replace_once(
    facade,
    '''    global_proof = configured_exact and all_safe\n    search.update({\n        "status": "FULL_UNIVERSE_PROVEN" if global_proof else "FULL_UNIVERSE_HEURISTIC",\n''',
    '''    shard_partial = int(outgoing_shard_count) > 1\n    global_proof = configured_exact and all_safe and not shard_partial\n    search.update({\n        "status": "SHARD_PARTIAL_EXACT" if shard_partial else ("FULL_UNIVERSE_PROVEN" if global_proof else "FULL_UNIVERSE_HEURISTIC"),\n''',
)
replace_once(
    facade,
    '''    if not global_proof:\n        (out.get("efficient_frontier") or {})["status"] = "PARTIAL"\n    return _apply_authority_gate(out, global_proof=global_proof)\n''',
    '''    if shard_partial:\n        (out.get("efficient_frontier") or {})["status"] = "SHARD_PARTIAL"\n        search["authoritative_for_recommendation"] = False\n        out["decision_authority"] = "SHARD_PARTIAL_NO_AUTHORITY"\n        out.setdefault("governance", {})["fan_in_required_for_global_authority"] = True\n        out["governance"]["shard_result_must_never_be_served"] = True\n        return out\n    if not global_proof:\n        (out.get("efficient_frontier") or {})["status"] = "PARTIAL"\n    return _apply_authority_gate(out, global_proof=global_proof)\n''',
)

# 3) Exact fan-in merge. Mathematical basis:
# global top-N is contained in union(local top-N), and global Pareto frontier is
# contained in union(local Pareto frontiers) for a disjoint partition of rows.
write(
    "src/engines/v4_full_universe_package_shard_merge.py",
    '''from __future__ import annotations\n\nimport copy\nimport json\nfrom hashlib import sha256\nfrom typing import Iterable\n\nfrom src.engines import v4_full_universe_package_search_core as core\n\nCONTRACT = "V4_EXACT_PACKAGE_SHARD_MERGE_V1"\n\n\ndef _stable_digest(value) -> str:\n    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")\n    return sha256(raw).hexdigest()\n\n\ndef _common_signature(result: dict) -> dict:\n    search = result.get("search") or {}\n    return {\n        "contract": result.get("contract"),\n        "baseline": result.get("baseline"),\n        "roll_baseline": result.get("roll_baseline"),\n        "affordability": result.get("affordability"),\n        "pruning_proofs": search.get("pruning_proofs") or [],\n        "proof_minimize_dimensions": search.get("proof_minimize_dimensions") or [],\n        "proof_maximize_dimensions": search.get("proof_maximize_dimensions") or [],\n        "maximum_replacements": search.get("maximum_replacements"),\n    }\n\n\ndef merge_exact_package_shards(results: Iterable[dict], *, top_per_size: int = 12) -> dict:\n    shards = list(results)\n    if not shards:\n        raise RuntimeError("no exact package shards supplied")\n    counts = {int((row.get("search") or {}).get("outgoing_shard_count") or 0) for row in shards}\n    if len(counts) != 1 or next(iter(counts)) < 2:\n        raise RuntimeError("fan-in requires one declared multi-shard count")\n    shard_count = next(iter(counts))\n    indexes = sorted(int((row.get("search") or {}).get("outgoing_shard_index") or -1) for row in shards)\n    if indexes != list(range(shard_count)):\n        raise RuntimeError(f"incomplete shard indexes: {indexes} expected 0..{shard_count - 1}")\n    if any((row.get("search") or {}).get("status") != "SHARD_PARTIAL_EXACT" for row in shards):\n        raise RuntimeError("fan-in received non-exact or already-authoritative shard")\n    if any((row.get("search") or {}).get("authoritative_for_recommendation") is not False for row in shards):\n        raise RuntimeError("shard authority contract violated")\n\n    common = _common_signature(shards[0])\n    common_digest = _stable_digest(common)\n    if any(_stable_digest(_common_signature(row)) != common_digest for row in shards[1:]):\n        raise RuntimeError("shard semantic/pruning baseline mismatch")\n\n    all_job_keys: list[str] = []\n    totals = set()\n    for row in shards:\n        diagnostics = (row.get("search") or {}).get("diagnostics") or {}\n        totals.add(int(diagnostics.get("outgoing_jobs_total") or 0))\n        keys = list(diagnostics.get("outgoing_job_keys") or [])\n        if len(keys) != int(diagnostics.get("outgoing_jobs_selected") or -1):\n            raise RuntimeError("shard outgoing coverage count mismatch")\n        all_job_keys.extend(keys)\n    if len(totals) != 1:\n        raise RuntimeError("shards disagree on total outgoing job count")\n    expected_total = next(iter(totals))\n    if len(all_job_keys) != len(set(all_job_keys)):\n        raise RuntimeError("outgoing shard partitions overlap")\n    if len(all_job_keys) != expected_total:\n        raise RuntimeError(f"outgoing shard coverage incomplete: {len(all_job_keys)} != {expected_total}")\n\n    maximum = int((shards[0].get("search") or {}).get("maximum_replacements") or 3)\n    top_by_k = {k: [] for k in range(1, maximum + 1)}\n    for shard in shards:\n        for row in shard.get("packages") or []:\n            k = int(row.get("replacements") or 0)\n            if k in top_by_k:\n                core._retain_top(top_by_k[k], row, top_per_size)\n    best_by_k = {str(k): (rows[0] if rows else None) for k, rows in top_by_k.items()}\n\n    roll = copy.deepcopy(shards[0].get("roll_baseline") or {})\n    epsilon = float(((shards[0].get("efficient_frontier") or {}).get("dominance_epsilon") or 0.01))\n    frontier: list[dict] = []\n    seen_ids: set[str] = set()\n    for shard in shards:\n        for row in (shard.get("efficient_frontier") or {}).get("rows") or []:\n            package_id = str(row.get("package_id") or "")\n            if package_id in seen_ids:\n                continue\n            seen_ids.add(package_id)\n            core._frontier_insert(frontier, copy.deepcopy(row), epsilon)\n    frontier.sort(key=core._rank, reverse=True)\n\n    packages = [row for k in range(1, maximum + 1) for row in top_by_k[k]]\n    best_candidates = [row for row in best_by_k.values() if row]\n    recommended = max(best_candidates, key=core._rank) if best_candidates else None\n    if recommended and core._f(recommended.get("adjusted_utility_gain_5")) <= 0:\n        recommended = None\n    overall = (recommended or roll).get("classification") or "ROLL_BASELINE"\n    categories = core._frontier_categories(frontier, roll)\n\n    first_search = shards[0].get("search") or {}\n    proof_flags = (\n        all((row.get("search") or {}).get("proof_covers_package_frontier_risk_confidence") is True for row in shards)\n        and all((row.get("search") or {}).get("proof_covers_projected_affordability") is True for row in shards)\n        and all((row.get("search") or {}).get("proof_covers_recommendation_sanity") is True for row in shards)\n        and all(not bool((row.get("search") or {}).get("heuristic_candidate_cutoff")) for row in shards)\n        and all(not bool((row.get("search") or {}).get("beam_cutoff")) for row in shards)\n    )\n    global_proof = proof_flags and len(all_job_keys) == expected_total\n    if not global_proof:\n        raise RuntimeError("fan-in cannot prove exact full-universe coverage")\n\n    diagnostics = copy.deepcopy(first_search.get("diagnostics") or {})\n    sum_keys = (\n        "search_nodes", "incoming_combinations_considered", "packages_evaluated",\n        "packages_rejected_by_budget", "packages_rejected_by_budget_bound",\n        "packages_rejected_by_club_limit", "packages_rejected_by_legality",\n        "packages_dominated_on_frontier",\n    )\n    for key in sum_keys:\n        diagnostics[key] = sum(int(((row.get("search") or {}).get("diagnostics") or {}).get(key) or 0) for row in shards)\n    diagnostics.update({\n        "workflow_shard_count": shard_count,\n        "outgoing_jobs_total": expected_total,\n        "outgoing_jobs_selected": expected_total,\n        "outgoing_job_keys": sorted(all_job_keys),\n        "packages_retained_on_frontier": len(frontier),\n        "shard_indexes_covered": indexes,\n        "shard_partitions_disjoint": True,\n        "shard_partitions_complete": True,\n    })\n\n    out = copy.deepcopy(shards[0])\n    out["overall_verdict"] = overall\n    out["recommended_package"] = recommended\n    out["best_by_replacement_count"] = best_by_k\n    out["packages"] = packages\n    out["efficient_frontier"] = {\n        "status": "PASS",\n        "dominance_epsilon": epsilon,\n        "rows": frontier,\n        "categories": categories,\n        "maximize": (shards[0].get("efficient_frontier") or {}).get("maximize") or [],\n        "minimize": (shards[0].get("efficient_frontier") or {}).get("minimize") or [],\n    }\n    search = out.setdefault("search", {})\n    search.update({\n        "status": "FULL_UNIVERSE_PROVEN",\n        "authoritative_for_recommendation": True,\n        "global_optimality_guaranteed_under_declared_package_semantics": True,\n        "workflow_fan_in_contract": CONTRACT,\n        "outgoing_shard_index": None,\n        "outgoing_shard_count": shard_count,\n        "full_outgoing_space_in_this_result": True,\n        "diagnostics": diagnostics,\n    })\n    out["decision_authority"] = "ENGINE_ADVISORY_ONLY_FULL_UNIVERSE_PROVEN"\n    out.setdefault("governance", {}).update({\n        "workflow_shards_are_never_authoritative": True,\n        "fan_in_is_single_global_authority": True,\n        "shard_partition_disjointness_proven": True,\n        "shard_partition_completeness_proven": True,\n        "global_topn_from_union_local_topn_exact": True,\n        "global_frontier_from_union_local_frontiers_exact": True,\n    })\n    return out\n''',
)

# 4) Shard worker service. It never writes canonical package outputs.
write(
    "src/services/package_optimization_shard_service.py",
    '''from __future__ import annotations\n\nimport json\nimport os\nfrom pathlib import Path\nfrom time import perf_counter\n\nfrom src.engines.v4_decision_pipeline import _semantic_fingerprint, effective_planning_squad\nfrom src.engines.v4_full_universe_package_search import search_full_universe_packages\nfrom src.engines.v4_package_artifact_contract import current_input_digests\nfrom src.engines.v4_tactical_interaction import build_tactical_interactions\nfrom src.engines.v4_wc_optimizer import build_candidates\nfrom src.utils import CONFIG, DATA, atomic_json, iso_now, read_json\n\nCONTRACT = "V4_EXACT_PACKAGE_WORKFLOW_SHARD_V1"\n\n\ndef run(index: int | None = None, count: int | None = None) -> dict:\n    index = int(os.environ.get("V4_PACKAGE_SHARD_INDEX", "0") if index is None else index)\n    count = int(os.environ.get("V4_PACKAGE_SHARD_COUNT", "1") if count is None else count)\n    if count < 2 or not 0 <= index < count:\n        raise RuntimeError("workflow shard service requires count >=2 and valid index")\n    started = perf_counter()\n    input_before = current_input_digests()\n    predictions = read_json(DATA / "predictions_v4.json", {}) or {}\n    universe = read_json(DATA / "universe.json", {}) or {}\n    team = read_json(DATA / "team.json", {}) or {}\n    latest = read_json(DATA / "latest.json", {}) or {}\n    prices = read_json(DATA / "prices.json", {}) or {}\n    understat = read_json(DATA / "understat_tactical_v4.json", {}) or {}\n    configured_lock = read_json(CONFIG / "locked_squad.json", {}) or {}\n    locked = effective_planning_squad(team, configured_lock, latest)\n    candidates = build_candidates(predictions, universe)\n    tactical = build_tactical_interactions(predictions, universe, understat)\n    semantic = _semantic_fingerprint(\n        predictions, universe, locked, understat, candidates=candidates,\n        tactical_interactions=tactical, prices=prices,\n    )\n    result = search_full_universe_packages(\n        candidates, locked, predictions=predictions, universe=universe, understat=understat,\n        interactions=tactical, prices=prices, max_replacements=3,\n        outgoing_shard_index=index, outgoing_shard_count=count,\n    )\n    search = result.get("search") or {}\n    if search.get("status") != "SHARD_PARTIAL_EXACT" or search.get("authoritative_for_recommendation") is not False:\n        raise RuntimeError("workflow shard improperly claimed global authority")\n    if result.get("decision_authority") != "SHARD_PARTIAL_NO_AUTHORITY":\n        raise RuntimeError("workflow shard authority label mismatch")\n    input_after = current_input_digests()\n    if input_before != input_after:\n        raise RuntimeError("workflow shard inputs changed during exact search")\n    duration_ms = round((perf_counter() - started) * 1000.0, 2)\n    wrapper = {\n        "schema_version": 1,\n        "contract": CONTRACT,\n        "generated_at": iso_now(),\n        "shard_index": index,\n        "shard_count": count,\n        "duration_ms": duration_ms,\n        "semantic_fingerprint": semantic,\n        "input_sha256": input_before,\n        "result": result,\n        "guardrails": {\n            "authoritative": False,\n            "full_universe_status_forbidden": True,\n            "no_candidate_cutoff": True,\n            "no_beam_cutoff": True,\n            "fan_in_required": True,\n        },\n    }\n    out = DATA / "package_shards" / f"shard-{index:02d}.json"\n    out.parent.mkdir(parents=True, exist_ok=True)\n    atomic_json(out, wrapper)\n    print(json.dumps({\n        "service": "package_optimization_shard", "index": index, "count": count,\n        "duration_ms": duration_ms,\n        "outgoing_jobs": (search.get("diagnostics") or {}).get("outgoing_jobs_selected"),\n        "packages_evaluated": (search.get("diagnostics") or {}).get("packages_evaluated"),\n    }))\n    return wrapper\n\n\nif __name__ == "__main__":\n    run()\n''',
)

# 5) Fan-in service is the sole creator of canonical exact package + manifest.
write(
    "src/services/package_optimization_merge_service.py",
    '''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\nfrom time import perf_counter\n\nfrom src.engines.v4_decision_pipeline import _semantic_fingerprint, effective_planning_squad\nfrom src.engines.v4_full_universe_package_shard_merge import merge_exact_package_shards\nfrom src.engines.v4_package_artifact_contract import (\n    CONTRACT as MANIFEST_CONTRACT, MANIFEST_OUTFILE, PACKAGE_OUTFILE,\n    TACTICAL_INTERACTION_OUTFILE, current_input_digests,\n)\nfrom src.engines.v4_tactical_interaction import build_tactical_interactions\nfrom src.engines.v4_wc_optimizer import build_candidates\nfrom src.services.contracts import file_digest\nfrom src.utils import CONFIG, DATA, atomic_json, iso_now, read_json\n\nSHARD_CONTRACT = "V4_EXACT_PACKAGE_WORKFLOW_SHARD_V1"\n\n\ndef run() -> dict:\n    started = perf_counter()\n    files = sorted((DATA / "package_shards").glob("shard-*.json"))\n    if not files:\n        raise RuntimeError("no package shard artifacts found")\n    wrappers = [read_json(path, {}) or {} for path in files]\n    if any(row.get("contract") != SHARD_CONTRACT for row in wrappers):\n        raise RuntimeError("invalid package shard contract")\n    counts = {int(row.get("shard_count") or 0) for row in wrappers}\n    if len(counts) != 1 or len(wrappers) != next(iter(counts)):\n        raise RuntimeError("package shard artifact count incomplete")\n\n    predictions = read_json(DATA / "predictions_v4.json", {}) or {}\n    universe = read_json(DATA / "universe.json", {}) or {}\n    team = read_json(DATA / "team.json", {}) or {}\n    latest = read_json(DATA / "latest.json", {}) or {}\n    prices = read_json(DATA / "prices.json", {}) or {}\n    understat = read_json(DATA / "understat_tactical_v4.json", {}) or {}\n    configured_lock = read_json(CONFIG / "locked_squad.json", {}) or {}\n    locked = effective_planning_squad(team, configured_lock, latest)\n    candidates = build_candidates(predictions, universe)\n    tactical = build_tactical_interactions(predictions, universe, understat)\n    semantic = _semantic_fingerprint(\n        predictions, universe, locked, understat, candidates=candidates,\n        tactical_interactions=tactical, prices=prices,\n    )\n    if any(row.get("semantic_fingerprint") != semantic for row in wrappers):\n        raise RuntimeError("package shard semantic fingerprint drift")\n    current_raw = current_input_digests()\n    if any(row.get("input_sha256") != current_raw for row in wrappers):\n        raise RuntimeError("package shard raw provenance drift")\n\n    package = merge_exact_package_shards([row.get("result") or {} for row in wrappers])\n    atomic_json(TACTICAL_INTERACTION_OUTFILE, tactical)\n    atomic_json(PACKAGE_OUTFILE, package)\n    merge_ms = round((perf_counter() - started) * 1000.0, 2)\n    shard_durations = [float(row.get("duration_ms") or 0.0) for row in wrappers]\n    manifest = {\n        "schema_version": 2,\n        "contract": MANIFEST_CONTRACT,\n        "generated_at": iso_now(),\n        "status": "PASS",\n        "slo_status": "PASS",\n        "duration_ms": round(max(shard_durations, default=0.0) + merge_ms, 2),\n        "slo_ms": float((read_json(CONFIG / "service_registry.json", {}) or {}).get("guardrails", {}).get("package_precompute_wall_slo_ms") or 90000),\n        "semantic_fingerprint": semantic,\n        "input_sha256": current_raw,\n        "package_artifact_sha256": file_digest(PACKAGE_OUTFILE),\n        "tactical_interaction_sha256": file_digest(TACTICAL_INTERACTION_OUTFILE),\n        "execution": {\n            "topology": "WORKFLOW_MATRIX_FANOUT_FANIN",\n            "shard_count": len(wrappers),\n            "shard_duration_ms": shard_durations,\n            "max_shard_duration_ms": max(shard_durations, default=0.0),\n            "merge_duration_ms": merge_ms,\n            "parallel_wall_estimate_ms": round(max(shard_durations, default=0.0) + merge_ms, 2),\n        },\n        "search": {\n            "status": "FULL_UNIVERSE_PROVEN",\n            "authoritative_for_recommendation": True,\n            "decision_authority": "ENGINE_ADVISORY_ONLY_FULL_UNIVERSE_PROVEN",\n            "heuristic_candidate_cutoff": False,\n            "beam_cutoff": False,\n            "global_optimality_guaranteed_under_declared_package_semantics": True,\n            "diagnostics": (package.get("search") or {}).get("diagnostics") or {},\n        },\n        "guardrails": {\n            "full_universe_exact_search_owner": True,\n            "workflow_matrix_fanout_fanin": True,\n            "all_shards_non_authoritative": True,\n            "fan_in_single_global_authority": True,\n            "shard_partition_disjointness_proven": True,\n            "shard_partition_completeness_proven": True,\n            "decision_consumer_recompute_forbidden": True,\n            "input_lineage_fail_closed": True,\n            "semantic_fingerprint_is_reuse_authority": True,\n            "raw_input_digests_are_provenance_only": True,\n            "package_slo_separate_from_decision_compute_slo": True,\n        },\n    }\n    if manifest["duration_ms"] >= manifest["slo_ms"]:\n        manifest["status"] = "FAIL"\n        manifest["slo_status"] = "FAIL"\n    atomic_json(MANIFEST_OUTFILE, manifest)\n    if manifest["status"] != "PASS":\n        raise RuntimeError(f"workflow-sharded package precompute missed SLO: {manifest['duration_ms']} >= {manifest['slo_ms']}")\n    print(json.dumps({\n        "service": "package_optimization_merge", "status": "PASS",\n        "shards": len(wrappers), "max_shard_ms": max(shard_durations, default=0.0),\n        "merge_ms": merge_ms, "parallel_wall_estimate_ms": manifest["duration_ms"],\n    }))\n    return manifest\n\n\nif __name__ == "__main__":\n    run()\n''',
)

# 6) The logical package service becomes a fast coordinator/reuse validator. It must
# not silently fall back to the >100s monolith inside the decision DAG.
write(
    "src/services/package_optimization_service.py",
    '''from __future__ import annotations\n\nimport json\nfrom time import perf_counter\n\nfrom src.engines.v4_package_artifact_contract import validate_package_optimization_artifact\n\n\ndef run() -> dict:\n    started = perf_counter()\n    manifest = validate_package_optimization_artifact()\n    elapsed_ms = round((perf_counter() - started) * 1000.0, 2)\n    out = dict(manifest)\n    out["coordinator_reuse_validation_ms"] = elapsed_ms\n    out["reused"] = True\n    print(json.dumps({\n        "service": "package_optimization", "status": "PASS", "reused": True,\n        "validation_ms": elapsed_ms, "search": (manifest.get("search") or {}).get("status"),\n    }))\n    return out\n\n\nif __name__ == "__main__":\n    run()\n''',
)

# 7) Registry: one logical boundary, governed nested matrix execution topology.
service_path = ROOT / "config/service_registry.json"
registry = json.loads(service_path.read_text(encoding="utf-8"))
registry["schema_version"] = 17
registry["registry"] = "fpl_v4_9_7_microservice_registry_v17"
package_row = next(row for row in registry["services"] if row.get("id") == "package_optimization")
package_row.update({
    "name": "Exact full-universe package optimization",
    "timeout_seconds": 20,
    "execution_role": "TARGETED_PRECOMPUTE_COORDINATOR",
    "execution_topology": "WORKFLOW_MATRIX_FANOUT_FANIN",
    "worker_module": "src.services.package_optimization_shard_service",
    "merge_module": "src.services.package_optimization_merge_service",
    "shard_strategy": "OUTGOING_JOB_ORDINAL_MODULO",
    "checkpoint_lead_minutes": 15,
})
guard = registry["guardrails"]
guard.pop("package_optimization_slo_ms", None)
guard.pop("package_optimization_process_timeout_seconds", None)
guard["package_precompute_shard_count"] = 8
guard["package_shard_slo_ms"] = 60000
guard["package_merge_slo_ms"] = 15000
guard["package_precompute_wall_slo_ms"] = 75000
guard["package_precompute_execution_topology"] = "WORKFLOW_MATRIX_FANOUT_FANIN"
guard["package_precompute_shards_non_authoritative"] = True
guard["package_precompute_fan_in_single_authority"] = True
guard["package_precompute_partition_disjoint_complete_proof_required"] = True
guard["package_precompute_monolithic_fallback_in_decision_dag_forbidden"] = True
guard["decision_compute_slo_ms"] = 5000
service_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

release_path = ROOT / "config/release_manifest.json"
release = json.loads(release_path.read_text(encoding="utf-8"))
release["registries"]["services"] = registry["registry"]
release_path.write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")

# Ownership registry names nested worker/merge modules but retains one logical owner.
own_path = ROOT / "config/architecture_ownership_registry.json"
own = json.loads(own_path.read_text(encoding="utf-8"))
package_cap = next(row for row in own["capability_matrix"] if row.get("capability") == "PACKAGE_OPTIMIZER")
package_cap["duplicates_overlap"] = (
    "package_optimization is the one logical owner; workflow matrix shard workers are explicitly non-authoritative; "
    "package_optimization_merge_service is the sole fan-in that may publish FULL_UNIVERSE_PROVEN; decision optimization only consumes the lineage-verified artifact"
)
own_path.write_text(json.dumps(own, indent=2) + "\n", encoding="utf-8")

# Contract manifest execution proof.
contracts_path = ROOT / "config/service_contract_registry.json"
contracts = json.loads(contracts_path.read_text(encoding="utf-8"))
manifest_contract = contracts["contracts"]["package_optimization_manifest"]
for required in (
    "execution.topology", "execution.shard_count", "execution.max_shard_duration_ms", "execution.merge_duration_ms",
    "guardrails.workflow_matrix_fanout_fanin", "guardrails.all_shards_non_authoritative",
    "guardrails.fan_in_single_global_authority", "guardrails.shard_partition_disjointness_proven",
    "guardrails.shard_partition_completeness_proven",
):
    if required not in manifest_contract.setdefault("required_paths", []):
        manifest_contract["required_paths"].append(required)
manifest_contract.setdefault("equals", {}).update({
    "execution.topology": "WORKFLOW_MATRIX_FANOUT_FANIN",
    "guardrails.workflow_matrix_fanout_fanin": True,
    "guardrails.all_shards_non_authoritative": True,
    "guardrails.fan_in_single_global_authority": True,
    "guardrails.shard_partition_disjointness_proven": True,
    "guardrails.shard_partition_completeness_proven": True,
})
contracts_path.write_text(json.dumps(contracts, indent=2) + "\n", encoding="utf-8")

# Optimizer registry declares nested execution without creating a second authority.
opt_path = ROOT / "config/optimizer_equivalence_registry.json"
opt = json.loads(opt_path.read_text(encoding="utf-8"))
opt["production"]["transfer_package_execution_topology"] = "WORKFLOW_MATRIX_FANOUT_FANIN"
opt["production"]["transfer_package_shard_worker"] = "src.services.package_optimization_shard_service"
opt["production"]["transfer_package_fan_in"] = "src.services.package_optimization_merge_service"
opt["guardrails"]["shard_workers_must_be_non_authoritative"] = True
opt["guardrails"]["fan_in_is_single_global_package_authority"] = True
opt["guardrails"]["outgoing_partition_coverage_proof_required"] = True
opt_path.write_text(json.dumps(opt, indent=2) + "\n", encoding="utf-8")

# Tests for partition semantics and merge exactness on the existing small proof fixture.
write(
    "tests/test_v4_exact_workflow_shard_merge.py",
    '''from __future__ import annotations\n\nimport json\n\nfrom src.engines.v4_full_universe_package_shard_merge import merge_exact_package_shards\n\n\ndef _row(package_id: str, k: int, score: float, job_keys: list[str], index: int, count: int):\n    package = {\n        "package_id": package_id, "replacements": k, "adjusted_utility_gain_5": score,\n        "adjusted_best_xi_gain_5": score, "net_xpts_3": score, "net_xpts_5": score,\n        "net_xpts_10": score, "net_xpts_15": score, "target_cost": 1000, "target_itb": 0,\n        "hit_cost": 0, "projection_uncertainty": 0.1, "xmins_uncertainty": 0.1,\n        "tactical_uncertainty": 0.1, "roster_change_uncertainty": 0.1, "price_risk": 0.1,\n        "tactical_role_confidence": 0.9, "opponent_matchup_confidence": 0.9,\n        "structural_flexibility": 0.5, "classification": "IMPROVE",\n    }\n    roll = dict(package, package_id="ROLL_BASELINE", replacements=0, adjusted_utility_gain_5=0.0, adjusted_best_xi_gain_5=0.0, net_xpts_3=0.0, net_xpts_5=0.0, net_xpts_10=0.0, net_xpts_15=0.0, classification="ROLL_BASELINE")\n    return {\n        "contract": "V4_FULL_UNIVERSE_PACKAGE_SEARCH_V1",\n        "overall_verdict": "IMPROVE", "recommended_package": package,\n        "roll_baseline": roll, "baseline": {"x": 1}, "affordability": {"x": 1},\n        "best_by_replacement_count": {str(k): package}, "packages": [package],\n        "efficient_frontier": {"status": "SHARD_PARTIAL", "dominance_epsilon": 0.01, "rows": [roll, package], "maximize": [], "minimize": []},\n        "search": {\n            "status": "SHARD_PARTIAL_EXACT", "authoritative_for_recommendation": False,\n            "outgoing_shard_index": index, "outgoing_shard_count": count, "maximum_replacements": 3,\n            "heuristic_candidate_cutoff": False, "beam_cutoff": False,\n            "proof_covers_package_frontier_risk_confidence": True, "proof_covers_projected_affordability": True,\n            "proof_covers_recommendation_sanity": True, "proof_minimize_dimensions": ["a"], "proof_maximize_dimensions": ["b"],\n            "pruning_proofs": [],\n            "diagnostics": {"outgoing_jobs_total": count, "outgoing_jobs_selected": len(job_keys), "outgoing_job_keys": job_keys, "packages_evaluated": 1},\n        },\n        "decision_authority": "SHARD_PARTIAL_NO_AUTHORITY", "governance": {},\n    }\n\n\ndef test_fan_in_requires_disjoint_complete_partitions_and_becomes_single_authority():\n    merged = merge_exact_package_shards([\n        _row("A", 1, 1.0, ["1:a"], 0, 2),\n        _row("B", 1, 2.0, ["1:b"], 1, 2),\n    ])\n    assert merged["search"]["status"] == "FULL_UNIVERSE_PROVEN"\n    assert merged["search"]["authoritative_for_recommendation"] is True\n    assert merged["decision_authority"] == "ENGINE_ADVISORY_ONLY_FULL_UNIVERSE_PROVEN"\n    assert merged["recommended_package"]["package_id"] == "B"\n    d = merged["search"]["diagnostics"]\n    assert d["shard_partitions_disjoint"] is True\n    assert d["shard_partitions_complete"] is True\n\n\ndef test_fan_in_rejects_overlap_or_missing_shard():\n    import pytest\n    with pytest.raises(RuntimeError):\n        merge_exact_package_shards([_row("A", 1, 1.0, ["1:a"], 0, 2)])\n    with pytest.raises(RuntimeError):\n        merge_exact_package_shards([\n            _row("A", 1, 1.0, ["1:a"], 0, 2),\n            _row("B", 1, 2.0, ["1:a"], 1, 2),\n        ])\n''',
)

# Version boundary test from monolithic package SLO to workflow topology.
boundary = ROOT / "tests/test_v4_package_optimization_service_boundary.py"
text = boundary.read_text(encoding="utf-8")
text = text.replace('    assert guard["package_optimization_slo_ms"] == 90000\n', '    assert guard["package_precompute_wall_slo_ms"] == 75000\n    assert guard["package_precompute_shard_count"] == 8\n    assert guard["package_precompute_execution_topology"] == "WORKFLOW_MATRIX_FANOUT_FANIN"\n')
text = text.replace('    source = inspect.getsource(package_optimization_service.run)\n    assert "search_full_universe_packages(" in source\n    assert "FULL_UNIVERSE_PROVEN" in source\n    assert "heuristic_candidate_cutoff" in source\n    assert "beam_cutoff" in source\n', '    source = inspect.getsource(package_optimization_service.run)\n    assert "search_full_universe_packages(" not in source\n    assert "validate_package_optimization_artifact()" in source\n')
boundary.write_text(text, encoding="utf-8")

print("workflow-level exact shard topology staged")
