from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.runtime_v3 import measured_command, shard_policy_validate, sharded_resource_telemetry


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_measured_command_records_successful_child_peak(tmp_path):
    output = tmp_path / "resource.json"
    rc = measured_command.run(["python", "-c", "print('ok')"], output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["registry"] == "V3_PROCESS_RESOURCE_MEASUREMENT_V1"
    assert payload["exit_code"] == 0
    assert payload["peak_rss_kb"] > 0
    assert payload["elapsed_ms"] >= 0


def test_sharded_resource_telemetry_fills_strict_performance_contract(monkeypatch, tmp_path):
    data = tmp_path / "data"
    shard_dir = tmp_path / "shards"
    monkeypatch.setattr(sharded_resource_telemetry, "DATA", data)
    _write(data / "projections.json", {"players": [1]})
    _write(data / "team.json", {"team_value_ledger": [1]})
    _write(data / "package_optimizer.json", {"status": "READY"})
    _write(data / "latest.json", {})
    plan = tmp_path / "plan.json"
    _write(plan, {"shard_count": 2})
    for shard_id, rss in ((0, 101), (1, 202)):
        _write(shard_dir / f"shard-{shard_id}.json", {"registry": "V3_PACKAGE_OPTIMIZER_SHARD_RESULT_V1"})
        _write(shard_dir / f"resource-{shard_id}.json", {
            "registry": "V3_PROCESS_RESOURCE_MEASUREMENT_V1",
            "exit_code": 0,
            "peak_rss_kb": rss,
            "elapsed_ms": 10 + shard_id,
        })
    reducer = tmp_path / "reducer.json"
    _write(reducer, {
        "registry": "V3_PROCESS_RESOURCE_MEASUREMENT_V1",
        "exit_code": 0,
        "peak_rss_kb": 303,
        "elapsed_ms": 5,
    })
    performance = data / "runtime_performance.json"
    _write(performance, {"execution_profile": "exhaustive_precompute", "sharded_precompute": {}})

    result = sharded_resource_telemetry.aggregate(plan, shard_dir, reducer, performance)

    resources = result["resources"]
    assert resources["peak_rss_kb"] == 303
    assert resources["child_peak_rss_kb"] == 202
    assert resources["temporary_bytes"] > 0
    assert resources["seed_input_bytes"] > 0
    assert resources["promoted_output_bytes"] > 0
    assert result["sharded_precompute"]["distributed_worker_count"] == 2
    assert result["sharded_precompute"]["resource_observability_complete"] is True


def test_sharded_resource_telemetry_fails_closed_on_missing_worker_measurement(monkeypatch, tmp_path):
    data = tmp_path / "data"
    monkeypatch.setattr(sharded_resource_telemetry, "DATA", data)
    _write(data / "projections.json", {})
    _write(data / "team.json", {})
    _write(data / "package_optimizer.json", {})
    _write(tmp_path / "plan.json", {"shard_count": 2})
    _write(tmp_path / "reducer.json", {
        "registry": "V3_PROCESS_RESOURCE_MEASUREMENT_V1",
        "exit_code": 0,
        "peak_rss_kb": 100,
    })
    with pytest.raises(RuntimeError, match="shard count mismatch"):
        sharded_resource_telemetry.aggregate(
            tmp_path / "plan.json",
            tmp_path / "shards",
            tmp_path / "reducer.json",
            data / "runtime_performance.json",
        )


def test_shard_policy_retention_is_not_hidden_top_n_authority():
    result = shard_policy_validate.validate()
    assert result["status"] == "PASS"
    assert result["local_top_keep"] >= result["global_top_required"]
    assert result["hidden_top_n_search_authority"] is False
    assert result["complete_exact_fan_in"] is True
