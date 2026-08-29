from __future__ import annotations

from typing import Any

from src.v5.evaluation.decision_validation import decision_regret

METRICS = ("captain_regret", "xi_regret", "transfer_comparator_realized_net_gain")


def build(ledger: dict[str, Any], snapshots: dict[str, Any]) -> dict[str, Any]:
    ledger_records = ledger.get("records") if isinstance(ledger.get("records"), dict) else {}
    snapshot_records = snapshots.get("records") if isinstance(snapshots.get("records"), dict) else {}
    values: dict[str, list[float]] = {name: [] for name in METRICS}
    settled_rows: list[dict[str, Any]] = []

    for key, record in ledger_records.items():
        if not isinstance(record, dict) or record.get("status") != "SETTLED":
            continue
        gw = int(record.get("gw") or key)
        actual_rows = ((record.get("actual") or {}).get("players") or [])
        actual = {
            int(row.get("element")): row
            for row in actual_rows
            if isinstance(row, dict) and row.get("element") is not None
        }
        snapshot = snapshot_records.get(str(gw)) if isinstance(snapshot_records.get(str(gw)), dict) else None
        metrics = decision_regret(snapshot, actual)
        settled_rows.append({"gw": gw, "metrics": metrics, "genuine_predeadline_snapshot": snapshot is not None})
        for name in METRICS:
            row = metrics.get(name) if isinstance(metrics.get(name), dict) else {}
            value = row.get("value")
            if value is not None and int(row.get("sample_size") or 0) > 0:
                values[name].append(float(value))

    decision_metrics: dict[str, Any] = {}
    flattened: dict[str, float | None] = {}
    for name in METRICS:
        samples = values[name]
        mean = round(sum(samples) / len(samples), 4) if samples else None
        decision_metrics[name] = {
            "status": "SETTLED" if samples else "NO_GENUINE_PREDEADLINE_SAMPLE",
            "sample_size": len(samples),
            "mean": mean,
        }
        flattened[name] = mean

    return {
        "model": "v5_prediction_promotion_evidence_v1",
        "decision_metrics": decision_metrics,
        "flattened_metrics": flattened,
        "settled_gameweeks_checked": sorted(row["gw"] for row in settled_rows),
        "rows": settled_rows,
        "governance": {
            "genuine_predeadline_snapshot_required": True,
            "postdeadline_reconstruction_forbidden": True,
            "exact_hit_cost_required_for_transfer_net_gain": True,
        },
    }
