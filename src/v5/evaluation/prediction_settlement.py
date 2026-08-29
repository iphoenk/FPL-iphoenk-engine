from __future__ import annotations
from datetime import datetime
from typing import Any
from src.v5.evaluation.temporal_backtest import validate_frozen_ledger


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def recover_overdue_predeadline_freezes(ledger: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Recover overdue records only from their last genuine pre-deadline forecast.

    This is a state-transition repair, not retroactive reconstruction. A forecast is
    eligible only when its own generated_at is on/before the record deadline. No
    post-deadline projection may be substituted and no decision formula is rerun.
    """
    records = ledger.get("records") if isinstance(ledger.get("records"), dict) else {}
    promoted: list[int] = []
    missed: list[int] = []
    for key, record in records.items():
        if not isinstance(record, dict) or record.get("status") == "SETTLED" or record.get("frozen_forecast"):
            continue
        deadline = _dt(record.get("deadline_time"))
        if deadline is None or now < deadline:
            continue
        candidate = record.get("latest_pre_deadline_forecast") if isinstance(record.get("latest_pre_deadline_forecast"), dict) else None
        generated = _dt((candidate or {}).get("generated_at"))
        gw = int(record.get("gw") or key)
        if candidate and generated and generated <= deadline:
            record["frozen_forecast"] = candidate
            record["frozen_at"] = now.isoformat()
            record["freeze_recovery"] = {
                "state": "RECOVERED_FROM_GENUINE_PREDEADLINE_SNAPSHOT",
                "forecast_generated_at": candidate.get("generated_at"),
                "deadline_time": record.get("deadline_time"),
                "retroactive_reconstruction": False,
            }
            promoted.append(gw)
        else:
            record["freeze_recovery"] = {
                "state": "MISSED_NO_VALID_PREDEADLINE_SNAPSHOT",
                "retroactive_reconstruction": False,
            }
            missed.append(gw)
    return {
        "model": "v5_overdue_prediction_freeze_recovery_v1",
        "promoted_gameweeks": sorted(promoted),
        "missed_gameweeks": sorted(missed),
        "promoted_count": len(promoted),
        "missed_count": len(missed),
        "governance": {
            "genuine_predeadline_snapshot_only": True,
            "postdeadline_projection_substitution_forbidden": True,
            "retroactive_reconstruction_forbidden": True,
        },
    }


def build_settlement_artifact(ledger: dict[str, Any], accuracy: dict[str, Any]) -> dict[str, Any]:
    records = ledger.get("records") if isinstance(ledger.get("records"), dict) else {}
    settled = sorted(int(k) for k,v in records.items() if isinstance(v,dict) and v.get("status") == "SETTLED")
    recovered = sorted(
        int(k) for k, v in records.items()
        if isinstance(v, dict)
        and isinstance(v.get("freeze_recovery"), dict)
        and v["freeze_recovery"].get("state") == "RECOVERED_FROM_GENUINE_PREDEADLINE_SNAPSHOT"
    )
    return {
        "schema_version": 2,
        "model": "v5_prediction_settlement_v2",
        "settled_gameweeks": settled,
        "recovered_predeadline_freeze_gameweeks": recovered,
        "sample_size": int(((accuracy.get("overall") or {}).get("sample_size")) or 0),
        "temporal_guard": validate_frozen_ledger(ledger),
        "baseline_comparison": accuracy.get("baseline_comparison"),
        "eligible_for_accuracy_claim": bool(settled) and int(((accuracy.get("overall") or {}).get("sample_size")) or 0) > 0,
        "governance": {
            "overdue_recovery_uses_genuine_predeadline_snapshot_only": True,
            "retroactive_prediction_reconstruction_forbidden": True,
        },
    }
