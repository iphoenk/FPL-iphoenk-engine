from __future__ import annotations

import json

import pytest

from src.services import runtime_publish_stamp as stamp


SOURCE_SHA = "a" * 40


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_provenance_uses_checked_out_head_not_caller_sha(monkeypatch):
    monkeypatch.setattr(stamp, "_checked_out_sha", lambda: SOURCE_SHA)
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("GITHUB_WORKFLOW", "FPL V4 reusable production core")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_call")
    monkeypatch.setenv("GITHUB_ACTOR", "fpl-iphoenk-bot")
    monkeypatch.setenv("GITHUB_REPOSITORY", "iphoenk/FPL-iphoenk-engine")

    provenance = stamp.provenance_from_env(required=True)

    assert provenance["canonical_source_sha"] == SOURCE_SHA
    assert provenance["workflow_run_id"] == 12345
    assert provenance["workflow_run_attempt"] == 2
    assert provenance["repository"] == "iphoenk/FPL-iphoenk-engine"


def test_required_provenance_fails_closed(monkeypatch):
    monkeypatch.setattr(stamp, "_checked_out_sha", lambda: None)
    for key in (
        "V4_CANONICAL_SOURCE_SHA",
        "V4_PUBLISH_RUN_ID",
        "V4_PUBLISH_RUN_ATTEMPT",
        "V4_PUBLISH_WORKFLOW",
        "V4_PUBLISH_EVENT",
        "V4_PUBLISH_ACTOR",
        "V4_PUBLISH_REPOSITORY",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_WORKFLOW",
        "GITHUB_EVENT_NAME",
        "GITHUB_ACTOR",
        "GITHUB_REPOSITORY",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(RuntimeError, match="provenance missing"):
        stamp.provenance_from_env(required=True)


def test_stamp_embeds_and_verifies_snapshot_identity(tmp_path, monkeypatch):
    latest = tmp_path / "latest.json"
    checkpoint = tmp_path / "checkpoint.json"
    serving = tmp_path / "serving.json"
    benchmark = tmp_path / "benchmark.json"
    snapshot = tmp_path / "runtime" / "snapshot.v1.json"
    provenance_path = tmp_path / "runtime_provenance_v4.json"

    _write(latest, {"generated_at": "2026-08-30T23:00:00+00:00"})
    _write(checkpoint, {"action_state": "REVIEW"})
    _write(serving, {"engine_source_line": {}})
    _write(benchmark, {})
    _write(snapshot, {"snapshot": "immutable-official-facts"})

    monkeypatch.setattr(stamp, "LATEST", latest)
    monkeypatch.setattr(stamp, "CHECKPOINT", checkpoint)
    monkeypatch.setattr(stamp, "SERVING", serving)
    monkeypatch.setattr(stamp, "BENCHMARK", benchmark)
    monkeypatch.setattr(stamp, "SNAPSHOT", snapshot)
    monkeypatch.setattr(stamp, "PROVENANCE", provenance_path)
    monkeypatch.setattr(
        stamp,
        "evaluate_freshness",
        lambda *_args, **_kwargs: {"freshness_state": "FRESH", "source_age_minutes": 0.0},
    )

    provenance = {
        "canonical_source_sha": SOURCE_SHA,
        "workflow_run_id": 12345,
        "workflow_run_attempt": 1,
        "workflow": "FPL V4 reusable production core",
        "event": "push",
        "actor": "fpl-iphoenk-bot",
        "repository": "iphoenk/FPL-iphoenk-engine",
        "runtime_branch": "runtime-data-v4",
    }
    result = stamp.stamp_runtime_publish(
        "2026-08-30T23:01:00+00:00",
        provenance=provenance,
        require_provenance=True,
    )

    assert result["canonical_source_sha"] == SOURCE_SHA
    verified = stamp.verify_runtime_provenance(
        expected_source_sha=SOURCE_SHA, expected_run_id=12345
    )
    assert verified["snapshot_sha256"] == stamp._sha256(snapshot)
    assert json.loads(latest.read_text())["runtime_provenance"] == verified

    snapshot.write_text('{"snapshot":"tampered"}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="snapshot hash mismatch"):
        stamp.verify_runtime_provenance(
            expected_source_sha=SOURCE_SHA, expected_run_id=12345
        )
