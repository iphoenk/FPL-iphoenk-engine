from __future__ import annotations

import json
from pathlib import Path

from src.utils import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_assessment_thresholds_are_owned_by_existing_policies() -> None:
    xmins = _json("config/intelligence/xmins_v2.json")["contract_validation"]
    projection = _json("config/intelligence/projection.json")["validation"]
    reporting = _json("config/intelligence/reporting.json")["battle_reason_thresholds"]
    assert xmins == {"probability_sum_tolerance": 0.002, "expected_minutes_identity_tolerance": 0.2}
    assert projection["minimum_player_coverage_ratio"] == 0.95
    assert reporting == {"xpts_delta": 0.10, "xmins_delta": 2.0, "start_probability_delta": 0.03}


def test_assessment_removes_reviewed_source_threshold_literals() -> None:
    sources = {
        "src/engines/framework_health_audit.py": ("ratio >= 0.95", "abs(total - 1.0) < 0.002"),
        "src/engines/framework_health_service.py": ("abs((start + bench + dnp) - 1.0) < 0.002",),
        "src/engines/p0_framework_health_overlay.py": ("abs(probs - 1.0) < 0.002", "coverage >= 0.95"),
        "src/engines/p0_decision_quality.py": ("abs(probability_sum - 1.0) > 0.002", "abs(expected - published) > 0.2"),
        "src/engines/report_enrichment.py": ("abs(xpts_delta) >= 0.10", "abs(xmins_delta) >= 2.0", "abs(start_delta) >= 0.03"),
        "src/runtime_v3/definition_of_done.py": ("float(interactive_ms) < 1000.0",),
    }
    for path, forbidden in sources.items():
        text = (ROOT / path).read_text(encoding="utf-8")
        for literal in forbidden:
            assert literal not in text, f"{path} still hardcodes {literal}"


def test_assessment_reviewed_json_writers_are_atomic() -> None:
    source_paths = [
        "src/engines/price_radar.py",
        "src/runtime_v3/measured_command.py",
        "src/runtime_v3/package_optimizer_shards.py",
        "src/runtime_v3/registry_compiler.py",
    ]
    for path in source_paths:
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "atomic_json" in text
        assert ".write_text(json.dumps(" not in text

    utils = (ROOT / "src" / "utils.py").read_text(encoding="utf-8")
    measured = (ROOT / "src" / "runtime_v3" / "measured_command.py").read_text(encoding="utf-8")
    shards = (ROOT / "src" / "runtime_v3" / "package_optimizer_shards.py").read_text(encoding="utf-8")
    assert "compact: bool | None = None" in utils
    assert "atomic_json(output, payload, compact=True)" in measured
    assert "atomic_json(output, result, compact=True)" in shards


def test_atomic_json_compact_override_preserves_payload_and_representation(tmp_path: Path) -> None:
    output = tmp_path / "shard-result.json"
    payload = {"status": "READY", "values": [1, 2, 3]}
    atomic_json(output, payload, compact=True)
    assert output.read_text(encoding="utf-8") == json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert not output.with_suffix(output.suffix + ".tmp").exists()


def test_sharded_official_snapshot_boundary_remains_fail_closed() -> None:
    workflow = (ROOT / ".github" / "workflows" / "v3-package-precompute.yml").read_text(encoding="utf-8")
    registry = _json("config/v3_service_registry.json")
    official = registry["services"]["official_snapshot"]
    assert official["ephemeral_artifacts"] == ["official_snapshot.json"]
    assert "data/official_snapshot.retry.json" in workflow
    assert "cmp -s data/official_snapshot.json data/official_snapshot.retry.json" in workflow
