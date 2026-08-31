import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.runtime_v3 import reuse_freshness

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_fast_warm_retry_reuses_only_fresh_same_workspace_official_snapshot(monkeypatch, tmp_path):
    profiles = _load("config/runtime/execution_profiles.json")
    fast = profiles["profiles"]["fast_decision"]
    cfg = fast["reuse_services"]["official_snapshot"]
    assert profiles["policy"]["fast_same_job_official_snapshot_reuse_is_bounded_and_semantic"] is True
    assert cfg == {
        "max_age_seconds": 60,
        "freshness_artifact": "official_snapshot.json",
        "freshness_field": "generated_at",
    }

    generated_at = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)
    (tmp_path / "official_snapshot.json").write_text(
        json.dumps({"generated_at": generated_at.isoformat()}), encoding="utf-8"
    )
    (tmp_path / "health.json").write_text("{}", encoding="utf-8")
    spec = {"artifacts": ["official_snapshot.json", "health.json"]}
    monkeypatch.setattr(
        reuse_freshness,
        "validate_artifact",
        lambda path, artifact: {"artifact": artifact, "valid": True},
    )

    reused = reuse_freshness.reuse_service(
        "official_snapshot",
        spec,
        tmp_path,
        fast,
        now=generated_at + timedelta(seconds=30),
    )
    assert reused is not None
    assert reused["status"] == "REUSED"
    assert reused["reuse_mode"] == "AGE_TTL"
    assert reused["reuse_age_seconds"] == 30.0
    assert reused["reuse_max_age_seconds"] == 60.0

    assert reuse_freshness.reuse_service(
        "official_snapshot",
        spec,
        tmp_path,
        fast,
        now=generated_at + timedelta(seconds=61),
    ) is None


def test_official_snapshot_warm_reuse_cannot_cross_production_jobs():
    profiles = _load("config/runtime/execution_profiles.json")
    services = _load("config/v3_service_registry.json")["services"]
    publish = _load("config/runtime/runtime_publish_registry.json")

    assert "official_snapshot" in profiles["profiles"]["fast_decision"]["reuse_services"]
    assert "official_snapshot" not in profiles["profiles"]["live"]["reuse_services"]
    assert "official_snapshot" not in profiles["profiles"]["full_refresh"]["reuse_services"]
    assert "official_snapshot.json" in services["official_snapshot"]["ephemeral_artifacts"]
    assert "official_snapshot.json" not in set(publish.get("hydrate_paths") or [])
