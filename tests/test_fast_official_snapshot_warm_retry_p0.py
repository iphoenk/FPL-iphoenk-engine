import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.engines import official_snapshot_service
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


def _patch_snapshot_paths(monkeypatch, tmp_path):
    out = tmp_path / "official_snapshot.json"
    retry = tmp_path / "official_snapshot.retry.json"
    health = tmp_path / "health.json"
    monkeypatch.setattr(official_snapshot_service, "OUT", out)
    monkeypatch.setattr(official_snapshot_service, "RETRY_OUT", retry)
    monkeypatch.setattr(official_snapshot_service, "HEALTH_OUT", health)
    return out, retry, health


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


def test_fresh_official_pull_writes_exact_workspace_retry_mirror(monkeypatch, tmp_path):
    out_path, retry_path, health_path = _patch_snapshot_paths(monkeypatch, tmp_path)
    fetched_at = "2026-08-31T08:00:00+00:00"

    def fake_get_json(path, retries=None):
        health = {"status": "LIVE", "fetched_at": fetched_at}
        if path == "bootstrap-static/":
            return {"elements": [{"id": 1}], "events": []}, health
        if path == "fixtures/":
            return [], health
        if path.endswith("/transfers/"):
            return [], health
        return {}, health

    monkeypatch.setattr(official_snapshot_service, "get_json", fake_get_json)
    monkeypatch.setattr(
        official_snapshot_service,
        "detect_phase",
        lambda bootstrap: {
            "planning_gw": 3,
            "submitted_gw": None,
            "scoring_gw": None,
            "is_live_event": False,
        },
    )

    result = official_snapshot_service.run()
    assert result["official_freshness"]["state"] == "FRESH"
    assert out_path.exists()
    assert retry_path.exists()
    assert health_path.exists()
    assert json.loads(retry_path.read_text(encoding="utf-8")) == json.loads(out_path.read_text(encoding="utf-8"))
    assert result["governance"]["workspace_retry_mirror_created_only_from_fresh_pull"] is True
    assert result["governance"]["workspace_retry_mirror_has_zero_publication_authority"] is True


def test_failed_fresh_pull_clears_retry_mirror_before_fallback(monkeypatch, tmp_path):
    out_path, retry_path, _ = _patch_snapshot_paths(monkeypatch, tmp_path)
    verified_at = "2026-08-31T07:50:00+00:00"
    previous = {
        "generated_at": verified_at,
        "bootstrap": {"elements": [{"id": 1}]},
        "endpoint_health": {"bootstrap": {"status": "LIVE", "fetched_at": verified_at}},
        "official_freshness": {
            "state": "FRESH",
            "fallback": False,
            "snapshot_id": f"bootstrap-static@{verified_at}",
            "last_verified_at": verified_at,
        },
    }
    out_path.write_text(json.dumps(previous), encoding="utf-8")
    retry_path.write_text(json.dumps({"generated_at": "2026-08-31T08:00:00+00:00"}), encoding="utf-8")

    def failed_get_json(path, retries=None):
        return None, {
            "status": "UNAVAILABLE",
            "fetched_at": "2026-08-31T08:01:00+00:00",
            "error": "simulated failure",
        }

    monkeypatch.setattr(official_snapshot_service, "get_json", failed_get_json)
    result = official_snapshot_service.run()
    assert result["official_freshness"]["state"] == "FALLBACK"
    assert result["official_freshness"]["fallback"] is True
    assert not retry_path.exists()
    assert result["governance"]["workspace_retry_mirror_created_only_from_fresh_pull"] is True


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
