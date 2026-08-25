from __future__ import annotations

import json
import statistics
from collections import Counter
from src.utils import DATA, atomic_json, read_json

OUTFILE = DATA / "recommendation_sanity_v4.json"


def _f(v, default=0.0):
    try:
        return float(v if v is not None else default)
    except Exception:
        return float(default)


def _avg(values, default=0.0):
    vals = [float(x) for x in values if x is not None]
    return sum(vals) / len(vals) if vals else float(default)


def _player_evidence(element: int, pmap: dict[int, dict], umap: dict[int, dict]) -> dict:
    pred = pmap[element]
    uni = umap[element]
    fixtures = (pred.get("fixtures") or [])[:5]
    starts, dnps = [], []
    for fx in fixtures:
        xm = fx.get("xmins") or {}
        starts.append(_f(xm.get("start_probability"), 0.5))
        dnps.append(_f(xm.get("dnp_probability"), 0.1))
    start = _avg(starts, 0.5)
    dnp = _avg(dnps, 0.1)
    unc = max(0.0, _f(pred.get("uncertainty")))
    priors = pred.get("priors") or {}
    role = max(0.0, _f(priors.get("role_prior")))

    horizon_rates = [
        _f(pred.get("xpts_3")) / 3.0,
        _f(pred.get("xpts_5")) / 5.0,
        _f(pred.get("xpts_10")) / 10.0,
        _f(pred.get("xpts_15")) / 15.0,
    ]
    mean_rate = _avg(horizon_rates, 0.0)
    cv = statistics.pstdev(horizon_rates) / mean_rate if mean_rate > 0 else 1.0
    horizon_stability = max(0.0, 1.0 - min(1.0, cv / 0.18))

    fx0 = fixtures[0] if fixtures else {}
    rates = fx0.get("rates") or {}
    prior_xg = max(0.04, _f(priors.get("xg90_prior"), 0.04))
    prior_xa = max(0.04, _f(priors.get("xa90_prior"), 0.04))
    raw_xg = max(0.0, _f(rates.get("raw_xg90")))
    raw_xa = max(0.0, _f(rates.get("raw_xa90")))
    current_weight = max(0.0, min(1.0, _f(rates.get("current_season_weight"))))
    dx = max(0.0, raw_xg / prior_xg - 1.0)
    da = max(0.0, raw_xa / prior_xa - 1.0)
    rate_spike_risk = min(1.0, ((dx + da) / 8.0) * max(0.3, 1.0 - current_weight))

    ownership = max(0.0, _f(uni.get("ownership")))
    net_transfers = _f(uni.get("transfers_in_event")) - _f(uni.get("transfers_out_event"))
    market_support = min(
        1.0,
        0.60 * min(1.0, ownership / 35.0)
        + 0.40 * max(0.0, min(1.0, net_transfers / 150000.0)),
    )

    confidence = (
        0.30 * start
        + 0.10 * (1.0 - dnp)
        + 0.18 * max(0.0, 1.0 - unc / 0.60)
        + 0.14 * min(1.0, role / 0.55)
        + 0.13 * horizon_stability
        + 0.05 * market_support
        + 0.10 * (1.0 - rate_spike_risk)
    )
    confidence = max(0.0, min(1.0, confidence))
    flags = []
    if start < 0.72 or dnp > 0.20:
        flags.append("MINUTES_RISK")
    if unc >= 0.30:
        flags.append("HIGH_UNCERTAINTY")
    if role < 0.12:
        flags.append("LOW_ROLE_PRIOR")
    if rate_spike_risk >= 0.85:
        flags.append("RAW_RATE_SPIKE")
    if current_weight < 0.20:
        flags.append("EARLY_SEASON_SAMPLE")

    return {
        "element": element,
        "name": uni.get("name") or pred.get("name") or str(element),
        "team": uni.get("team"),
        "position": uni.get("position") or pred.get("position"),
        "confidence": round(confidence, 4),
        "grade": "HIGH" if confidence >= 0.78 else "MEDIUM" if confidence >= 0.64 else "LOW",
        "start_probability_5": round(start, 4),
        "dnp_probability_5": round(dnp, 4),
        "uncertainty": round(unc, 4),
        "role_prior": round(role, 4),
        "horizon_stability": round(horizon_stability, 4),
        "rate_spike_risk": round(rate_spike_risk, 4),
        "current_season_weight": round(current_weight, 4),
        "market_support": round(market_support, 4),
        "flags": flags,
    }


def _classify(sanity_gain: float, k: int, material_eligible: bool) -> str:
    material = {1: 2.2, 2: 4.0, 3: 6.0, 4: 8.0}[k]
    optional = {1: 1.1, 2: 2.2, 3: 3.5, 4: 5.0}[k]
    if material_eligible and sanity_gain >= material:
        return "MATERIAL_UPGRADE"
    if sanity_gain >= optional:
        return "OPTIONAL_IMPROVEMENT"
    return "KEEP_15"


