from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.v5.shadow_acceptance as accounting


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _cycle(
    cycle_id: str,
    *,
    v5: str,
    v3_runtime: str,
    baseline: str,
    sha: str,
    fingerprint: str,
    runtime_schema: int = 49,
    post: str = "PASS",
    cycle_pass: bool = True,
) -> dict:
    return {
        "schema_version": 10,
        "cycle_id": cycle_id,
        "generated_at": f"2026-08-27T00:0{cycle_id[-1]}:00+00:00",
        "mode": "REAL_SHADOW",
        "v3": {"engine_version": v3_runtime, "schema_version": runtime_schema},
        "v5": {"engine_version": v5},
        "acceptance_context": {
            "production_baseline_version": baseline,
            "production_main_sha": sha,
            "production_runtime_engine_version": v3_runtime,
            "production_runtime_schema_version": runtime_schema,
            "release_fingerprint": fingerprint,
        },
        "parity": {"pass": cycle_pass},
        "operational_invariants": {"pass": cycle_pass, "checks": {}},
        "acceptance_progress": {"cycle_pass": cycle_pass},
        "post_validation": {"status": post, "validated_at": "2026-08-27T00:10:00+00:00"},
    }


def _with_official_auth_proof(payload: dict, *, valid: bool, authority: str = "official_public") -> dict:
    payload["acceptance_context"].update(
        {
            "official_auth_validation_required": True,
            "official_auth_proof_contract": accounting.AUTH_PROOF_CONTRACT,
        }
    )
    payload["v5"].update(
        {
            "phase": "PRE_DEADLINE",
            "squad_authority": authority,
            "decision_squad_authority": authority,
            "authenticated_official": {
                "state": "VALID" if valid else "DISABLED",
                "expected_entry": 3462711,
                "verified_entry": 3462711 if valid else None,
                "raw_authenticated_payload_persisted": False,
            },
        }
    )
    payload["official_auth_proof"] = {
        "authenticated_requirement_active": True,
        "authenticated_role": "OPTIONAL_PRIVATE_ENRICHMENT",
        "authenticated_proof_contract": accounting.AUTH_PROOF_CONTRACT,
        "authority": authority,
        "auth_state": "VALID" if valid else "DISABLED",
        "verified_entry": 3462711 if valid else None,
        "raw_authenticated_payload_persisted": False,
    }
    return payload


def _strict_policy() -> dict:
    return {
        "require_post_validation_pass": True,
        "require_same_v5_version": True,
        "require_same_production_baseline": True,
        "require_same_release_fingerprint": True,
        "require_prediction_acceptance_for_production_candidate": True,
        "reject_claimed_official_auth_validation_without_proof": True,
    }


def test_accounting_counts_runtime_reference_even_when_frozen_truth_version_differs(tmp_path, monkeypatch):
    baseline = "v3.20.0"
    sha = "abc123"
    fingerprint = "sha256:test-runtime"
    monkeypatch.setattr(accounting, "V5_VERSION", "5.0.0-beta.4")
    monkeypatch.setattr(accounting, "_baseline", lambda: (baseline, sha))
    monkeypatch.setattr(accounting, "_required_cycles", lambda: 3)
    monkeypatch.setattr(accounting, "_current_release_fingerprint", lambda: fingerprint)
    monkeypatch.setattr(accounting, "_accounting_policy", _strict_policy)

    cycles = tmp_path / "cycles"
    _write(cycles / "c1.json", _cycle("c1", v5="5.0.0-beta.4", v3_runtime="3.25.0", baseline=baseline, sha=sha, fingerprint=fingerprint))
    _write(cycles / "c2.json", _cycle("c2", v5="5.0.0-beta.4", v3_runtime="3.25.0", baseline=baseline, sha=sha, fingerprint=fingerprint, post="PENDING"))
    _write(cycles / "c3.json", _cycle("c3", v5="5.0.0-beta.3", v3_runtime="3.25.0", baseline=baseline, sha=sha, fingerprint=fingerprint))
    bad_runtime = _cycle("c4", v5="5.0.0-beta.4", v3_runtime="3.25.0", baseline=baseline, sha=sha, fingerprint=fingerprint)
    bad_runtime["acceptance_context"]["production_runtime_engine_version"] = "3.24.0"
    _write(cycles / "c4.json", bad_runtime)
    _write(cycles / "c5.json", _cycle("c5", v5="5.0.0-beta.4", v3_runtime="3.25.0", baseline=baseline, sha=sha, fingerprint="sha256:different-runtime"))

    rows = accounting._validated_cycles(cycles)
    assert [row["cycle_id"] for row in rows] == ["c1"]
    assert rows[0]["v3_engine_version"] == "3.25.0"
    assert rows[0]["release_fingerprint"] == fingerprint


