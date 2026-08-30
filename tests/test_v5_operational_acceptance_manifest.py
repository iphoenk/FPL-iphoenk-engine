import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "v5_convergence_manifest.json"


def _manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_operational_acceptance_closeout_is_internally_consistent():
    manifest = _manifest()
    evidence = manifest["operational_acceptance_evidence"]
    promotion = manifest["production_promotion"]

    assert evidence["status"] == "COMPLETE"
    assert evidence["validated_real_shadow_cycles"] >= evidence["required_real_shadow_cycles"]
    assert evidence["remaining_validated_cycles"] == 0
    assert evidence["operational_candidate_eligible"] is True
    assert evidence["release_fingerprint"].startswith("sha256:")
    assert evidence["evidence_contract"] == "v5_postvalidated_shadow_acceptance_v5"
    assert evidence["source_branch"] == "v5-shadow-runtime"

    assert promotion["validated_real_shadow_cycles"] == evidence["validated_real_shadow_cycles"]
    assert promotion["required_real_shadow_cycles"] == evidence["required_real_shadow_cycles"]
    assert promotion["operational_acceptance_complete"] is True


def test_operational_acceptance_does_not_bypass_prediction_or_production_gates():
    manifest = _manifest()
    evidence = manifest["operational_acceptance_evidence"]
    promotion = manifest["production_promotion"]

    assert evidence["prediction_candidate_eligible"] is False
    assert evidence["production_candidate_eligible"] is False
    assert promotion["prediction_acceptance_complete"] is False
    assert promotion["production_candidate"] is False
    assert promotion["allowed"] is False
    assert promotion["beta"] is True