def _assess_package(row: dict, pmap: dict[int, dict], umap: dict[int, dict]) -> dict:
    k = int(row.get("replacements") or len(row.get("in", [])))
    ins = [_player_evidence(int(x["element"]), pmap, umap) for x in row.get("in", [])]
    outs = [_player_evidence(int(x["element"]), pmap, umap) for x in row.get("out", [])]
    if not ins:
        return {"classification": "KEEP_15", "sanity_gain_5": 0.0, "evidence_confidence": 0.0}

    team_counts = Counter(x.get("team") for x in ins if x.get("team"))
    cluster_excess = max(team_counts.values(), default=1) - 1
    avg_in = _avg([x["confidence"] for x in ins], 0.0)
    avg_out = _avg([x["confidence"] for x in outs], 0.0)
    min_in = min(x["confidence"] for x in ins)
    severe_spikes = sum(x["rate_spike_risk"] >= 0.85 for x in ins)
    early_season = all(x["current_season_weight"] < 0.20 for x in ins)

    churn_penalty = 0.05 * max(0, k - 1)
    cluster_penalty = 0.08 * max(0, cluster_excess)
    baseline_resistance = 0.04 * max(0.0, avg_out - avg_in)
    confidence = max(0.25, min(0.95, avg_in - churn_penalty - cluster_penalty - baseline_resistance))
    raw_gain = _f(row.get("adjusted_utility_gain_5"))
    sanity_gain = raw_gain * confidence

    if k == 1:
        material_eligible = min_in >= 0.65 and severe_spikes == 0
    elif k == 2:
        material_eligible = min_in >= 0.74 and severe_spikes == 0 and cluster_excess == 0
    else:
        material_eligible = (
            min_in >= 0.76
            and severe_spikes == 0
            and cluster_excess == 0
            and not early_season
        )

    reasons = []
    if severe_spikes:
        reasons.append("RATE_SPIKE_CAP")
    if cluster_excess:
        reasons.append("TEAM_CLUSTER_PENALTY")
    if early_season and k >= 3:
        reasons.append("EARLY_SEASON_MULTI_CHANGE_CAP")
    if min_in < (0.74 if k >= 2 else 0.65):
        reasons.append("WEAK_LINK_EVIDENCE")
    if avg_out > avg_in:
        reasons.append("STRONG_BASELINE_RESISTANCE")

    return {
        "replacements": k,
        "out": row.get("out", []),
        "in": row.get("in", []),
        "raw_classification": row.get("classification"),
        "raw_adjusted_utility_gain_5": round(raw_gain, 3),
        "evidence_confidence": round(confidence, 4),
        "sanity_gain_5": round(sanity_gain, 3),
        "classification": _classify(sanity_gain, k, material_eligible),
        "material_eligible": material_eligible,
        "evidence": {
            "incoming": ins,
            "outgoing": outs,
            "avg_incoming_confidence": round(avg_in, 4),
            "avg_outgoing_confidence": round(avg_out, 4),
            "min_incoming_confidence": round(min_in, 4),
            "severe_rate_spikes": severe_spikes,
            "team_cluster_excess": cluster_excess,
            "early_season": early_season,
            "reasons": reasons,
        },
    }


def sanity_report(predictions: dict, universe: dict, package_audit: dict, latest: dict | None = None) -> dict:
    if predictions.get("point_in_time") is not True:
        raise RuntimeError("V4.6 sanity gate requires point-in-time predictions")
    pmap = {int(p["element"]): p for p in predictions.get("players", []) if p.get("element") is not None}
    umap = {int(p["element"]): p for p in universe.get("players", []) if p.get("element") is not None}
    assessed = {}
    for k, row in (package_audit.get("best_by_replacement_count") or {}).items():
        if row:
            assessed[str(k)] = _assess_package(row, pmap, umap)

    material = [x for x in assessed.values() if x["classification"] == "MATERIAL_UPGRADE"]
    optional = [x for x in assessed.values() if x["classification"] == "OPTIONAL_IMPROVEMENT"]
    if material:
        recommended = max(material, key=lambda x: (x["sanity_gain_5"] - 0.25 * (x["replacements"] - 1), -x["replacements"]))
        verdict = "MATERIAL_UPGRADE"
    elif optional:
        recommended = max(optional, key=lambda x: (x["sanity_gain_5"] - 0.35 * (x["replacements"] - 1), -x["replacements"]))
        verdict = "OPTIONAL_IMPROVEMENT"
    else:
        recommended = None
        verdict = "KEEP_15"

    latest = latest or {}
    advanced = latest.get("advanced_stats_sync") or {}
    enrichment_healthy = any(isinstance(v, dict) and v.get("ok") for v in advanced.values())
    return {
        "schema_version": 460,
        "engine": "v4.6-evidence-fusion-sanity",
        "point_in_time": True,
        "raw_package_verdict": package_audit.get("overall_verdict"),
        "final_verdict": verdict,
        "best_by_replacement_count": assessed,
        "recommended_package": recommended,
        "evidence_health": {
            "official_universe": bool(umap),
            "prediction_priors_xmins_uncertainty": bool(pmap),
            "market_movement": any("transfers_in_event" in u for u in umap.values()),
            "global_advanced_sync_healthy": enrichment_healthy,
        },
        "guardrails": {
            "raw_optimizer_not_authoritative": True,
            "rate_spike_detection": True,
            "team_cluster_penalty": True,
            "outgoing_baseline_resistance": True,
            "early_season_multi_change_cap": True,
            "point_in_time_required": True,
            "prefer_fewer_changes_when_evidence_similar": True,
        },
    }


def run():
    out = sanity_report(
        read_json(DATA / "predictions_v4.json", {}),
        read_json(DATA / "universe.json", {}),
        read_json(DATA / "wc_package_audit_v4.json", {}),
        read_json(DATA / "latest.json", {}),
    )
    atomic_json(OUTFILE, out)
    print(json.dumps({"engine": out["engine"], "final_verdict": out["final_verdict"], "recommended_replacements": (out["recommended_package"] or {}).get("replacements")}, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
