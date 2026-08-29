from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.engines import rules_compliance_audit as rules_audit


def _write_state(path, *, checked_at: str, status: str, changed=None, failed=None) -> None:
    path.write_text(
        json.dumps(
            {
                "ruleset_id": "FPL_2026_27",
                "checked_at": checked_at,
                "status": status,
                "changed_sources": changed or [],
                "failed_sources": failed or [],
                "sources": {
                    "general_rules": {
                        "url": "https://fantasy.premierleague.com/help/rules",
                        "fingerprint_sha256": "abc123",
                        "changed": bool(changed),
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_cached_rules_drift_reports_not_run_without_persisted_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(rules_audit, "SOURCE_STATE", tmp_path / "rules_source_state.json")
    result = rules_audit._cached_remote_drift_state()
    assert result["status"] == "NOT_RUN"
    assert result["cached"] is False


def test_cached_rules_drift_reuses_fresh_no_change_state(tmp_path, monkeypatch):
    source_state = tmp_path / "rules_source_state.json"
    monkeypatch.setattr(rules_audit, "SOURCE_STATE", source_state)
    _write_state(
        source_state,
        checked_at=datetime.now(timezone.utc).isoformat(),
        status="NO_CHANGE",
    )
    result = rules_audit._cached_remote_drift_state()
    assert result["status"] == "NO_CHANGE"
    assert result["cached"] is True
    assert result["age_hours"] is not None
    assert result["age_hours"] < 1.0


def test_cached_rules_drift_marks_old_non_review_state_stale(tmp_path, monkeypatch):
    source_state = tmp_path / "rules_source_state.json"
    monkeypatch.setattr(rules_audit, "SOURCE_STATE", source_state)
    _write_state(
        source_state,
        checked_at=(datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
        status="NO_CHANGE",
    )
    result = rules_audit._cached_remote_drift_state()
    assert result["status"] == "STALE"
    assert result["cached"] is True


def test_cached_rules_drift_never_hides_review_required(tmp_path, monkeypatch):
    source_state = tmp_path / "rules_source_state.json"
    monkeypatch.setattr(rules_audit, "SOURCE_STATE", source_state)
    _write_state(
        source_state,
        checked_at=(datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
        status="REVIEW_REQUIRED",
        changed=["general_rules"],
    )
    result = rules_audit._cached_remote_drift_state()
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["changed_sources"] == ["general_rules"]
