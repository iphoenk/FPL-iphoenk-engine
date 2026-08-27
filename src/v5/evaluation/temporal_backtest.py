from __future__ import annotations
from datetime import datetime
from typing import Any

LOWER_IS_BETTER = {"points_mae", "xmins_mae", "starter_brier", "clean_sheet_brier"}
HIGHER_IS_BETTER = {"spearman"}

def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

def validate_frozen_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    checked = 0
    for key, record in (ledger.get("records") or {}).items():
        if not isinstance(record, dict):
            continue
        frozen = record.get("frozen_forecast")
        if not frozen:
            continue
        checked += 1
        deadline = _dt(record.get("deadline_time"))
        generated = _dt((frozen or {}).get("generated_at"))
        frozen_at = _dt(record.get("frozen_at"))
        if deadline and generated and generated > deadline:
            violations.append({"gw": int(record.get("gw") or key), "type": "FORECAST_AFTER_DEADLINE"})
        actual = record.get("actual") if isinstance(record.get("actual"), dict) else {}
        settled = _dt(actual.get("settled_at"))
        if settled and frozen_at and settled < frozen_at:
            violations.append({"gw": int(record.get("gw") or key), "type": "SETTLEMENT_PRECEDES_FREEZE"})
    return {
        "status": "PASS" if not violations else "FAIL",
        "checked_frozen_gameweeks": checked,
        "violations": violations,
        "time_travel_detected": bool(violations),
    }

def compare_to_frozen_baseline(metrics: dict[str, Any], baseline: dict[str, Any] | None, tolerances: dict[str, Any] | None = None) -> dict[str, Any]:
    baseline = baseline if isinstance(baseline, dict) else {}
    tolerances = tolerances if isinstance(tolerances, dict) else {}
    if not baseline:
        return {"status": "NO_FROZEN_BASELINE", "non_regression_pass": False, "checks": {}}
    checks: dict[str, bool] = {}
    for name in sorted(LOWER_IS_BETTER | HIGHER_IS_BETTER):
        current = metrics.get(name)
        base = baseline.get(name)
        if current is None or base is None:
            checks[name] = False
            continue
        tol = max(0.0, float(tolerances.get(name) or 0.0))
        if name in LOWER_IS_BETTER:
            checks[name] = float(current) <= float(base) + tol
        else:
            checks[name] = float(current) >= float(base) - tol
    return {
        "status": "PASS" if checks and all(checks.values()) else "FAIL",
        "non_regression_pass": bool(checks) and all(checks.values()),
        "checks": checks,
        "baseline": baseline,
    }