def test_finalize_marks_cycle_validated_and_computes_three_of_three_when_prediction_gate_passes(tmp_path, monkeypatch):
    baseline = "v3.20.0"
    sha = "abc123"
    fingerprint = "sha256:test-runtime"
    monkeypatch.setattr(accounting, "V5_VERSION", "5.0.0-beta.4")
    monkeypatch.setattr(accounting, "_baseline", lambda: (baseline, sha))
    monkeypatch.setattr(accounting, "_required_cycles", lambda: 3)
    monkeypatch.setattr(accounting, "_current_release_fingerprint", lambda: fingerprint)
    monkeypatch.setattr(accounting, "_accounting_policy", _strict_policy)
    monkeypatch.setattr(accounting, "_prediction_acceptance", lambda _out: {
        "eligible": True, "status": "PASS", "checks": {"settled_evidence": True},
        "settled_gameweeks": 4, "sample_size": 1000, "confidence": "HIGH",
    })

    cycles = tmp_path / "cycles"
    for cycle_id in ("c1", "c2"):
        _write(cycles / f"{cycle_id}.json", _cycle(cycle_id, v5="5.0.0-beta.4", v3_runtime="3.25.0", baseline=baseline, sha=sha, fingerprint=fingerprint))
    current = _cycle("c3", v5="5.0.0-beta.4", v3_runtime="3.25.0", baseline=baseline, sha=sha, fingerprint=fingerprint, post="PENDING")
    latest = tmp_path / "latest_shadow_cycle.json"
    _write(latest, current)
    _write(cycles / "c3.json", current)

    summary = accounting.finalize(str(latest), str(tmp_path))
    persisted = json.loads(latest.read_text(encoding="utf-8"))

    assert summary["validated_successful_cycles"] == 3
    assert summary["remaining_validated_cycles"] == 0
    assert summary["operational_candidate_eligible"] is True
    assert summary["prediction_candidate_eligible"] is True
    assert summary["production_candidate_eligible"] is True
    assert summary["production_candidate_auto_promoted"] is False
    assert persisted["post_validation"]["status"] == "PASS"
    assert persisted["post_validation"]["validator_contract"] == "V5_REAL_SHADOW_POSTVALIDATION_V6"
    assert persisted["acceptance_progress"]["counts_as_successful_acceptance_cycle"] is True
    assert persisted["acceptance_progress"]["production_candidate_eligible"] is True


def test_three_operational_cycles_do_not_bypass_prediction_acceptance(tmp_path, monkeypatch):
    baseline = "v3.20.0"
    sha = "abc123"
    fingerprint = "sha256:test-runtime"
    monkeypatch.setattr(accounting, "V5_VERSION", "5.0.0-beta.4")
    monkeypatch.setattr(accounting, "_baseline", lambda: (baseline, sha))
    monkeypatch.setattr(accounting, "_required_cycles", lambda: 3)
    monkeypatch.setattr(accounting, "_current_release_fingerprint", lambda: fingerprint)
    monkeypatch.setattr(accounting, "_accounting_policy", _strict_policy)
    monkeypatch.setattr(accounting, "_prediction_acceptance", lambda _out: {
        "eligible": False, "status": "INSUFFICIENT_OR_UNPROVEN_SETTLED_EVIDENCE",
        "checks": {"settled_evidence": False}, "settled_gameweeks": 0,
        "sample_size": 0, "confidence": "LOW",
    })

    cycles = tmp_path / "cycles"
    for cycle_id in ("c1", "c2"):
        _write(cycles / f"{cycle_id}.json", _cycle(cycle_id, v5="5.0.0-beta.4", v3_runtime="3.25.0", baseline=baseline, sha=sha, fingerprint=fingerprint))
    current = _cycle("c3", v5="5.0.0-beta.4", v3_runtime="3.25.0", baseline=baseline, sha=sha, fingerprint=fingerprint, post="PENDING")
    latest = tmp_path / "latest_shadow_cycle.json"
    _write(latest, current)
    _write(cycles / "c3.json", current)

    summary = accounting.finalize(str(latest), str(tmp_path))
    assert summary["operational_candidate_eligible"] is True
    assert summary["prediction_candidate_eligible"] is False
    assert summary["production_candidate_eligible"] is False


def test_claimed_official_auth_validation_accepts_optional_enrichment_without_squad_authority(monkeypatch):
    baseline = "v3.20.0"
    sha = "abc123"
    fingerprint = "sha256:test-runtime"
    monkeypatch.setattr(accounting, "V5_VERSION", "5.0.0-beta.4")
    monkeypatch.setattr(accounting, "_baseline", lambda: (baseline, sha))
    monkeypatch.setattr(accounting, "_current_release_fingerprint", lambda: fingerprint)
    monkeypatch.setattr(accounting, "_accounting_policy", _strict_policy)
    payload = _with_official_auth_proof(
        _cycle("c1", v5="5.0.0-beta.4", v3_runtime="3.39.0", baseline=baseline, sha=sha, fingerprint=fingerprint),
        valid=True,
        authority="official_public",
    )
    assert accounting._official_auth_validation_ok(payload) is True
    assert accounting.validated_cycle_eligible(payload) is True


