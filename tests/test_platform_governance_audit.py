from __future__ import annotations

from src.runtime_v3 import platform_governance_audit as audit


def _branch(*, protected: bool, enforcement: str = "off", checks: list[str] | None = None):
    return {
        "protected": protected,
        "protection": {
            "required_status_checks": {
                "enforcement_level": enforcement,
                "contexts": list(checks or []),
                "checks": [],
            }
        },
    }


def _run(monkeypatch, payloads):
    def fake(url: str, token: str | None):
        for suffix, result in payloads.items():
            if url.endswith(suffix):
                return result
        raise AssertionError(url)

    monkeypatch.setattr(audit, "_request_json", fake)
    return audit.audit(
        api_url="https://api.github.com",
        repo="iphoenk/FPL-iphoenk-engine",
        default_branch="main",
        runtime_branch="runtime-data",
        required_check="verify",
        token="token",
    )


def test_platform_audit_reports_current_unprotected_shape_as_red(monkeypatch):
    result = _run(
        monkeypatch,
        {
            "/branches/main": audit.ApiResult(200, _branch(protected=True)),
            "/branches/runtime-data": audit.ApiResult(200, _branch(protected=False)),
            "/rulesets": audit.ApiResult(200, []),
        },
    )
    assert result["overall"] == "RED"
    by_name = {row["name"]: row for row in result["checks"]}
    assert by_name["MAIN_PROTECTED"]["status"] == "PASS"
    assert by_name["MAIN_REQUIRED_V3_CI"]["status"] == "FAIL"
    assert by_name["RUNTIME_BRANCH_NATIVE_PROTECTION"]["status"] == "FAIL"


def test_platform_audit_requires_explicit_ruleset_evidence_for_green(monkeypatch):
    main_ruleset = {
        "id": 1,
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [{"type": "pull_request"}, {"type": "non_fast_forward"}, {"type": "deletion"}],
    }
    runtime_ruleset = {
        "id": 2,
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/heads/runtime-data"], "exclude": []}},
        "rules": [{"type": "update"}, {"type": "deletion"}],
    }
    result = _run(
        monkeypatch,
        {
            "/branches/main": audit.ApiResult(200, _branch(protected=True, enforcement="non_admins", checks=["verify"])),
            "/branches/runtime-data": audit.ApiResult(200, _branch(protected=True)),
            "/rulesets": audit.ApiResult(200, [{"id": 1}, {"id": 2}]),
            "/rulesets/1": audit.ApiResult(200, main_ruleset),
            "/rulesets/2": audit.ApiResult(200, runtime_ruleset),
        },
    )
    assert result["overall"] == "GREEN"
    assert all(row["status"] == "PASS" for row in result["checks"])


def test_platform_audit_never_treats_unknown_as_green(monkeypatch):
    result = _run(
        monkeypatch,
        {
            "/branches/main": audit.ApiResult(403, None, "forbidden"),
            "/branches/runtime-data": audit.ApiResult(403, None, "forbidden"),
            "/rulesets": audit.ApiResult(403, None, "forbidden"),
        },
    )
    assert result["overall"] == "AMBER"
    assert all(row["status"] == "UNKNOWN" for row in result["checks"])
