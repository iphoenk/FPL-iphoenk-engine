from __future__ import annotations

from src.runtime_v3 import rules_drift_refresh


def test_refresh_if_due_keeps_fresh_cached_state_off_network(monkeypatch):
    calls = []

    def fake_audit(*, check_remote: bool = False):
        calls.append(check_remote)
        return {
            "overall": "PASS",
            "drift": {
                "status": "NO_CHANGE",
                "changed_sources": [],
                "failed_sources": [],
                "changed_source_evidence": {},
            },
        }

    monkeypatch.setattr(rules_drift_refresh.rules_compliance_audit, "audit", fake_audit)

    result = rules_drift_refresh.refresh_if_due()

    assert calls == [False]
    assert result["status"] == "FRESH"
    assert result["remote_check_executed"] is False
    assert result["drift_after"] == "NO_CHANGE"


def test_refresh_if_due_refreshes_stale_state_once(monkeypatch):
    calls = []

    def fake_audit(*, check_remote: bool = False):
        calls.append(check_remote)
        if check_remote:
            return {
                "overall": "PASS",
                "drift": {
                    "status": "NO_CHANGE",
                    "changed_sources": [],
                    "failed_sources": [],
                    "changed_source_evidence": {},
                },
            }
        return {
            "overall": "PASS",
            "drift": {
                "status": "STALE",
                "changed_sources": [],
                "failed_sources": [],
                "changed_source_evidence": {},
            },
        }

    monkeypatch.setattr(rules_drift_refresh.rules_compliance_audit, "audit", fake_audit)

    result = rules_drift_refresh.refresh_if_due()

    assert calls == [False, True]
    assert result["status"] == "REFRESHED"
    assert result["remote_check_executed"] is True
    assert result["drift_before"] == "STALE"
    assert result["drift_after"] == "NO_CHANGE"


def test_refresh_if_due_surfaces_exact_changed_source_evidence(monkeypatch):
    calls = []
    evidence = {
        "scoring": {
            "url": "https://example.test/scoring",
            "http_status": 200,
            "previous_fingerprint_sha256": "a" * 64,
            "current_fingerprint_sha256": "b" * 64,
        }
    }

    def fake_audit(*, check_remote: bool = False):
        calls.append(check_remote)
        if check_remote:
            return {
                "overall": "REVIEW_REQUIRED",
                "drift": {
                    "status": "REVIEW_REQUIRED",
                    "changed_sources": ["scoring"],
                    "failed_sources": [],
                    "changed_source_evidence": evidence,
                },
            }
        return {
            "overall": "PASS",
            "drift": {
                "status": "STALE",
                "changed_sources": [],
                "failed_sources": [],
                "changed_source_evidence": {},
            },
        }

    monkeypatch.setattr(rules_drift_refresh.rules_compliance_audit, "audit", fake_audit)

    result = rules_drift_refresh.refresh_if_due()

    assert calls == [False, True]
    assert result["status"] == "MANUAL_REVIEW_REQUIRED"
    assert result["changed_sources"] == ["scoring"]
    assert result["changed_source_evidence"] == evidence
    assert rules_drift_refresh.main() == 3


def test_refresh_if_due_bootstraps_missing_remote_state(monkeypatch):
    calls = []

    def fake_audit(*, check_remote: bool = False):
        calls.append(check_remote)
        if check_remote:
            return {
                "overall": "PASS",
                "drift": {
                    "status": "BASELINED",
                    "changed_sources": [],
                    "failed_sources": [],
                    "changed_source_evidence": {},
                },
            }
        return {
            "overall": "PASS",
            "drift": {
                "status": "NOT_RUN",
                "changed_sources": [],
                "failed_sources": [],
                "changed_source_evidence": {},
            },
        }

    monkeypatch.setattr(rules_drift_refresh.rules_compliance_audit, "audit", fake_audit)

    result = rules_drift_refresh.refresh_if_due()

    assert calls == [False, True]
    assert result["remote_check_executed"] is True
    assert result["drift_after"] == "BASELINED"


def test_refresh_if_due_never_auto_clears_manual_review(monkeypatch):
    calls = []
    evidence = {
        "general_rules": {
            "url": "https://example.test/rules",
            "http_status": 200,
            "previous_fingerprint_sha256": "c" * 64,
            "current_fingerprint_sha256": "d" * 64,
        }
    }

    def fake_audit(*, check_remote: bool = False):
        calls.append(check_remote)
        return {
            "overall": "REVIEW_REQUIRED",
            "drift": {
                "status": "REVIEW_REQUIRED",
                "changed_sources": ["general_rules"],
                "failed_sources": [],
                "changed_source_evidence": evidence,
            },
        }

    monkeypatch.setattr(rules_drift_refresh.rules_compliance_audit, "audit", fake_audit)

    result = rules_drift_refresh.refresh_if_due()

    assert calls == [False]
    assert result["status"] == "MANUAL_REVIEW_REQUIRED"
    assert result["remote_check_executed"] is False
    assert result["rules_overall"] == "REVIEW_REQUIRED"
    assert result["changed_source_evidence"] == evidence
