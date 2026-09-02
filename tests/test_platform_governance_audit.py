from __future__ import annotations

from copy import deepcopy

from src.runtime_v3 import platform_governance_audit as audit


PUBLISHER_APP_ID = 4800186


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


def _run(
    monkeypatch,
    payloads,
    *,
    publisher_app_id: int | None = PUBLISHER_APP_ID,
    public_payloads=None,
):
    def fake(url: str, token: str | None):
        source = public_payloads if token is None and public_payloads is not None else payloads
        for suffix, result in source.items():
            if url.endswith(suffix):
                return result
        raise AssertionError((url, token))

    monkeypatch.setattr(audit, "_request_json", fake)
    return audit.audit(
        api_url="https://api.github.com",
        repo="iphoenk/FPL-iphoenk-engine",
        default_branch="main",
        runtime_branch="runtime-data",
        required_check="verify",
        token="token",
        runtime_publisher_app_id=publisher_app_id,
    )


def _main_ruleset():
    return {
        "id": 1,
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "pull_request"},
            {"type": "non_fast_forward"},
            {"type": "deletion"},
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [{"context": "verify", "integration_id": 15368}],
                },
            },
        ],
        "bypass_actors": [],
    }


def _runtime_ruleset(*, app_id: int = PUBLISHER_APP_ID):
    return {
        "id": 2,
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/heads/runtime-data"], "exclude": []}},
        "rules": [{"type": "update"}, {"type": "deletion"}, {"type": "non_fast_forward"}],
        "bypass_actors": [{"actor_id": app_id, "actor_type": "Integration", "bypass_mode": "always"}],
    }


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
    assert by_name["RUNTIME_PUBLISHER_BYPASS_EXACT"]["status"] == "FAIL"


def test_platform_audit_accepts_ruleset_required_check_and_exact_publisher_for_green(monkeypatch):
    result = _run(
        monkeypatch,
        {
            "/branches/main": audit.ApiResult(200, _branch(protected=True)),
            "/branches/runtime-data": audit.ApiResult(200, _branch(protected=True)),
            "/rulesets": audit.ApiResult(200, [{"id": 1}, {"id": 2}]),
            "/rulesets/1": audit.ApiResult(200, _main_ruleset()),
            "/rulesets/2": audit.ApiResult(200, _runtime_ruleset()),
        },
    )
    assert result["overall"] == "GREEN"
    assert all(row["status"] == "PASS" for row in result["checks"])
    by_name = {row["name"]: row for row in result["checks"]}
    assert by_name["MAIN_REQUIRED_V3_CI"]["detail"]["classic"]["enforcement"] == "off"
    assert by_name["MAIN_REQUIRED_V3_CI"]["detail"]["ruleset"]["required_checks"] == ["verify"]
    assert by_name["RUNTIME_PUBLISHER_BYPASS_EXACT"]["detail"]["evidence_source"] == "authenticated_ruleset_detail"


def test_platform_audit_recovers_exact_bypass_when_actions_token_masks_actor_list(monkeypatch):
    masked_runtime = deepcopy(_runtime_ruleset())
    masked_runtime["bypass_actors"] = []
    result = _run(
        monkeypatch,
        {
            "/branches/main": audit.ApiResult(200, _branch(protected=True)),
            "/branches/runtime-data": audit.ApiResult(200, _branch(protected=True)),
            "/rulesets": audit.ApiResult(200, [{"id": 1}, {"id": 2}]),
            "/rulesets/1": audit.ApiResult(200, _main_ruleset()),
            "/rulesets/2": audit.ApiResult(200, masked_runtime),
        },
        public_payloads={
            "/rulesets/2": audit.ApiResult(200, _runtime_ruleset()),
        },
    )
    assert result["overall"] == "GREEN"
    by_name = {row["name"]: row for row in result["checks"]}
    detail = by_name["RUNTIME_PUBLISHER_BYPASS_EXACT"]["detail"]
    assert by_name["RUNTIME_PUBLISHER_BYPASS_EXACT"]["status"] == "PASS"
    assert detail["evidence_source"] == "public_ruleset_detail_fallback"
    assert detail["actors"] == [["Integration", PUBLISHER_APP_ID, "always"]]


def test_platform_audit_does_not_accept_unmatched_public_fallback(monkeypatch):
    masked_runtime = deepcopy(_runtime_ruleset())
    masked_runtime["bypass_actors"] = []
    mismatched_public = _runtime_ruleset()
    mismatched_public["rules"] = [{"type": "update"}, {"type": "deletion"}]
    result = _run(
        monkeypatch,
        {
            "/branches/main": audit.ApiResult(200, _branch(protected=True)),
            "/branches/runtime-data": audit.ApiResult(200, _branch(protected=True)),
            "/rulesets": audit.ApiResult(200, [{"id": 1}, {"id": 2}]),
            "/rulesets/1": audit.ApiResult(200, _main_ruleset()),
            "/rulesets/2": audit.ApiResult(200, masked_runtime),
        },
        public_payloads={
            "/rulesets/2": audit.ApiResult(200, mismatched_public),
        },
    )
    assert result["overall"] == "RED"
    by_name = {row["name"]: row for row in result["checks"]}
    assert by_name["RUNTIME_PUBLISHER_BYPASS_EXACT"]["status"] == "FAIL"
    assert by_name["RUNTIME_PUBLISHER_BYPASS_EXACT"]["detail"]["actors"] == []


def test_platform_audit_rejects_wrong_runtime_publisher_bypass(monkeypatch):
    result = _run(
        monkeypatch,
        {
            "/branches/main": audit.ApiResult(200, _branch(protected=True)),
            "/branches/runtime-data": audit.ApiResult(200, _branch(protected=True)),
            "/rulesets": audit.ApiResult(200, [{"id": 1}, {"id": 2}]),
            "/rulesets/1": audit.ApiResult(200, _main_ruleset()),
            "/rulesets/2": audit.ApiResult(200, _runtime_ruleset(app_id=999999)),
        },
    )
    assert result["overall"] == "RED"
    by_name = {row["name"]: row for row in result["checks"]}
    assert by_name["RUNTIME_PUBLISHER_BYPASS_EXACT"]["status"] == "FAIL"


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
