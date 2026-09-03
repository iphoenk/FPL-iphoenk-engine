from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.runtime_v3 import package_optimizer_shards, precompute_checkpoint

ROOT = Path(__file__).resolve().parents[1]


def _current_squad() -> list[dict]:
    positions = ["GK", "GK", *(["DEF"] * 5), *(["MID"] * 5), *(["FWD"] * 3)]
    return [
        {"element": index + 1, "position": position, "team_id": (index % 10) + 1, "sell_cost": 50}
        for index, position in enumerate(positions)
    ]


def _pool() -> dict[str, list[dict]]:
    sizes = {"GK": 20, "DEF": 100, "MID": 100, "FWD": 50}
    next_id = 1000
    out = {}
    for position, size in sizes.items():
        rows = []
        for offset in range(size):
            rows.append({"element": next_id + offset, "position": position, "team_id": (offset % 20) + 1, "now_cost": 50})
        out[position] = rows
        next_id += size
    return out


def test_shard_planner_derives_count_from_registry_workload_and_covers_all_pairs(monkeypatch):
    current = _current_squad()
    pool = _pool()
    monkeypatch.setattr(package_optimizer_shards, "_material", lambda: (
        {"planning_gw": 3, "players": []},
        {},
        {},
        current,
        pool,
        0,
        {"context": {}, "universe_counts": {"official_universe_count": 651}},
    ))
    monkeypatch.setattr(package_optimizer_shards, "optimizer_input_fingerprint", lambda: "a" * 64)

    plan = package_optimizer_shards.build_plan()
    policy = package_optimizer_shards.load_policy()["planner"]
    expected = min(
        int(policy["max_shards"]),
        max(
            int(policy["min_shards"]),
            -(-int(plan["estimated_pair_combinations"]) // int(policy["target_pair_combinations_per_shard"])),
        ),
    )
    tasks = [tuple(task) for shard in plan["shards"] for task in shard["tasks"]]

    assert plan["shard_count"] == expected
    assert plan["shard_count"] > 2
    assert len(tasks) == 105
    assert len(set(tasks)) == 105
    assert set(tasks) == set(__import__("itertools").combinations(range(15), 2))
    assert plan["governance"]["candidate_pruning"] is False
    assert plan["governance"]["business_authority_sharded"] is False


def test_shard_plan_is_deterministic_for_same_material_inputs(monkeypatch):
    current = _current_squad()
    pool = _pool()
    monkeypatch.setattr(package_optimizer_shards, "_material", lambda: (
        {"planning_gw": 3, "players": []}, {}, {}, current, pool, 0,
        {"context": {}, "universe_counts": {}},
    ))
    monkeypatch.setattr(package_optimizer_shards, "optimizer_input_fingerprint", lambda: "b" * 64)
    first = package_optimizer_shards.build_plan()
    second = package_optimizer_shards.build_plan()
    assert first["shards"] == second["shards"]
    assert first["matrix"] == second["matrix"]


def test_shard_worker_is_execution_only_and_cannot_write_optimizer(monkeypatch):
    current = _current_squad()
    pool = _pool()
    plan = {
        "registry": package_optimizer_shards.PLAN_REGISTRY,
        "optimizer_input_fingerprint": "c" * 64,
        "shards": [{"shard_id": 0, "tasks": [[0, 1]], "estimated_pair_combinations": 10}],
    }
    class FakeScorer:
        def __init__(self, *args, **kwargs):
            pass
        def score(self, players, changes=0):
            return {"valid": True, "horizons": {}, "robust_score": 1.0}

    monkeypatch.setattr(package_optimizer_shards, "CompiledPackageScorer", FakeScorer)
    monkeypatch.setattr(package_optimizer_shards, "optimizer_input_fingerprint", lambda: "c" * 64)
    monkeypatch.setattr(package_optimizer_shards, "_material", lambda: (
        {"planning_gw": 3, "players": []}, {}, {}, current, pool, 0,
        {"context": {"planning_gw": 3}, "universe_counts": {}},
    ))
    monkeypatch.setattr(package_optimizer_shards.accelerated, "_init_worker", lambda *args, **kwargs: None)
    monkeypatch.setattr(package_optimizer_shards.accelerated, "_pair_partition", lambda task: {
        "pair_candidate_combinations": 10,
        "pair_structural_cash_rejected": 0,
        "pair_structural_club_rejected": 0,
        "pair_step_legal": 9,
        "pair_candidates_exact_scored": 9,
        "batch_scalar_fallback_count": 2,
        "top": [],
        "frontier": [],
    })

    result = package_optimizer_shards.run_shard(plan, 0)
    assert result["registry"] == package_optimizer_shards.SHARD_REGISTRY
    assert result["governance"]["execution_only"] is True
    assert result["governance"]["writes_package_optimizer"] is False
    assert result["governance"]["writes_package_decision"] is False
    assert result["governance"]["candidate_pruning"] is False


def test_shard_reducer_loader_fails_closed_on_missing_or_duplicate_shards(tmp_path):
    plan = {
        "registry": package_optimizer_shards.PLAN_REGISTRY,
        "shards": [
            {"shard_id": 0, "tasks": [[0, 1]]},
            {"shard_id": 1, "tasks": [[0, 2]]},
        ],
    }
    payload = {"registry": package_optimizer_shards.SHARD_REGISTRY, "shard_id": 0, "tasks": [[0, 1]]}
    (tmp_path / "shard-0.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="incomplete/duplicate shard result set"):
        package_optimizer_shards._load_shards(plan, tmp_path)


def test_shard_policy_contains_only_execution_tuning_not_search_caps():
    policy = package_optimizer_shards.load_policy()
    assert policy["execution_only"] is True
    assert policy["authority_owner"] == "prediction"
    assert policy["contracts"]["shard_partition_may_not_prune_candidates"] is True
    assert policy["contracts"]["shard_partition_may_not_change_scoring"] is True
    assert policy["contracts"]["business_authority_is_not_sharded"] is True
    serialized = json.dumps(policy).lower()
    assert "top_n_per_position" not in serialized
    assert "candidate_budget" not in serialized


def test_legacy_runtime_precompute_schedule_delegates_instead_of_computing(monkeypatch, capsys):
    monkeypatch.setattr(precompute_checkpoint, "verify_runtime_snapshot", lambda: {"status": "PASS"})
    monkeypatch.setenv("GITHUB_WORKFLOW", precompute_checkpoint.LEGACY_RUNTIME_WORKFLOW)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("FPL_SCHEDULE_EXPR", "15 * * * *")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(precompute_checkpoint, "_precompute_decision", lambda now: (_ for _ in ()).throw(AssertionError("legacy workflow must not execute exhaustive precompute")))
    assert precompute_checkpoint.main() == 0
    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert payload["should_collect"] is False
    assert payload["snapshot_role"] == "SHARDED_PRECOMPUTE_DELEGATED"


def test_legacy_runtime_ci_deployment_delegates_sharded_exhaustive(monkeypatch, capsys):
    monkeypatch.setattr(precompute_checkpoint, "verify_runtime_snapshot", lambda: {"status": "PASS"})
    monkeypatch.setenv("GITHUB_WORKFLOW", precompute_checkpoint.LEGACY_RUNTIME_WORKFLOW)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_run")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(precompute_checkpoint, "_ci_deployment_decision", lambda now: (_ for _ in ()).throw(AssertionError("legacy workflow must delegate CI exhaustive")))
    assert precompute_checkpoint.main() == 0
    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert payload["should_collect"] is False
    assert "delegated" in payload["reason"]


def test_sharded_workflow_uses_dynamic_matrix_and_registry_resume_not_business_module_list():
    workflow = (ROOT / ".github/workflows/v3-package-precompute.yml").read_text(encoding="utf-8")
    assert "fromJSON(needs.prepare.outputs.matrix)" in workflow
    assert "package_optimizer_shards run-shard" in workflow
    assert "package_optimizer_shards reduce" in workflow
    assert "sharded_pipeline_resume" in workflow
    assert "max-parallel:" not in workflow
    assert "src.engines.lineup_governance" not in workflow
    assert "src.engines.framework_health_service" not in workflow
    assert "package_optimizer_exhaustive_accelerated" not in workflow
    assert "group: v3-runtime-publication" in workflow
