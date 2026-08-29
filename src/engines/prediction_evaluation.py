from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from itertools import combinations
from typing import Any

from src.engines.official_snapshot_primitives import endpoint_health, load_snapshot, snapshot_event_live_for_gw
from src.models.calibration import brier, mae, spearman_rank
from src.sources.official_fpl import get_json
from src.utils import DATA, ROOT, atomic_json, parse_dt, read_json, utcnow

CONFIG_PATH = ROOT / "config" / "intelligence" / "prediction_evaluation.json"
LEDGER_PATH = DATA / "prediction_ledger.json"
DECISION_SNAPSHOT_PATH = DATA / "decision_validation_snapshots.json"
OUT_PATH = DATA / "prediction_accuracy.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _forecast_rows(projections: dict[str, Any], gw: int) -> list[dict[str, Any]]:
    rows = []
    for player in projections.get("players") or []:
        event = next((x for x in player.get("xpts_by_gw") or [] if int(x.get("gw") or -1) == gw), None)
        if event is None:
            continue
        rows.append({
            "element": int(player["element"]),
            "name": player.get("name"),
            "position": player.get("position"),
            "xpts": round(_f(event.get("mean")), 4),
            "xpts_std": round(_f(event.get("std")), 4),
            "xmins": round(_f((player.get("xmins") or {}).get("expected_minutes")), 2),
            "start_probability": round(_f((player.get("xmins") or {}).get("start_probability")), 4),
            "clean_sheet_probability": round(_f(event.get("clean_sheet_probability")), 4),
            "projection_confidence": player.get("projection_confidence"),
        })
    return rows


