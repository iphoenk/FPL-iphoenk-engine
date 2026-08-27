import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "v5_capability_parity_registry.json"


def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_every_production_rec_has_explicit_v5_disposition():
    cfg = _registry()
    expected = {f"REC-{value:02d}" for value in range(1, 39)}
    expected.remove("REC-09")
    expected.update({"REC-09a", "REC-09b"})
    coverage = cfg["production_rec_coverage"]
    assert set(coverage) == expected
    assert all(row.get("production_status") for row in coverage.values())
    assert all(row.get("v5_status") for row in coverage.values())


def test_open_parity_is_fail_closed_and_blocks_rebaseline():
    cfg = _registry()
    coverage = cfg["production_rec_coverage"]
    blockers = sorted(key for key, row in coverage.items() if bool(row.get("blocking")))
    assert blockers == sorted(cfg["parity_drift"]["open_blockers"])
    assert blockers == ["REC-05", "REC-22", "REC-38"]
    assert cfg["parity_drift"]["promotion_blocked"] is True
    assert cfg["observed_production"]["rebaseline_complete"] is False
    assert cfg["governance"]["rebaseline_requires_zero_open_blockers"] is True


def test_rec02_robust_rate_parity_has_real_evidence_files():
    cfg = _registry()
    rec02 = cfg["production_rec_coverage"]["REC-02"]
    assert rec02["v5_status"] == "ADOPTED_AND_EXTENDED"
    assert rec02["blocking"] is False
    for relative in rec02["evidence"]:
        assert (ROOT / relative).exists(), relative


def test_rec36_historical_submission_parity_has_real_evidence_files():
    cfg = _registry()
    rec36 = cfg["production_rec_coverage"]["REC-36"]
    assert rec36["v5_status"] == "ADOPTED"
    for relative in rec36["evidence"]:
        assert (ROOT / relative).exists(), relative


def test_observed_production_is_not_silently_promoted_to_adopted_baseline():
    cfg = _registry()
    observed = cfg["observed_production"]
    authorities = cfg["authorities"]
    assert observed["through_rec"] == "REC-38"
    assert observed["main_sha"] != authorities["production_main_sha"]
    assert cfg["governance"]["observed_production_may_advance_ahead_of_adopted_baseline"] is True
