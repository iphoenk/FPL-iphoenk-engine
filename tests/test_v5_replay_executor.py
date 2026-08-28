from __future__ import annotations

from copy import deepcopy

from src.v5.replay_capture import build_replay_capture
from src.v5.replay_executor import ALLOWED_ROUTES, execute_replay


def _capture(monkeypatch):
    monkeypatch.setattr("src.v5.replay_capture.current_runtime_fingerprint", lambda: "sha256:runtime")
    return build_replay_capture(
        correlation_id="original-run",
        team_id=123,
        mode="daily",
        bootstrap={"elements": []},
        fixtures=[],
        truth={
            "context": {"planning_gw": 2},
            "team": {"owned_ids": []},
            "rules": {"season": "2026-27", "ruleset_id": "test"},
        },
        event_live=None,
        source_fusion={"status": "READY"},
        states={
            "price_trajectory": {"data": {}},
            "historical_prior": {"data": {}},
            "prediction_ledger": {"data": {}},
            "challenger_observations": {"data": {}},
        },
        runner_cfg={"status": "BETA", "prediction_horizon_gws": 15},
        feature_switches={"historical_prior_network_refresh": True},
        captured_at="2026-08-28T01:00:00+00:00",
    )


def test_replay_runtime_mismatch_blocks_before_model_calls(monkeypatch):
    bundle = _capture(monkeypatch)
    calls = []

    def invoke(name, payload, cid):
        calls.append(name)
        return {"data": {}}

    result = execute_replay(
        bundle,
        invoke_route=invoke,
        correlation_id="replay-run",
        current_runtime_fingerprint_value="sha256:different-runtime",
    )
    assert result["status"] == "BLOCKED_RUNTIME_FINGERPRINT_MISMATCH"
    assert result["match"] is False
    assert result["route_trace"] == []
    assert calls == []
    assert result["governance"]["model_services_invoked"] is False


def test_replay_tampered_bundle_blocks_before_model_calls(monkeypatch):
    bundle = _capture(monkeypatch)
    tampered = deepcopy(bundle)
    tampered["inputs"]["runner_policy"]["prediction_horizon_gws"] = 3
    calls = []

    def invoke(name, payload, cid):
        calls.append(name)
        return {"data": {}}

    result = execute_replay(
        tampered,
        invoke_route=invoke,
        correlation_id="replay-run",
        current_runtime_fingerprint_value="sha256:runtime",
    )
    assert result["status"] == "BLOCKED_ARTIFACT_INTEGRITY_MISMATCH"
    assert result["route_trace"] == []
    assert calls == []


def test_replay_uses_only_whitelisted_internal_model_routes(monkeypatch):
    bundle = _capture(monkeypatch)
    calls = []

    def invoke(name, payload, cid):
        calls.append(name)
        if name == "decision_finalize":
            return {"data": {"decision_trace": {"decision_type": "HOLD"}}}
        if name == "governance_audit":
            return {"data": {"recommendation_allowed": True, "go_allowed": False}}
        return {"data": {}}

    result = execute_replay(
        bundle,
        invoke_route=invoke,
        correlation_id="replay-run",
        current_runtime_fingerprint_value="sha256:runtime",
    )
    assert result["status"] == "MATCH"
    assert result["match"] is True
    assert calls == list(ALLOWED_ROUTES)
    assert result["route_trace"] == list(ALLOWED_ROUTES)
    assert not ({"base_collection", "dynamic_collection", "authenticated_collection", "enrichment_collection", "historical_prior_resolve"} & set(calls))
    assert result["governance"]["refetched_current_sources"] is False
    assert result["governance"]["network_refresh_allowed"] is False
    assert result["governance"]["historical_prior_network_refresh"] is False
    assert result["governance"]["promotion_authority"] is False
    assert result["decision"]["final_state"] == "HOLD_WAIT_REVIEW_ONLY"
