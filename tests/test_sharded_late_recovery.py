from __future__ import annotations

import json
from datetime import datetime, timezone

from src.runtime_v3 import precompute_checkpoint


def _base_env(monkeypatch, workflow: str) -> None:
    monkeypatch.setattr(precompute_checkpoint, "verify_runtime_snapshot", lambda: {"status": "PASS"})
    monkeypatch.setenv("GITHUB_WORKFLOW", workflow)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("FPL_SCHEDULE_EXPR", "32 * * * *")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(precompute_checkpoint, "read_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(precompute_checkpoint, "is_precompute_schedule", lambda expr: False)
    monkeypatch.setattr(precompute_checkpoint.collector_gate, "is_primary_schedule", lambda expr: False)
    monkeypatch.setattr(precompute_checkpoint.collector_gate, "is_adaptive_schedule", lambda expr: True)
    target = datetime(2026, 9, 3, 5, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(precompute_checkpoint, "_adaptive_recovery_target", lambda now: ("CURRENT", target))
    monkeypatch.setattr(precompute_checkpoint, "_manifest_satisfies_checkpoint", lambda *args, **kwargs: False)


def test_sharded_workflow_recovers_missing_current_checkpoint_with_exhaustive_lane(monkeypatch, capsys):
    _base_env(monkeypatch, precompute_checkpoint.SHARDED_PRECOMPUTE_WORKFLOW)
    called = {}

    def recover(now, target):
        called["target"] = target
        return {
            "should_collect": True,
            "reason": "adaptive_missing_current_checkpoint_sharded_exhaustive_recovery",
            "visible_mode": precompute_checkpoint.PRECOMPUTE_EXECUTION_MODE,
            "snapshot_role": precompute_checkpoint.LATE_PRECOMPUTE_ROLE,
            "target_checkpoint_utc": target.isoformat(),
            "target_checkpoint_local": target.isoformat(),
            "target_visible_report": True,
            "target_visible_mode": "NORMAL_MIDDAY_REVIEW",
        }

    monkeypatch.setattr(precompute_checkpoint, "_sharded_current_recovery_decision", recover)
    monkeypatch.setattr(precompute_checkpoint, "_checkpoint_recovery_decision", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("generic recovery must not own sharded CURRENT recovery")))

    assert precompute_checkpoint.main() == 0
    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert called["target"].isoformat() == payload["target_checkpoint_utc"]
    assert payload["should_collect"] is True
    assert payload["visible_mode"] == precompute_checkpoint.PRECOMPUTE_EXECUTION_MODE
    assert payload["snapshot_role"] == precompute_checkpoint.LATE_PRECOMPUTE_ROLE


def test_legacy_runtime_delegates_missing_current_checkpoint_to_sharded_lane(monkeypatch, capsys):
    _base_env(monkeypatch, precompute_checkpoint.LEGACY_RUNTIME_WORKFLOW)
    monkeypatch.setattr(precompute_checkpoint, "_checkpoint_recovery_decision", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy runtime may not compute adaptive CURRENT recovery")))
    monkeypatch.setattr(precompute_checkpoint, "_sharded_current_recovery_decision", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy runtime may not invoke sharded compute directly")))

    assert precompute_checkpoint.main() == 0
    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert payload["should_collect"] is False
    assert payload["snapshot_role"] == "SHARDED_PRECOMPUTE_DELEGATED"
    assert payload["reason"] == "adaptive_missing_current_checkpoint_delegated_to_sharded_workflow"
