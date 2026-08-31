import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "v5_convergence_manifest.json"
RUNTIME_EVIDENCE_AUTHORITY = "v5-shadow-runtime:data/v5/shadow/acceptance_summary.json"
PRODUCTION_SOURCE_AUTHORITY = "runtime-data:data/runtime_manifest.json#source_commit"


def _manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_production_reanchor_supersedes_prior_operational_acceptance():
    manifest = _manifest()
    evidence = manifest["operational_acceptance_evidence"]
    promotion = manifest["production_promotion"]
    old = evidence["superseded_evidence"]
    authority = manifest["baselines"]["production_source_authority"]

    assert evidence["status"] == "SUPERSEDED_BY_PRODUCTION_REANCHOR_PENDING_REVALIDATION"
    assert evidence["release_fingerprint"] is None
    assert evidence["validated_real_shadow_cycles"] == 0
    assert evidence["required_real_shadow_cycles"] == 3
    assert evidence["remaining_validated_cycles"] == 3
    assert evidence["operational_candidate_eligible"] is False
    assert evidence["authority"] == RUNTIME_EVIDENCE_AUTHORITY
    assert evidence["materialized_status_snapshot_only"] is True

    assert old["release_fingerprint"].startswith("sha256:")
    assert old["validated_real_shadow_cycles"] == 3
    assert old["latest_validated_at"]
    assert authority == PRODUCTION_SOURCE_AUTHORITY
    reason = old["reason"].lower()
    assert "superseded" in reason
    assert "runtime-data" in reason
    assert "fresh exact-identity validation" in reason

    assert promotion["validated_real_shadow_cycles"] == 0
    assert promotion["required_real_shadow_cycles"] == 3
    assert promotion["operational_acceptance_complete"] is False
    assert promotion["operational_evidence_authority"] == RUNTIME_EVIDENCE_AUTHORITY
    assert promotion["materialized_status_snapshot_only"] is True


def test_operational_revalidation_does_not_bypass_prediction_or_production_gates():
    manifest = _manifest()
    evidence = manifest["operational_acceptance_evidence"]
    promotion = manifest["production_promotion"]

    assert evidence["prediction_candidate_eligible"] is False
    assert evidence["production_candidate_eligible"] is False
    assert promotion["prediction_acceptance_complete"] is False
    assert promotion["production_candidate"] is False
    assert promotion["allowed"] is False
    assert promotion["beta"] is True
