import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.runtime_v3 import reuse_freshness

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _stub_validation(monkeypatch):
    monkeypatch.setattr(
        reuse_freshness,
        "validate_artifact",
        lambda path, artifact: {"artifact": artifact, "valid": True},
    )


def test_fast_warm_retry_reuses_only_fresh_same_workspace_official_snapshot(monkeypatch, tmp_path):
    profiles = _load("config/runtime/execution_profiles.json")
    fast = profiles["profiles"]["fast_decision"]
    cfg = fast["reuse_services"]["official_snapshot"]
    assert profiles["policy"]["fast_same_job_official_snapshot_reuse_is_bounded_and_semantic"] is True
    assert profiles["policy"]["workspace_retry_mirror_never_crosses_runtime_publication_boundary"] is True
    assert cfg == {
        "max_age_seconds": 60,
        "freshness_artifact": "official_snapshot.json",
        "freshness_field": "generated_at",
        "workspace_retry_artifact": "official_snapshot.retry.json",
    }

    generated_at = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)
    (tmp_path / "official_snapshot.json").write_text(
        json.dumps({"generated_at": generated_at.isoformat()}), encoding="utf-8"
    )
    (tmp_path / "health.json").write_text("{}", encoding="utf-8")
    spec = {"artifacts": ["official_snapshot.json", "health.json"]}
    _stub_validation(monkeypatch)

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
    assert reused["workspace_retry_restored"] is False

    assert reuse_freshness.reuse_service(
        "official_snapshot",
        spec,
        tmp_path,
        fast,
        now=generated_at + timedelta(seconds=61),
    ) is None


def test_fast_warm_retry_restores_ephemeral_snapshot_from_fresh_workspace_mirror(monkeypatch, tmp_path):
    fast = _load("config/runtime/execution_profiles.json")["profiles"]["fast_decision"]
    generated_at = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)
    payload = {
        "generated_at": generated_at.isoformat(),
        "official_freshness": {"state": "FRESH", "fallback": False},
        "bootstrap": {"elements": [{"id": 1}]},
    }
    (tmp_path / "official_snapshot.retry.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "health.json").write_text("{}", encoding="utf-8")
    spec = {"artifacts": ["official_snapshot.json", "health.json"]}
    _stub_validation(monkeypatch)

    assert not (tmp_path / "official_snapshot.json").exists()
    reused = reuse_freshness.reuse_service(
        "official_snapshot",
        spec,
        tmp_path,
        fast,
        now=generated_at + timedelta(seconds=15),
    )
    assert reused is not None
    assert reused["status"] == "REUSED"
    assert reused["workspace_retry_restored"] is True
    assert reused["workspace_retry_artifact"] == "official_snapshot.retry.json"
    assert json.loads((tmp_path / "official_snapshot.json").read_text(encoding="utf-8")) == payload

    (tmp_path / "official_snapshot.json").unlink()
    stale = reuse_freshness.reuse_service(
        "official_snapshot",
        spec,
        tmp_path,
        fast,
        now=generated_at + timedelta(seconds=61),
    )
    assert stale is None
    assert not (tmp_path / "official_snapshot.json").exists()


def test_official_snapshot_warm_reuse_cannot_cross_production_jobs():
    profiles = _load("config/runtime/execution_profiles.json")
    services = _load("config/v3_service_registry.json")["services"]
    publish = _load("config/runtime/runtime_publish_registry.json")
    fast_cfg = profiles["profiles"]["fast_decision"]["reuse_services"]["official_snapshot"]
    retry_artifact = fast_cfg["workspace_retry_artifact"]
    hydrate_paths = set(publish.get("hydrate_paths") or [])
    publish_paths = set(publish.get("publish_paths") or [])

    assert "official_snapshot" not in profiles["profiles"]["live"]["reuse_services"]
    assert "official_snapshot" not in profiles["profiles"]["full_refresh"]["reuse_services"]
    assert "official_snapshot.json" in services["official_snapshot"]["ephemeral_artifacts"]
    assert "official_snapshot.json" not in hydrate_paths
    assert "official_snapshot.json" not in publish_paths
    assert retry_artifact not in hydrate_paths
    assert retry_artifact not in publish_paths
