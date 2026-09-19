from __future__ import annotations

"""V12 model-run evidence and calibration ledger primitives.

Evidence only: not a methodology authority, no V6 mutation/read, no scheduler
integration, and no production dependency on legacy calibration/runtime code.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "FPL_MASTER_V12_MODEL_EVIDENCE_V1"
FROZEN = "FROZEN_AWAITING_SETTLEMENT"
SETTLED = "SETTLED"
SAMPLE_BUCKETS = (("LOW_SAMPLE", 0, 49), ("MEDIUM_SAMPLE", 50, 149), ("HIGH_SAMPLE", 150, None))


class ModelEvidenceError(ValueError):
    pass


def _canon(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise ModelEvidenceError("value is not canonical-JSON serializable") from exc


def fingerprint(value: Any) -> str:
    return hashlib.sha256(_canon(value)).hexdigest()


def _text(value: Any, label: str) -> str:
    out = str(value or "").strip()
    if not out:
        raise ModelEvidenceError(f"{label} is required")
    return out


def _utc(value: Any, label: str) -> str:
    if isinstance(value, datetime):
        dt = value
    else:
        raw = _text(value, label)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ModelEvidenceError(f"{label} must be ISO-8601") from exc
    if dt.tzinfo is None:
        raise ModelEvidenceError(f"{label} must be timezone-aware")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _dt(value: Any, label: str) -> datetime:
    return datetime.fromisoformat(_utc(value, label).replace("Z", "+00:00"))


def _num(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ModelEvidenceError(f"{label} must be numeric") from exc
    if not math.isfinite(out):
        raise ModelEvidenceError(f"{label} must be finite")
    return out


def _prob(value: Any, label: str) -> float:
    out = _num(value, label)
    if not 0.0 <= out <= 1.0:
        raise ModelEvidenceError(f"{label} must be within [0,1]")
    return out


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def build_model_run_binding(
    *,
    input_snapshot_id: str,
    factual_snapshot_timestamps: Mapping[str, Any],
    factual_artifact_fingerprints: Mapping[str, str] | None,
    deterministic_factual_inputs: Any,
    model_version: str,
    feature_version: str,
    parameter_version: str,
    parameters: Any,
    calibration_version: str,
    calibration_cutoff: Any,
    calibration_parameters: Any,
    generated_at: Any,
    planning_gw: int,
    canonical_v12_revision: str,
) -> dict[str, Any]:
    if int(planning_gw) <= 0:
        raise ModelEvidenceError("planning_gw must be positive")
    timestamps = {str(k): _utc(v, f"{k} timestamp") for k, v in sorted(factual_snapshot_timestamps.items())}
    artifacts = {str(k): _text(v, str(k)) for k, v in sorted((factual_artifact_fingerprints or {}).items())}
    input_fp = fingerprint({
        "input_snapshot_id": _text(input_snapshot_id, "input_snapshot_id"),
        "factual_snapshot_timestamps": timestamps,
        "factual_artifact_fingerprints": artifacts,
        "deterministic_factual_inputs": deterministic_factual_inputs,
        "planning_gw": int(planning_gw),
    })
    model_fp = fingerprint({
        "model_version": _text(model_version, "model_version"),
        "feature_version": _text(feature_version, "feature_version"),
        "canonical_v12_revision": _text(canonical_v12_revision, "canonical_v12_revision"),
    })
    parameter_fp = fingerprint({"parameter_version": _text(parameter_version, "parameter_version"), "parameters": parameters})
    cutoff = _utc(calibration_cutoff, "calibration_cutoff")
    calibration_fp = fingerprint({
        "calibration_version": _text(calibration_version, "calibration_version"),
        "calibration_cutoff": cutoff,
        "calibration_parameters": calibration_parameters,
    })
    run_fp = fingerprint({
        "input_fingerprint": input_fp,
        "model_fingerprint": model_fp,
        "parameter_fingerprint": parameter_fp,
        "calibration_fingerprint": calibration_fp,
        "planning_gw": int(planning_gw),
        "canonical_v12_revision": canonical_v12_revision,
    })
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_kind": "MODEL_RUN_BINDING",
        "input_snapshot_id": input_snapshot_id,
        "factual_snapshot_timestamps": timestamps,
        "factual_artifact_fingerprints": artifacts,
        "model_version": model_version,
        "feature_version": feature_version,
        "parameter_version": parameter_version,
        "calibration_version": calibration_version,
        "calibration_cutoff": cutoff,
        "generated_at": _utc(generated_at, "generated_at"),
        "planning_gw": int(planning_gw),
        "canonical_v12_revision": canonical_v12_revision,
        "input_fingerprint": input_fp,
        "model_fingerprint": model_fp,
        "parameter_fingerprint": parameter_fp,
        "calibration_fingerprint": calibration_fp,
        "run_fingerprint": run_fp,
        "wall_clock_excluded_from_deterministic_fingerprint": True,
        "raw_factual_inputs_persisted": False,
    }


def bind_deterministic_output(binding: Mapping[str, Any], output: Any) -> dict[str, Any]:
    run_fp = _text(binding.get("run_fingerprint"), "run_fingerprint")
    return {
        "run_fingerprint": run_fp,
        "output_fingerprint": fingerprint({"run_fingerprint": run_fp, "deterministic_output": output}),
        "deterministic_output": deepcopy(output),
    }


def freeze_prediction(
    *,
    model_binding: Mapping[str, Any],
    deadline_time: Any,
    forecast_generated_at: Any,
    frozen_at: Any,
    forecast_rows: Sequence[Mapping[str, Any]],
    decision_snapshot: Mapping[str, Any] | None = None,
    existing_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    deadline, generated, frozen = _dt(deadline_time, "deadline_time"), _dt(forecast_generated_at, "forecast_generated_at"), _dt(frozen_at, "frozen_at")
    if generated > deadline:
        raise ModelEvidenceError("forecast must be generated on or before deadline")
    if existing_record and existing_record.get("frozen_forecast") is not None:
        raise ModelEvidenceError("frozen forecast is immutable and cannot be rewritten")
    decision = deepcopy(dict(decision_snapshot or {}))
    if decision.get("captured_at") is not None and _dt(decision["captured_at"], "decision captured_at") > deadline:
        raise ModelEvidenceError("decision snapshot must be captured on or before deadline")
    frozen_forecast = {"generated_at": _utc(forecast_generated_at, "forecast_generated_at"), "players": [deepcopy(dict(x)) for x in forecast_rows]}
    frozen_decision = decision or None
    evidence_fp = fingerprint({
        "run_fingerprint": model_binding.get("run_fingerprint"),
        "deadline_time": _utc(deadline_time, "deadline_time"),
        "frozen_forecast": frozen_forecast,
        "frozen_decision_snapshot": frozen_decision,
    })
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_kind": "CALIBRATION_DECISION_LEDGER_RECORD",
        "status": FROZEN,
        "planning_gw": int(model_binding.get("planning_gw") or 0),
        "deadline_time": _utc(deadline_time, "deadline_time"),
        "frozen_at": _utc(frozen_at, "frozen_at"),
        "freeze_transition": "PREDEADLINE_FREEZE" if frozen <= deadline else "PROMOTED_LAST_PREDEADLINE_SNAPSHOT",
        "model_binding": deepcopy(dict(model_binding)),
        "frozen_forecast": frozen_forecast,
        "frozen_decision_snapshot": frozen_decision,
        "frozen_evidence_fingerprint": evidence_fp,
        "anti_hindsight": {
            "forecast_generated_predeadline": True,
            "decision_captured_predeadline": decision.get("captured_at") is None or _dt(decision["captured_at"], "decision captured_at") <= deadline,
            "retroactive_forecast_rewrite_forbidden": True,
            "settlement_requires_finished_event": True,
        },
    }


def _avg(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _avg_ranks(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks, i = [0.0] * len(values), 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = rank
        i = j
    return ranks


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    rx, ry = _avg_ranks(xs), _avg_ranks(ys)
    mx, my = _avg(rx), _avg(ry)
    vx, vy = sum((x - mx) ** 2 for x in rx), sum((y - my) ** 2 for y in ry)
    if vx <= 0 or vy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(rx, ry)) / math.sqrt(vx * vy)


def _pairs(forecasts: Sequence[Mapping[str, Any]], actuals: Sequence[Mapping[str, Any]]):
    amap = {int(x["element"]): x for x in actuals if x.get("element") is not None}
    return [(f, amap[int(f["element"])]) for f in forecasts if f.get("element") is not None and int(f["element"]) in amap]


def _metrics(pairs) -> dict[str, Any]:
    if not pairs:
        return {"status": "NO_SETTLED_SAMPLE", "sample_size": 0}
    pp, ap = [_num(f["xpts"], "xpts") for f, _ in pairs], [_num(a["points"], "points") for _, a in pairs]
    pm, am = [_num(f["xmins"], "xmins") for f, _ in pairs], [_num(a["minutes"], "minutes") for _, a in pairs]
    starter = [(f, a) for f, a in pairs if f.get("start_probability") is not None and a.get("started") is not None]
    dnp = [(f, a) for f, a in pairs if f.get("dnp_probability") is not None and a.get("dnp") is not None]
    cs = [(f, a) for f, a in pairs if str(f.get("position") or "") in {"GK", "DEF", "MID"} and f.get("clean_sheet_probability") is not None and a.get("clean_sheet") is not None]
    return {
        "status": SETTLED,
        "sample_size": len(pairs),
        "xpts_mae": _r(_avg([abs(a - p) for p, a in zip(pp, ap)])),
        "xpts_rmse": _r(math.sqrt(_avg([(a - p) ** 2 for p, a in zip(pp, ap)]))),
        "xmins_mae": _r(_avg([abs(a - p) for p, a in zip(pm, am)])),
        "starter_brier": _r(_avg([(_prob(f["start_probability"], "start_probability") - _num(a["started"], "started")) ** 2 for f, a in starter])),
        "starter_sample_size": len(starter),
        "dnp_brier": _r(_avg([(_prob(f["dnp_probability"], "dnp_probability") - _num(a["dnp"], "dnp")) ** 2 for f, a in dnp])),
        "dnp_sample_size": len(dnp),
        "clean_sheet_brier": _r(_avg([(_prob(f["clean_sheet_probability"], "clean_sheet_probability") - _num(a["clean_sheet"], "clean_sheet")) ** 2 for f, a in cs])),
        "clean_sheet_sample_size": len(cs),
        "spearman_rank": _r(_spearman(pp, ap)),
    }


def prediction_calibration_metrics(forecasts: Sequence[Mapping[str, Any]], actuals: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pairs = _pairs(forecasts, actuals)
    confidence = {str(f.get("projection_confidence") or "UNSPECIFIED") for f, _ in pairs}
    by_conf = {label: _metrics([(f, a) for f, a in pairs if str(f.get("projection_confidence") or "UNSPECIFIED") == label]) for label in sorted(confidence)}
    by_sample = {}
    for label, low, high in SAMPLE_BUCKETS:
        subset = [(f, a) for f, a in pairs if f.get("evidence_sample_size") is not None and int(f["evidence_sample_size"]) >= low and (high is None or int(f["evidence_sample_size"]) <= high)]
        by_sample[label] = {**_metrics(subset), "bucket_min": low, "bucket_max": high}
    return {
        "overall": _metrics(pairs),
        "by_confidence_bucket": by_conf,
        "by_sample_size_bucket": by_sample,
        "governance": {"prediction_error_separate_from_decision_error": True, "bucket_metrics_are_diagnostic_only": True, "one_result_rule_creation_forbidden": True},
    }


def _metric(value: float | None, status: str = SETTLED, **extra: Any) -> dict[str, Any]:
    return {"status": status, "sample_size": 1 if value is not None else 0, "value": _r(value), **extra}


def decision_calibration_metrics(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    e = dict(evidence or {})
    names = ("transfer_counterfactual_regret", "hold_vs_act_realized_regret", "xi_regret", "bench_order_regret", "captain_regret", "vice_captain_consequence", "cameo_block_autosub_regret", "one_gw_rental_realized_pnl")
    m = {name: _metric(None, "NO_GENUINE_PREDEADLINE_SAMPLE") for name in names}
    if e.get("chosen_transfer_net") is not None and e.get("best_transfer_or_hold_net") is not None:
        m["transfer_counterfactual_regret"] = _metric(max(0.0, _num(e["best_transfer_or_hold_net"], "best_transfer_or_hold_net") - _num(e["chosen_transfer_net"], "chosen_transfer_net")))
    if e.get("hold_realized_net") is not None and e.get("act_realized_net") is not None and e.get("chosen_action"):
        hold, act, chosen = _num(e["hold_realized_net"], "hold_realized_net"), _num(e["act_realized_net"], "act_realized_net"), str(e["chosen_action"]).upper()
        if chosen not in {"HOLD", "ACT"}:
            raise ModelEvidenceError("chosen_action must be HOLD or ACT")
        m["hold_vs_act_realized_regret"] = _metric(max(0.0, max(hold, act) - (hold if chosen == "HOLD" else act)), chosen_action=chosen)
    for key, a, b in (
        ("xi_regret", "selected_xi_points", "best_legal_xi_points"),
        ("bench_order_regret", "realized_bench_order_autosub_points", "best_legal_bench_autosub_points"),
        ("captain_regret", "chosen_captain_points", "best_captain_candidate_points"),
        ("cameo_block_autosub_regret", "cameo_points", "blocked_legal_autosub_points"),
    ):
        if e.get(a) is not None and e.get(b) is not None:
            m[key] = _metric(max(0.0, _num(e[b], b) - _num(e[a], a)))
    if e.get("vice_takeover_points") is not None and e.get("vice_counterfactual_points") is not None:
        m["vice_captain_consequence"] = _metric(_num(e["vice_takeover_points"], "vice_takeover_points") - _num(e["vice_counterfactual_points"], "vice_counterfactual_points"), consequence_semantics="SIGNED_POINTS_DELTA")
    rental_fields = ("rental_player_points", "hold_player_points", "rental_exact_hit_cost", "rental_exact_exit_cost")
    if all(e.get(k) is not None for k in rental_fields):
        m["one_gw_rental_realized_pnl"] = _metric(_num(e["rental_player_points"], rental_fields[0]) - _num(e["hold_player_points"], rental_fields[1]) - _num(e["rental_exact_hit_cost"], rental_fields[2]) - _num(e["rental_exact_exit_cost"], rental_fields[3]))
    return {"metrics": m, "governance": {"prediction_error_separate_from_decision_error": True, "exact_fpl_costs_required_for_cost_adjusted_metrics": True, "legacy_fixed_change_penalty_forbidden": True, "one_result_rule_creation_forbidden": True}}


def settle_frozen_record(record: Mapping[str, Any], *, actual_rows: Sequence[Mapping[str, Any]], decision_outcome_evidence: Mapping[str, Any] | None, event_finished: bool, settled_at: Any) -> dict[str, Any]:
    if record.get("status") != FROZEN:
        raise ModelEvidenceError("only frozen records may be settled")
    if not event_finished:
        raise ModelEvidenceError("settlement requires a finished event")
    if _dt(settled_at, "settled_at") < _dt(record.get("deadline_time"), "deadline_time"):
        raise ModelEvidenceError("settled_at cannot precede deadline_time")
    expected = fingerprint({"run_fingerprint": (record.get("model_binding") or {}).get("run_fingerprint"), "deadline_time": record.get("deadline_time"), "frozen_forecast": record.get("frozen_forecast"), "frozen_decision_snapshot": record.get("frozen_decision_snapshot")})
    if expected != record.get("frozen_evidence_fingerprint"):
        raise ModelEvidenceError("frozen evidence fingerprint mismatch; possible hindsight mutation")
    out = deepcopy(dict(record))
    prediction = prediction_calibration_metrics((record.get("frozen_forecast") or {}).get("players") or [], actual_rows)
    out.update({
        "status": SETTLED,
        "settled_at": _utc(settled_at, "settled_at"),
        "settled_sample_size": int(prediction["overall"].get("sample_size") or 0),
        "actual_outcome_fingerprint": fingerprint([dict(x) for x in actual_rows]),
        "prediction_calibration": prediction,
        "decision_calibration": decision_calibration_metrics(decision_outcome_evidence),
        "anti_hindsight": {**dict(record.get("anti_hindsight") or {}), "frozen_evidence_verified_before_settlement": True, "actuals_not_embedded_in_frozen_fingerprint": True},
    })
    return out


def new_calibration_ledger() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "evidence_kind": "CALIBRATION_DECISION_LEDGER", "records": {}, "governance": {"authority": False, "v6_factual_data_duplicated": False, "prediction_freeze_immutable": True, "settlement_finished_event_only": True}}


def put_frozen_record(ledger: Mapping[str, Any], *, record_id: str, frozen_record: Mapping[str, Any]) -> dict[str, Any]:
    if frozen_record.get("status") != FROZEN:
        raise ModelEvidenceError("only frozen records may be inserted")
    out, key = deepcopy(dict(ledger)), _text(record_id, "record_id")
    if key in out.setdefault("records", {}):
        raise ModelEvidenceError("ledger record_id is immutable once inserted")
    out["records"][key] = deepcopy(dict(frozen_record))
    return out


def replace_with_settled_record(ledger: Mapping[str, Any], *, record_id: str, settled_record: Mapping[str, Any]) -> dict[str, Any]:
    if settled_record.get("status") != SETTLED:
        raise ModelEvidenceError("replacement record must be SETTLED")
    out, key = deepcopy(dict(ledger)), _text(record_id, "record_id")
    current = out.setdefault("records", {}).get(key)
    if not current:
        raise ModelEvidenceError("record_id must already exist")
    if current.get("frozen_evidence_fingerprint") != settled_record.get("frozen_evidence_fingerprint"):
        raise ModelEvidenceError("settlement must preserve frozen evidence fingerprint")
    out["records"][key] = deepcopy(dict(settled_record))
    return out


def aggregate_settled_ledgers(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    settled = [r for r in records if r.get("status") == SETTLED]
    prediction_n = sum(int(((r.get("prediction_calibration") or {}).get("overall") or {}).get("sample_size") or 0) for r in settled)
    names = ("transfer_counterfactual_regret", "hold_vs_act_realized_regret", "xi_regret", "bench_order_regret", "captain_regret", "vice_captain_consequence", "cameo_block_autosub_regret", "one_gw_rental_realized_pnl")
    summary = {}
    for name in names:
        values = [float(metric["value"]) for r in settled if (metric := ((((r.get("decision_calibration") or {}).get("metrics") or {}).get(name)) or {})).get("status") == SETTLED and metric.get("value") is not None]
        summary[name] = {"status": SETTLED if values else "NO_SETTLED_SAMPLE", "sample_size": len(values), "mean": _r(_avg(values))}
    return {"schema_version": SCHEMA_VERSION, "settled_record_count": len(settled), "prediction_sample_size": prediction_n, "decision_metrics": summary, "calibration_confidence": "LOW" if prediction_n < 50 else "MEDIUM" if prediction_n < 150 else "HIGH", "governance": {"updates_require_settled_samples": True, "explicit_sample_size_required": True, "automatic_methodology_weight_mutation": False}}


OPERATIONAL_BINDING_FIELDS = (
    "input_snapshot_id",
    "factual_snapshot_timestamps",
    "factual_artifact_fingerprints",
    "model_version",
    "feature_version",
    "parameter_version",
    "calibration_version",
    "calibration_cutoff",
    "planning_gw",
    "canonical_v12_revision",
    "input_fingerprint",
    "model_fingerprint",
    "parameter_fingerprint",
    "calibration_fingerprint",
    "run_fingerprint",
    "generated_at",
)
OPERATIONAL_FINGERPRINT_FIELDS = (
    "input_fingerprint",
    "model_fingerprint",
    "parameter_fingerprint",
    "calibration_fingerprint",
    "run_fingerprint",
)


def _is_sha256_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def validate_operational_model_evidence(
    binding: Mapping[str, Any] | None,
    *,
    serious_decision: bool = True,
    reproducibility_claimed: bool = False,
    repository_python_executed: bool = False,
    repository_python_execution_proof: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate actual-runtime model evidence without claiming repository execution.

    This is a deterministic contract helper. Calling it in tests/CI is not proof
    that the recurring ChatGPT Automation executed this Python module.
    """
    if not binding:
        if reproducibility_claimed:
            raise ModelEvidenceError("reproducibility cannot be claimed without MODEL_EVIDENCE_BINDING")
        return {
            "status": "DEGRADED" if serious_decision else "NOT_REQUIRED",
            "serious_decision": bool(serious_decision),
            "binding_present": False,
            "reproducible": False,
            "report_can_continue": True,
            "authority": False,
            "evidence_only": True,
            "repository_python_executed": False,
            "missing_fields": list(OPERATIONAL_BINDING_FIELDS),
            "uncomputed_fingerprints": list(OPERATIONAL_FINGERPRINT_FIELDS),
        }

    row = dict(binding)
    if row.get("authority") is not False:
        raise ModelEvidenceError("MODEL_EVIDENCE_BINDING must be authority=false")
    if row.get("evidence_only") is not True:
        raise ModelEvidenceError("MODEL_EVIDENCE_BINDING must be evidence_only=true")
    if row.get("raw_v6_payload") is not None or row.get("raw_factual_payload") is not None:
        raise ModelEvidenceError("complete raw V6/factual payload must not be persisted in model evidence")
    if row.get("raw_factual_inputs_persisted") not in (None, False):
        raise ModelEvidenceError("raw_factual_inputs_persisted must be false")

    missing = [field for field in OPERATIONAL_BINDING_FIELDS if field not in row]
    uncomputed = [
        field for field in OPERATIONAL_FINGERPRINT_FIELDS
        if field not in row or not _is_sha256_text(row.get(field))
    ]
    if reproducibility_claimed and (missing or uncomputed):
        raise ModelEvidenceError("reproducibility claim requires complete actually-computed model evidence fingerprints")

    if repository_python_executed:
        proof = dict(repository_python_execution_proof or {})
        if not (
            proof.get("occurrence_bound") is True
            and str(proof.get("module") or "") == "src/engines/v12_model_evidence.py"
            and str(proof.get("execution_id") or "").strip()
        ):
            raise ModelEvidenceError("repository Python execution claim requires exact occurrence-bound execution proof")

    reproducible = not missing and not uncomputed
    return {
        "status": "PASS" if reproducible else "DEGRADED",
        "serious_decision": bool(serious_decision),
        "binding_present": True,
        "reproducible": reproducible,
        "report_can_continue": True,
        "authority": False,
        "evidence_only": True,
        "repository_python_executed": bool(repository_python_executed),
        "missing_fields": missing,
        "uncomputed_fingerprints": uncomputed,
    }


