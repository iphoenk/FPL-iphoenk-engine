from __future__ import annotations

from pathlib import Path

from src.engines import v4_backtest_store as store
from src.engines.v4_maturity_reconciler import _find_module, _recount
from src.engines.v4_validation import interval_coverage, mae, promotion_gate, ranking_metrics
from src.utils import DATA, atomic_json, read_json

HEALTH = DATA / "framework_health_v4.json"
PREDICTIONS = DATA / "predictions_v4.json"
RECONCILED = DATA / "validation" / "reconciled"
WARMUP_MODULES = ("DSS-44", "DSS-X12")
MINIMUM_RECONCILED_ROWS = 300


def _calibration_evidence(
    reconciled_dir: Path = RECONCILED,
    *,
    model_version: str | None = None,
) -> tuple[bool, dict]:
    """Evaluate calibration maturity only from eligible immutable production reconciliations.

    The eligibility view is produced by the validation lifecycle from the append-only
    reconciliation archive. Every row is re-validated against its immutable deadline
    snapshot before it can contribute to the maturity gate. Merely having a file is
    never sufficient for promotion.
    """
    paths = sorted(reconciled_dir.glob("gw*.json")) if reconciled_dir.exists() else []
    if not paths:
        return False, {
            "implementation_state": "ACTIVE",
            "maturity_state": "WARMUP",
            "reason": "no eligible reconciled post-GW sample exists yet",
            "eligible_reconciliations": 0,
            "reconciled_rows": 0,
            "minimum_reconciled_rows": MINIMUM_RECONCILED_ROWS,
            "promotion_rule": "existing v4_validation.promotion_gate over integrity-checked current-model reconciliation rows",
            "simulation_can_mutate_store": False,
            "missing_starts_excluded_from_start_calibration": True,
            "retrospective_prediction_reconstruction_forbidden": True,
        }

    rows: list[dict] = []
    eligible_gws: list[int] = []
    rejected: list[dict] = []
    start_n = 0
    start_missing = 0
    for path in paths:
        sample = read_json(path, {})
        ok, reason = store.reconciled_integrity(sample, model_version=model_version)
        if not ok:
            rejected.append({"file": path.name, "reason": reason})
            continue
        report = sample.get("report") or {}
        metrics = report.get("metrics") or {}
        if metrics.get("status") != "PASS" or int(metrics.get("leakage_rejected") or 0) != 0:
            rejected.append({"file": path.name, "reason": "reconciliation_metrics_not_safe"})
            continue
        sample_rows = list(report.get("rows") or [])
        if not sample_rows:
            rejected.append({"file": path.name, "reason": "reconciliation_rows_missing"})
            continue
        rows.extend(sample_rows)
        eligible_gws.append(int(sample.get("gw") or 0))
        minutes = metrics.get("minutes") or {}
        start_n += int(minutes.get("start_n") or 0)
        start_missing += int(minutes.get("start_missing") or 0)

    if not rows:
        return False, {
            "implementation_state": "ACTIVE",
            "maturity_state": "WARMUP",
            "reason": "no integrity-checked current-model reconciliation rows are eligible",
            "eligible_reconciliations": 0,
            "reconciled_rows": 0,
            "minimum_reconciled_rows": MINIMUM_RECONCILED_ROWS,
            "rejected_reconciliations": rejected,
            "promotion_rule": "existing v4_validation.promotion_gate over integrity-checked current-model reconciliation rows",
            "simulation_can_mutate_store": False,
            "missing_starts_excluded_from_start_calibration": True,
            "retrospective_prediction_reconstruction_forbidden": True,
        }

    coverage = interval_coverage(rows)
    aggregate_metrics = {
        "status": "PASS",
        "n": len(rows),
        "mae": round(mae(rows), 4),
        "ranking": ranking_metrics(rows),
        "interval80_coverage": round(coverage, 4) if coverage is not None else None,
    }
    gate = promotion_gate({"metrics": aggregate_metrics}, minimum_n=MINIMUM_RECONCILED_ROWS)
    promote = gate.get("promote") is True
    detail = {
        "implementation_state": "ACTIVE",
        "maturity_state": "ACTIVE" if promote else "WARMUP",
        "eligible_reconciliations": len(eligible_gws),
        "eligible_gws": eligible_gws,
        "reconciled_rows": len(rows),
        "minimum_reconciled_rows": MINIMUM_RECONCILED_ROWS,
        "aggregate_metrics": aggregate_metrics,
        "promotion_gate": gate,
        "rejected_reconciliations": rejected,
        "official_start_calibration_rows": start_n,
        "missing_start_rows_excluded": start_missing,
        "promotion_rule": "deterministic existing v4_validation.promotion_gate over integrity-checked current-model reconciliation rows",
        "archive_authority": "data/validation/archive/reconciled",
        "eligibility_view": "data/validation/reconciled",
        "simulation_can_mutate_store": False,
        "missing_starts_excluded_from_start_calibration": True,
        "retrospective_prediction_reconstruction_forbidden": True,
    }
    return promote, detail


def reconcile(health: dict | None = None) -> dict:
    health = health if health is not None else read_json(HEALTH, {})
    if not health:
        raise RuntimeError("warmup governance requires framework health artifact")
    predictions = read_json(PREDICTIONS, {})
    model_version = predictions.get("model_version")
    promote, detail = _calibration_evidence(model_version=model_version)

    evaluated: list[str] = []
    preserved_failed: list[str] = []
    for module_id in WARMUP_MODULES:
        row = _find_module(health, module_id)
        if row is None:
            continue
        evaluated.append(module_id)
        if row.get("status") == "FAILED":
            preserved_failed.append(module_id)
            continue
        row["status"] = "ACTIVE" if promote else "WARMUP"
        row["detail"] = {**detail, "module_id": module_id}

    _recount(health)
    health["warmup_governance"] = {
        "schema_version": 1,
        "evaluated_modules": evaluated,
        "preserved_failed_modules": preserved_failed,
        "promotion_allowed": promote,
        "minimum_reconciled_rows": MINIMUM_RECONCILED_ROWS,
        "file_presence_alone_never_promotes": True,
        "current_model_only": True,
        "immutable_reconciliation_required": True,
        "simulation_never_mutates_validation_store": True,
        "critical_warmup_blocks_unqualified_go": True,
        "detail": detail,
    }
    atomic_json(HEALTH, health)
    return health