def test_claimed_official_auth_validation_accepts_user_capture_as_primary_when_auth_is_enrichment(monkeypatch):
    baseline = "v3.20.0"
    sha = "abc123"
    fingerprint = "sha256:test-runtime"
    monkeypatch.setattr(accounting, "V5_VERSION", "5.0.0-beta.4")
    monkeypatch.setattr(accounting, "_baseline", lambda: (baseline, sha))
    monkeypatch.setattr(accounting, "_current_release_fingerprint", lambda: fingerprint)
    monkeypatch.setattr(accounting, "_accounting_policy", _strict_policy)
    payload = _with_official_auth_proof(
        _cycle("c1", v5="5.0.0-beta.4", v3_runtime="3.39.0", baseline=baseline, sha=sha, fingerprint=fingerprint),
        valid=True,
        authority="user_capture",
    )
    assert accounting._official_auth_validation_ok(payload) is True


def test_authenticated_official_becoming_squad_authority_is_rejected(monkeypatch):
    baseline = "v3.20.0"
    sha = "abc123"
    fingerprint = "sha256:test-runtime"
    monkeypatch.setattr(accounting, "V5_VERSION", "5.0.0-beta.4")
    monkeypatch.setattr(accounting, "_baseline", lambda: (baseline, sha))
    monkeypatch.setattr(accounting, "_current_release_fingerprint", lambda: fingerprint)
    monkeypatch.setattr(accounting, "_accounting_policy", _strict_policy)
    payload = _with_official_auth_proof(
        _cycle("c1", v5="5.0.0-beta.4", v3_runtime="3.39.0", baseline=baseline, sha=sha, fingerprint=fingerprint),
        valid=True,
        authority="official_authenticated",
    )
    assert accounting._official_auth_validation_ok(payload) is False
    assert accounting.validated_cycle_eligible(payload) is False


def test_finalize_cannot_turn_missing_official_auth_into_postvalidated_pass(tmp_path, monkeypatch):
    baseline = "v3.20.0"
    sha = "abc123"
    fingerprint = "sha256:test-runtime"
    monkeypatch.setattr(accounting, "V5_VERSION", "5.0.0-beta.4")
    monkeypatch.setattr(accounting, "_baseline", lambda: (baseline, sha))
    monkeypatch.setattr(accounting, "_current_release_fingerprint", lambda: fingerprint)
    monkeypatch.setattr(accounting, "_accounting_policy", _strict_policy)
    payload = _with_official_auth_proof(
        _cycle("c1", v5="5.0.0-beta.4", v3_runtime="3.39.0", baseline=baseline, sha=sha, fingerprint=fingerprint, post="PENDING"),
        valid=False,
        authority="official_public",
    )
    latest = tmp_path / "latest_shadow_cycle.json"
    _write(latest, payload)
    with pytest.raises(RuntimeError, match="optional-enrichment proof"):
        accounting.finalize(str(latest), str(tmp_path))


def test_effective_summary_fails_stale_without_destroying_historical_evidence(monkeypatch):
    monkeypatch.setattr(accounting, "V5_VERSION", "5.0.0-beta.4")
    monkeypatch.setattr(accounting, "_baseline", lambda: ("v3.20.0", "newsha"))
    monkeypatch.setattr(accounting, "_current_release_fingerprint", lambda: "sha256:new")
    monkeypatch.setattr(accounting, "_required_cycles", lambda: 3)
    stored = {
        "v5_version": "5.0.0-beta.4",
        "production_baseline_version": "v3.20.0",
        "production_main_sha": "oldsha",
        "release_fingerprint": "sha256:old",
        "required_validated_cycles": 3,
        "validated_successful_cycles": 3,
        "remaining_validated_cycles": 0,
        "operational_candidate_eligible": True,
        "production_candidate_eligible": True,
        "validated_cycles": [{"cycle_id": "historical"}],
    }
    effective = accounting.effective_acceptance_summary(stored)
    assert effective["stored_operational_candidate_eligible"] is True
    assert effective["effective_identity_current"] is False
    assert effective["effective_state"] == "SUPERSEDED_BY_CURRENT_BASELINE_OR_FINGERPRINT"
    assert effective["validated_successful_cycles"] == 0
    assert effective["remaining_validated_cycles"] == 3
    assert effective["operational_candidate_eligible"] is False
    assert effective["production_candidate_eligible"] is False
    assert effective["validated_cycles"] == [{"cycle_id": "historical"}]
