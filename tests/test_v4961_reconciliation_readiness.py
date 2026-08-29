import json
from pathlib import Path

from src.services.reconciliation_readiness_service import classify_stage

ROOT = Path(__file__).resolve().parents[1]


def test_readiness_stage_machine_distinguishes_expected_waits_from_blockers():
    assert classify_stage(before_deadline=True, submitted_picks_ready=False, finished=False, actuals_ready=False, archive_ready=False) == "PREDEADLINE_READY"
    assert classify_stage(before_deadline=False, submitted_picks_ready=False, finished=False, actuals_ready=False, archive_ready=False) == "WAITING_SUBMITTED_PICKS"
    assert classify_stage(before_deadline=False, submitted_picks_ready=True, finished=False, actuals_ready=False, archive_ready=False) == "WAITING_GW_FINISH"
    assert classify_stage(before_deadline=False, submitted_picks_ready=True, finished=True, actuals_ready=True, archive_ready=False) == "READY_TO_RECONCILE"
    assert classify_stage(before_deadline=False, submitted_picks_ready=True, finished=True, actuals_ready=False, archive_ready=True) == "RECONCILED"


def test_reconciliation_readiness_is_distinct_responsibility_inside_validation_boundary():
    services = json.loads((ROOT / "config/service_registry.json").read_text())
    validation = next(item for item in services["services"] if item["id"] == "validation")
    assert validation["module"] == "src.services.validation_service"
    assert "reconciliation_readiness" in validation["produces"]
    assert not any(item["id"] == "reconciliation_readiness" for item in services["services"])

    source = (ROOT / "src/services/reconciliation_readiness_service.py").read_text()
    assert "store.snapshot_integrity" in source
    assert "store.reconciled_integrity" in source
    assert "reconcile_finished_gw" not in source
    assert "src.sources.official_fpl" not in source
    assert '"execution_boundary": "validation"' in source


def test_readiness_contract_and_logical_ownership_are_preserved():
    contracts = json.loads((ROOT / "config/service_contract_registry.json").read_text())
    spec = contracts["contracts"]["reconciliation_readiness"]
    assert spec["path"] == "data/validation/reconciliation_readiness_v4.json"
    assert spec["equals"]["status"] == "PASS"
    assert spec["equals"]["guardrails.read_only_audit"] is True
    assert spec["equals"]["guardrails.reconciliation_truth_not_reimplemented"] is True

    ownership = json.loads((ROOT / "config/architecture_ownership_registry.json").read_text())
    owner = next(row for row in ownership["responsibilities"] if row["id"] == "RECONCILIATION_READINESS")
    assert owner["owner"] == "reconciliation_readiness"
    assert owner["execution_boundary"] == "validation"
    integrity = next(row for row in ownership["shared_primitives"] if row["id"] == "VALIDATION_INTEGRITY")
    assert "reconciliation_readiness" in integrity["consumers"]
    assert integrity["owner"] == "validation_store"
