from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.runtime_v3.reuse_freshness import reuse_service
from src.utils import ROOT


def _write(path, generated_at: datetime | None) -> None:
    payload = {"value": "ok"}
    if generated_at is not None:
        payload["generated_at"] = generated_at.isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")


def _spec() -> dict:
    return {"artifacts": ["source_health.json"]}


def _profile(ttl: int, *, freshness: bool = True) -> dict:
    rule = {"max_age_seconds": ttl}
    if freshness:
        rule |= {"freshness_artifact": "source_health.json", "freshness_field": "generated_at"}
    return {"reuse_services": {"source_layer": rule}}


def test_hydrated_fresh_mtime_cannot_hide_stale_semantic_timestamp(tmp_path):
    now = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    artifact = tmp_path / "source_health.json"
    _write(artifact, now - timedelta(hours=3))

    # Writing the file above gives it a fresh filesystem mtime, exactly like
    # `git show ... > data/file` hydration in the production workflow.
    assert reuse_service("source_layer", _spec(), tmp_path, _profile(1800), now=now) is None


def test_fresh_semantic_timestamp_allows_ttl_reuse(tmp_path):
    now = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    artifact = tmp_path / "source_health.json"
    generated_at = now - timedelta(minutes=10)
    _write(artifact, generated_at)

    reused = reuse_service("source_layer", _spec(), tmp_path, _profile(1800), now=now)
    assert reused is not None
    assert reused["status"] == "REUSED"
    assert reused["reuse_mode"] == "AGE_TTL"
    assert reused["reuse_freshness_source"] == "SEMANTIC_TIMESTAMP"
    assert reused["reuse_freshness_artifact"] == "source_health.json"
    assert reused["reuse_freshness_timestamp"] == generated_at.isoformat()
    assert reused["reuse_age_seconds"] == 600.0


def test_non_positive_ttl_disables_age_reuse(tmp_path):
    now = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    _write(tmp_path / "source_health.json", now)
    assert reuse_service("source_layer", _spec(), tmp_path, _profile(0), now=now) is None


def test_missing_or_undeclared_freshness_metadata_fails_closed(tmp_path):
    now = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    _write(tmp_path / "source_health.json", None)
    assert reuse_service("source_layer", _spec(), tmp_path, _profile(1800), now=now) is None
    assert reuse_service("source_layer", _spec(), tmp_path, _profile(1800, freshness=False), now=now) is None


def test_every_positive_ttl_rule_declares_owned_semantic_freshness_artifact():
    profiles = json.loads((ROOT / "config" / "runtime" / "execution_profiles.json").read_text(encoding="utf-8"))
    services = json.loads((ROOT / "config" / "v3_service_registry.json").read_text(encoding="utf-8"))["services"]

    for profile_name, profile in profiles["profiles"].items():
        for service_name, rule in (profile.get("reuse_services") or {}).items():
            ttl = float(rule.get("max_age_seconds") or 0)
            if ttl <= 0:
                continue
            freshness_artifact = rule.get("freshness_artifact")
            assert freshness_artifact, f"{profile_name}:{service_name} missing freshness_artifact"
            assert freshness_artifact in services[service_name]["artifacts"], (
                f"{profile_name}:{service_name} freshness artifact is not capability-owned"
            )
