from __future__ import annotations

from src.v5.artifact_contracts import validate_payload
from src.v5.decision.decision_trace import bind_execution_fingerprint
from src.v5.release_integrity import (
    build_exact_execution_fingerprint,
    build_replay_fingerprint,
    replay_output_fingerprint,
    verify_replay_outputs,
)
from src.v5.replay_capture import build_replay_capture, finalize_replay_bundle
from src.v5.services import snapshot as snapshot_service


def _replay_inputs():
    return {
        "bootstrap": {"elements": [{"id": 1, "web_name": "A"}]},
        "fixtures": [{"id": 10, "event": 2}],
        "truth": {"context": {"planning_gw": 2}, "team": {"owned_ids": [1]}},
        "event_live": {"elements": []},
        "source_fusion": {"status": "READY"},
        "state_hydration": {
            "price_trajectory": {},
            "historical_prior": {"status": "READY"},
            "prediction_ledger": {"records": {}},
            "challenger_observations": {"observations": []},
        },
        "runner_policy": {"mode": "daily", "prediction_horizon_gws": 5},
    }


def test_replay_fingerprint_is_deterministic_across_dict_order():
    inputs = _replay_inputs()
    reversed_inputs = dict(reversed(list(inputs.items())))
    first = build_replay_fingerprint(inputs, runtime_release_fingerprint="sha256:runtime")
    second = build_replay_fingerprint(reversed_inputs, runtime_release_fingerprint="sha256:runtime")
    assert first["replay_fingerprint"] == second["replay_fingerprint"]
    assert first["component_hashes"] == second["component_hashes"]


def test_execution_identity_changes_without_changing_replay_identity():
    inputs = _replay_inputs()
    first = build_exact_execution_fingerprint(
        inputs,
        correlation_id="run-a",
        captured_at="2026-08-28T01:00:00+00:00",
        runtime_release_fingerprint="sha256:runtime",
        environ={"V5_CODE_REVISION": "abc123"},
    )
    second = build_exact_execution_fingerprint(
        inputs,
        correlation_id="run-b",
        captured_at="2026-08-28T01:01:00+00:00",
        runtime_release_fingerprint="sha256:runtime",
        environ={"V5_CODE_REVISION": "abc123"},
    )
    assert first["replay_fingerprint"] == second["replay_fingerprint"]
    assert first["execution_fingerprint"] != second["execution_fingerprint"]
    assert first["promotion_fingerprint_complete"] is True


def test_replay_output_hash_ignores_only_declared_volatile_fields():
    left = {"status": "READY", "score": 5.5, "generated_at": "one", "correlation_id": "a"}
    right = {"correlation_id": "b", "generated_at": "two", "score": 5.5, "status": "READY"}
    changed = {**right, "score": 5.6}
    assert replay_output_fingerprint(left) == replay_output_fingerprint(right)
    assert replay_output_fingerprint(left) != replay_output_fingerprint(changed)


def test_replay_output_verifier_detects_substantive_drift():
    expected = {"decision": replay_output_fingerprint({"action": "HOLD", "generated_at": "a"})}
    matching = verify_replay_outputs(expected, {"decision": {"action": "HOLD", "generated_at": "b"}})
    drifted = verify_replay_outputs(expected, {"decision": {"action": "TRANSFER", "generated_at": "b"}})
    assert matching["status"] == "MATCH"
    assert matching["match"] is True
    assert drifted["status"] == "MISMATCH"
    assert drifted["match"] is False


def test_point_in_time_capture_excludes_raw_authenticated_payload(monkeypatch):
    monkeypatch.setattr("src.v5.replay_capture.current_runtime_fingerprint", lambda: "sha256:runtime")
    states = {
        "price_trajectory": {"data": {}},
        "historical_prior": {"data": {"status": "READY"}},
        "prediction_ledger": {"data": {"records": {}}},
        "challenger_observations": {"data": {"observations": []}},
    }
    capture = build_replay_capture(
        correlation_id="run-a",
        team_id=123,
        mode="daily",
        bootstrap={"elements": []},
        fixtures=[],
        truth={"context": {}, "team": {}},
        event_live=None,
        source_fusion={"status": "READY"},
        states=states,
        runner_cfg={"status": "BETA", "prediction_horizon_gws": 5},
        feature_switches={},
        captured_at="2026-08-28T01:00:00+00:00",
    )
    assert capture["replay_boundary"] == "POST_TRUTH_PRE_INTELLIGENCE"
    assert capture["governance"]["raw_authenticated_payload_persisted"] is False
    assert capture["governance"]["refetch_current_sources_on_replay"] is False
    assert "auth_runtime" not in capture["inputs"]
    assert "raw_authenticated_payload" not in capture["inputs"]


def test_replay_bundle_contract_accepts_finalized_capture(monkeypatch):
    monkeypatch.setattr("src.v5.replay_capture.current_runtime_fingerprint", lambda: "sha256:runtime")
    states = {
        "price_trajectory": {"data": {}},
        "historical_prior": {"data": {}},
        "prediction_ledger": {"data": {}},
        "challenger_observations": {"data": {}},
    }
    capture = build_replay_capture(
        correlation_id="run-a",
        team_id=123,
        mode="daily",
        bootstrap={"elements": []},
        fixtures=[],
        truth={"context": {}, "team": {}},
        event_live=None,
        source_fusion={},
        states=states,
        runner_cfg={"status": "BETA", "prediction_horizon_gws": 5},
        feature_switches={},
        captured_at="2026-08-28T01:00:00+00:00",
    )
    bundle = finalize_replay_bundle(
        capture,
        price={},
        prediction={},
        evaluation={},
        decision={},
        framework={},
    )
    result = validate_payload("replay_bundle", bundle)
    assert result["validation"] == "CONTRACT_VALID"
    assert set(bundle["expected_output_hashes"]) == {"price", "prediction", "evaluation", "decision", "framework"}


def test_snapshot_service_forwards_gameweek_to_persistence(monkeypatch):
    called = {}

    def fake_write_snapshot(snapshot, *, gw=None):
        called["snapshot"] = snapshot
        called["gw"] = gw
        return {"latest": "data/v5/latest.json", "gameweek": f"data/v5/gw/{gw:02d}.json"}

    monkeypatch.setattr(snapshot_service, "write_snapshot", fake_write_snapshot)
    payload = {"schema_version": 1, "engine_version": "test"}
    result = snapshot_service.handle("snapshot", {"snapshot": payload, "gw": 2})
    assert called["snapshot"] == payload
    assert called["gw"] == 2
    assert result["gameweek"].endswith("02.json")


def test_decision_trace_v2_binds_fingerprint_as_provenance_only():
    trace = {"decision_type": "HOLD", "score": 0.0}
    fingerprint = {
        "runtime_release_fingerprint": "sha256:runtime",
        "replay_fingerprint": "sha256:replay",
        "execution_fingerprint": "sha256:execution",
        "code_revision": {"status": "AVAILABLE", "value": "abc123"},
        "promotion_fingerprint_complete": True,
    }
    bound = bind_execution_fingerprint(trace, fingerprint)
    assert bound["trace_contract"] == "V5_DECISION_TRACE_V2"
    assert bound["replay_fingerprint"] == "sha256:replay"
    assert bound["execution_fingerprint"] == "sha256:execution"
    assert bound["fingerprint_binding"]["bound"] is True
    assert bound["fingerprint_binding"]["scoring_input"] is False
    assert bound["fingerprint_binding"]["provenance_only"] is True