def new_durable_state_evidence_surface() -> dict[str, Any]:
    return {
        "schema": "FPL_MASTER_V12_MODEL_EVIDENCE_STATE_V1",
        "authority": False,
        "evidence_only": True,
        "raw_v6_payload_persisted": False,
        "lifecycle": [FROZEN, SETTLED],
        "records": {},
        "automatic_methodology_weight_mutation": False,
        "report_delivery_policy": "OPTIONAL_MODEL_EVIDENCE_DEGRADATION_NEVER_SUPPRESSES_DUE_REPORT",
    }


def persist_frozen_to_state(
    evidence_state: Mapping[str, Any],
    *,
    record_id: str,
    frozen_record: Mapping[str, Any],
) -> dict[str, Any]:
    out = deepcopy(dict(evidence_state))
    if out.get("authority") is not False or out.get("evidence_only") is not True:
        raise ModelEvidenceError("durable model evidence surface must remain non-authoritative evidence only")
    if out.get("raw_v6_payload_persisted") is not False:
        raise ModelEvidenceError("durable model evidence surface may not persist raw V6 payload")
    key = _text(record_id, "record_id")
    records = out.setdefault("records", {})
    if key in records:
        raise ModelEvidenceError("same frozen record cannot be silently replaced")
    if frozen_record.get("status") != FROZEN:
        raise ModelEvidenceError("durable evidence accepts only genuinely frozen records")
    records[key] = deepcopy(dict(frozen_record))
    return out


def settle_durable_state_record(
    evidence_state: Mapping[str, Any],
    *,
    record_id: str,
    actual_rows: Sequence[Mapping[str, Any]],
    decision_outcome_evidence: Mapping[str, Any] | None,
    event_finished: bool,
    settled_at: Any,
) -> dict[str, Any]:
    out = deepcopy(dict(evidence_state))
    key = _text(record_id, "record_id")
    current = out.setdefault("records", {}).get(key)
    if current is None:
        raise ModelEvidenceError("settlement cannot manufacture an old forecast; frozen record is required")
    if current.get("status") != FROZEN:
        raise ModelEvidenceError("only FROZEN_AWAITING_SETTLEMENT record may transition to SETTLED")
    settled = settle_frozen_record(
        current,
        actual_rows=actual_rows,
        decision_outcome_evidence=decision_outcome_evidence,
        event_finished=event_finished,
        settled_at=settled_at,
    )
    out["records"][key] = settled
    return out