def _actual_rows(event_live: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for player in event_live.get("elements") or []:
        stats = player.get("stats") or {}
        starts = stats.get("starts")
        rows.append({
            "element": int(player.get("id") or -1),
            "points": _f(stats.get("total_points")),
            "minutes": _f(stats.get("minutes")),
            "started": int(starts > 0) if starts is not None else None,
            "clean_sheet": int(_f(stats.get("clean_sheets")) > 0),
        })
    return rows


def _metrics(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    if not pairs:
        return {"sample_size": 0, "status": "NO_SETTLED_SAMPLE"}
    pred_points = [_f(x["forecast"].get("xpts")) for x in pairs]
    actual_points = [_f(x["actual"].get("points")) for x in pairs]
    pred_minutes = [_f(x["forecast"].get("xmins")) for x in pairs]
    actual_minutes = [_f(x["actual"].get("minutes")) for x in pairs]
    sq = [(a - p) ** 2 for a, p in zip(actual_points, pred_points)]
    starter_pairs = [x for x in pairs if x["actual"].get("started") is not None]
    cs_pairs = [x for x in pairs if x["forecast"].get("position") in {"GK", "DEF", "MID"}]
    rank = spearman_rank(pred_points, actual_points) if len(pairs) >= 2 else None
    return {
        "sample_size": len(pairs),
        "points_mae": round(mae(pred_points, actual_points), 4),
        "points_rmse": round(math.sqrt(sum(sq) / len(sq)), 4),
        "xmins_mae": round(mae(pred_minutes, actual_minutes), 4),
        "starter_brier": round(brier(
            [_f(x["forecast"].get("start_probability")) for x in starter_pairs],
            [_f(x["actual"].get("started")) for x in starter_pairs],
        ), 4) if starter_pairs else None,
        "starter_sample_size": len(starter_pairs),
        "clean_sheet_brier": round(brier(
            [_f(x["forecast"].get("clean_sheet_probability")) for x in cs_pairs],
            [_f(x["actual"].get("clean_sheet")) for x in cs_pairs],
        ), 4) if cs_pairs else None,
        "clean_sheet_sample_size": len(cs_pairs),
        "spearman": round(rank, 4) if rank is not None else None,
        "status": "SETTLED",
    }


def _confidence(sample_size: int) -> str:
    thresholds = load_config().get("confidence_sample_thresholds") or {}
    if sample_size <= int(thresholds.get("low_max") or 49):
        return "LOW"
    if sample_size <= int(thresholds.get("medium_max") or 149):
        return "MEDIUM"
    return "HIGH"


def _legal_xi(rows: tuple[dict[str, Any], ...]) -> bool:
    counts: dict[str, int] = {}
    for row in rows:
        pos = str(row.get("position") or "")
        counts[pos] = counts.get(pos, 0) + 1
    return counts.get("GK", 0) == 1 and counts.get("DEF", 0) >= 3 and counts.get("MID", 0) >= 2 and counts.get("FWD", 0) >= 1


def _decision_validation(snapshot: dict[str, Any] | None, actual: list[dict[str, Any]]) -> dict[str, Any]:
    missing = {
        "captain_regret": {"status": "NO_GENUINE_PREDEADLINE_SAMPLE", "sample_size": 0, "value": None},
        "xi_regret": {"status": "NO_GENUINE_PREDEADLINE_SAMPLE", "sample_size": 0, "value": None},
        "transfer_comparator_realized_net_gain": {"status": "NO_GENUINE_PREDEADLINE_SAMPLE", "sample_size": 0, "value": None},
    }
    if not snapshot:
        return missing
    amap = {int(x.get("element") or -1): x for x in actual}
    lineup = snapshot.get("lineup") or {}

    chosen_cap = int(lineup.get("captain") or -1)
    cap_pool = [int(x) for x in lineup.get("captain_candidates") or [] if int(x) in amap]
    if chosen_cap in amap and cap_pool:
        chosen_points = _f(amap[chosen_cap].get("points"))
        best_points = max(_f(amap[x].get("points")) for x in cap_pool)
        missing["captain_regret"] = {
            "status": "SETTLED",
            "sample_size": 1,
            "value": round(max(0.0, best_points - chosen_points), 4),
            "chosen_actual_points": chosen_points,
            "best_candidate_actual_points": best_points,
            "candidate_count": len(cap_pool),
        }

    selected_ids = [int(x.get("element") or -1) for x in lineup.get("starting_xi") or []]
    owned = [x for x in lineup.get("owned_squad") or [] if int(x.get("element") or -1) in amap]
    if len(selected_ids) == 11 and len(owned) >= 11 and all(x in amap for x in selected_ids):
        selected_points = sum(_f(amap[x].get("points")) for x in selected_ids)
        best_points = None
        for combo in combinations(owned, 11):
            if not _legal_xi(combo):
                continue
            points = sum(_f(amap[int(row["element"])].get("points")) for row in combo)
            if best_points is None or points > best_points:
                best_points = points
        if best_points is not None:
            missing["xi_regret"] = {
                "status": "SETTLED",
                "sample_size": 1,
                "value": round(max(0.0, best_points - selected_points), 4),
                "selected_xi_actual_points": round(selected_points, 4),
                "best_legal_xi_actual_points": round(best_points, 4),
            }

    comparison_rows = []
    exact_net = []
    for row in (snapshot.get("comparator") or {}).get("comparisons") or []:
        out_id = int(row.get("player_out") or -1)
        in_id = int(row.get("player_in") or -1)
        if out_id not in amap or in_id not in amap:
            continue
        gross = _f(amap[in_id].get("points")) - _f(amap[out_id].get("points"))
        hit_cost = row.get("exact_hit_cost")
        net = None if hit_cost is None else gross - _f(hit_cost)
        comparison_rows.append({
            "player_out": out_id,
            "player_in": in_id,
            "state": row.get("state"),
            "realized_gross_points_delta_1gw": round(gross, 4),
            "exact_hit_cost": hit_cost,
            "realized_net_gain_1gw": round(net, 4) if net is not None else None,
            "net_gain_state": "AVAILABLE" if net is not None else "UNAVAILABLE_EXACT_HIT_COST",
        })
        if net is not None:
            exact_net.append(net)
    if comparison_rows:
        missing["transfer_comparator_realized_net_gain"] = {
            "status": "SETTLED" if exact_net else "PARTIAL_GROSS_ONLY",
            "sample_size": len(exact_net),
            "value": round(sum(exact_net) / len(exact_net), 4) if exact_net else None,
            "gross_pair_count": len(comparison_rows),
            "comparisons": comparison_rows,
            "note": "Net gain is unavailable when exact FPL hit cost was not captured pre-deadline; optimizer change penalties are never substituted.",
        }
    return missing


def _aggregate_decision_metrics(records: dict[str, Any]) -> dict[str, Any]:
    names = ("captain_regret", "xi_regret", "transfer_comparator_realized_net_gain")
    out: dict[str, Any] = {}
    for name in names:
        rows = []
        partial = False
        for record in records.values():
            if record.get("status") != "SETTLED":
                continue
            metric = (record.get("decision_validation") or {}).get(name) or {}
            if metric.get("status") == "SETTLED" and metric.get("value") is not None:
                rows.append(_f(metric.get("value")))
            elif metric.get("status") == "PARTIAL_GROSS_ONLY":
                partial = True
        if rows:
            out[name] = {"status": "SETTLED", "sample_size": len(rows), "mean": round(sum(rows) / len(rows), 4)}
        elif partial:
            out[name] = {"status": "PARTIAL_GROSS_ONLY", "sample_size": 0, "mean": None}
        else:
            out[name] = {"status": "NO_GENUINE_PREDEADLINE_SAMPLE", "sample_size": 0, "mean": None}
    return out


def _settle_record(record: dict[str, Any], event_live: dict[str, Any], decision_snapshot: dict[str, Any] | None) -> None:
    actual = _actual_rows(event_live)
    amap = {int(x["element"]): x for x in actual}
    frozen = (record.get("frozen_forecast") or {}).get("players") or []
    pairs = [{"forecast": f, "actual": amap[int(f["element"])]} for f in frozen if int(f["element"]) in amap]
    record["actual"] = {"settled_at": _now(), "players": actual}
    record["metrics"] = _metrics(pairs)
    if decision_snapshot:
        record["frozen_decision_snapshot"] = decision_snapshot
    record["decision_validation"] = _decision_validation(decision_snapshot, actual)
    record["status"] = "SETTLED"


def _valid_predeadline_decision_snapshot(snapshot: dict[str, Any] | None, deadline_value: Any) -> dict[str, Any] | None:
    if not snapshot:
        return None
    captured = parse_dt(snapshot.get("captured_at"))
    deadline = parse_dt(deadline_value or snapshot.get("deadline_time"))
    if captured is None or deadline is None or captured > deadline:
        return None
    return snapshot


def _promote_overdue_predeadline_forecasts(records: dict[str, Any], now: datetime) -> dict[str, int]:
    """Freeze every overdue ledger record from its last genuine pre-deadline snapshot.

    The promotion may happen after the deadline, but the forecast payload itself must have
    been generated on or before that record's deadline. This closes the state-transition
    gap when planning advances to the next GW before the previous record is frozen.
    """
    promoted = 0
    missed = 0
    for record in records.values():
        if record.get("status") == "SETTLED" or record.get("frozen_forecast"):
            continue
        record_deadline = parse_dt(record.get("deadline_time"))
        if record_deadline is None or now < record_deadline:
            continue
        candidate = record.get("latest_pre_deadline_forecast")
        candidate_time = parse_dt((candidate or {}).get("generated_at"))
        if candidate and candidate_time and candidate_time <= record_deadline:
            record["frozen_forecast"] = candidate
            record["frozen_at"] = now.astimezone(timezone.utc).isoformat()
            record["freeze_transition"] = "PROMOTED_LAST_PREDEADLINE_SNAPSHOT"
            record["status"] = "FROZEN_AWAITING_SETTLEMENT"
            promoted += 1
        else:
            record["status"] = "MISSED_PRE_DEADLINE_FREEZE"
            missed += 1
    return {"promoted": promoted, "missed": missed}


def run() -> dict[str, Any]:
    cfg = load_config()
    latest = read_json(DATA / "latest.json", {})
    projections = read_json(DATA / "projections.json", {})
    ledger = read_json(LEDGER_PATH, {"schema_version": 1, "records": {}})
    decision_snapshots = read_json(DECISION_SNAPSHOT_PATH, {"records": {}}).get("records") or {}
    snapshot = load_snapshot()
    records = ledger.setdefault("records", {})
    phase = latest.get("phase") or snapshot.get("phase") or {}
    planning_gw = int(phase.get("planning_gw") or projections.get("planning_gw") or 0)
    deadline = parse_dt(phase.get("deadline_time"))
    now = utcnow()

    if planning_gw > 0:
        record = records.setdefault(str(planning_gw), {"gw": planning_gw, "status": "COLLECTING"})
        forecast = {"generated_at": projections.get("generated_at") or _now(), "players": _forecast_rows(projections, planning_gw)}
        if deadline and now < deadline:
            record["deadline_time"] = phase.get("deadline_time")
            record["latest_pre_deadline_forecast"] = forecast
            record["status"] = "COLLECTING"

    freeze_recovery = _promote_overdue_predeadline_forecasts(records, now)

    bootstrap = snapshot.get("bootstrap") or {}
    bh = endpoint_health(snapshot, "bootstrap")
    events = {int(e["id"]): e for e in bootstrap.get("events", [])}
    settled_from_snapshot = 0
    settled_from_network = 0
    for key, record in records.items():
        gw = int(record.get("gw") or key)
        if record.get("status") == "SETTLED" or not record.get("frozen_forecast"):
            continue
        event = events.get(gw) or {}
        if cfg.get("settle_only_finished_events", True) and not event.get("finished"):
            continue
        live, health = snapshot_event_live_for_gw(snapshot, gw)
        if live is not None:
            settled_from_snapshot += 1
            health = {**health, "reuse": "CORE_SNAPSHOT"}
        else:
            live, health = get_json(f"event/{gw}/live/")
            settled_from_network += 1
        if live:
            decision_snapshot = _valid_predeadline_decision_snapshot(decision_snapshots.get(str(gw)), record.get("deadline_time"))
            _settle_record(record, live, decision_snapshot)
            record["settlement_source_health"] = health.get("status")
            record["settlement_source"] = "CORE_SNAPSHOT" if health.get("reuse") else "HISTORICAL_EVENT_LIVE"

    all_pairs = []
    by_position: dict[str, list[dict[str, Any]]] = {}
    by_gw: dict[str, dict[str, Any]] = {}
    for key, record in records.items():
        if record.get("status") != "SETTLED":
            continue
        actual = {int(x["element"]): x for x in (record.get("actual") or {}).get("players") or []}
        frozen = (record.get("frozen_forecast") or {}).get("players") or []
        pairs = [{"forecast": f, "actual": actual[int(f["element"])]} for f in frozen if int(f["element"]) in actual]
        all_pairs.extend(pairs)
        by_gw[str(record.get("gw") or key)] = {
            **_metrics(pairs),
            "decision_validation": record.get("decision_validation") or _decision_validation(None, []),
        }
        for pair in pairs:
            by_position.setdefault(str(pair["forecast"].get("position")), []).append(pair)

    overall = _metrics(all_pairs)
    sample_size = int(overall.get("sample_size") or 0)
    decision_metrics = _aggregate_decision_metrics(records)
    accuracy = {
        "generated_at": _now(),
        "model": cfg.get("model_id"),
        "freeze_policy": cfg.get("freeze_policy"),
        "overall": overall,
        "confidence": _confidence(sample_size),
        "by_position": {k: _metrics(v) for k, v in sorted(by_position.items())},
        "by_gw": by_gw,
        "decision_metrics": decision_metrics,
        "validation_dimensions": {
            "formula_correctness": {"status": "SEPARATE_GOVERNANCE_TRACK", "counts_as_predictive_accuracy": False},
            "predictive_accuracy": {"status": overall.get("status"), "sample_size": sample_size},
        },
        "settled_gameweeks": sorted(int(k) for k, v in records.items() if v.get("status") == "SETTLED"),
        "collecting_gameweeks": sorted(int(k) for k, v in records.items() if v.get("status") != "SETTLED"),
        "dynamic_weight_eligible": sample_size >= int(cfg.get("minimum_sample_for_dynamic_weight") or 50),
        "governance": {
            "accuracy_claim_requires_settled_sample": True,
            "pre_deadline_forecast_is_frozen_before_scoring": True,
            "overdue_freeze_may_only_promote_predeadline_payload": True,
            "pre_deadline_decision_snapshot_required_for_decision_regret": True,
            "post_deadline_information_cannot_rewrite_frozen_forecast": True,
            "post_deadline_information_cannot_create_retroactive_decision_snapshot": True,
            "reconcile_only_finished_events": True,
            "formula_correctness_is_separate_from_predictive_accuracy": True,
            "optimizer_change_penalty_is_never_used_as_fpl_hit_cost": True,
            "core_snapshot_consumed_before_historical_network": True,
            "early_season_confidence_is_conservative": True,
        },
        "source_health": {
            "bootstrap": bh.get("status"),
            "bootstrap_source": "CORE_SNAPSHOT",
            "event_live_snapshot_reused": settled_from_snapshot,
            "historical_event_live_fetched": settled_from_network,
            "freeze_recovery": freeze_recovery,
        },
    }
    ledger["updated_at"] = _now()
    ledger["model"] = cfg.get("model_id")
    atomic_json(LEDGER_PATH, ledger)
    atomic_json(OUT_PATH, accuracy)

    latest.setdefault("files", {}).update({"prediction_ledger": "data/prediction_ledger.json", "prediction_accuracy": "data/prediction_accuracy.json"})
    latest["prediction_evaluation"] = {
        "status": overall.get("status"),
        "sample_size": sample_size,
        "confidence": accuracy["confidence"],
        "settled_gameweeks": accuracy["settled_gameweeks"],
        "dynamic_weight_eligible": accuracy["dynamic_weight_eligible"],
        "decision_metrics": decision_metrics,
        "freeze_recovery": freeze_recovery,
        "core_snapshot_consumed": True,
    }
    atomic_json(DATA / "latest.json", latest)
    return accuracy


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
