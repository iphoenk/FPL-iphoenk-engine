from __future__ import annotations

import json

import v4_frontier_regret_shadow
from src.services import runtime_publish_stamp


def test_frontier_regret_shadow_success_is_persisted_without_authority(monkeypatch, tmp_path):
    target = tmp_path / "frontier_regret_shadow_v4.json"
    monkeypatch.setattr(runtime_publish_stamp, "FRONTIER_REGRET_SHADOW", target)
    monkeypatch.setattr(
        v4_frontier_regret_shadow,
        "audit_current_runtime",
        lambda: {
            "schema_version": 1,
            "engine": "v4-frontier-regret-shadow",
            "audit_only": True,
            "decision_authority": "NONE",
            "affects_search": False,
            "affects_decision": False,
            "status": "PER_K_REGRET_OBSERVED",
            "history": [],
            "history_limit": 48,
        },
    )

    execution = runtime_publish_stamp.run_frontier_regret_shadow_nonblocking()
    persisted = json.loads(target.read_text())

    assert execution["outcome"] == "success"
    assert execution["failure_cannot_block_core_publish"] is True
    assert execution["observational_outside_decision_chain"] is True
    assert persisted["decision_authority"] == "NONE"
    assert persisted["affects_search"] is False
    assert persisted["runtime_execution"]["outcome"] == "success"


def test_frontier_regret_shadow_failure_is_diagnostic_not_publication_failure(monkeypatch, tmp_path):
    target = tmp_path / "frontier_regret_shadow_v4.json"
    monkeypatch.setattr(runtime_publish_stamp, "FRONTIER_REGRET_SHADOW", target)

    def fail():
        raise RuntimeError("synthetic shadow failure")

    monkeypatch.setattr(v4_frontier_regret_shadow, "audit_current_runtime", fail)

    execution = runtime_publish_stamp.run_frontier_regret_shadow_nonblocking()
    persisted = json.loads(target.read_text())

    assert execution["outcome"] == "failure"
    assert execution["failure_cannot_block_core_publish"] is True
    assert persisted["status"] == "DIAGNOSTIC_UNAVAILABLE"
    assert persisted["decision_authority"] == "NONE"
    assert persisted["runtime_execution"]["error_type"] == "RuntimeError"


def test_frontier_regret_shadow_persistence_failure_is_returned_not_raised(monkeypatch, tmp_path):
    target = tmp_path / "frontier_regret_shadow_v4.json"
    monkeypatch.setattr(runtime_publish_stamp, "FRONTIER_REGRET_SHADOW", target)
    monkeypatch.setattr(
        v4_frontier_regret_shadow,
        "audit_current_runtime",
        lambda: {"status": "NO_REGRET_OBSERVED", "history": [], "history_limit": 48},
    )

    def persistence_failure(*args, **kwargs):
        raise OSError("synthetic persistence failure")

    monkeypatch.setattr(runtime_publish_stamp, "atomic_json", persistence_failure)

    execution = runtime_publish_stamp.run_frontier_regret_shadow_nonblocking()

    assert execution["outcome"] == "success"
    assert execution["persistence"] == "failure"
    assert execution["persistence_error_type"] == "OSError"
