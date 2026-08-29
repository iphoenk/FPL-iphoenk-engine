from __future__ import annotations

import math
from datetime import datetime, timezone

from src.utils import CONFIG, parse_dt, read_json

POLICY = CONFIG / "serving_improvement_registry.json"


def _f(value, default=0.0):
    try: return float(value if value is not None else default)
    except (TypeError, ValueError): return float(default)


def _freshness_weight(verified_at: str | None, now: datetime, half_life_hours: float) -> tuple[float, float | None]:
    parsed = parse_dt(verified_at)
    if not parsed: return 0.0, None
    age = max(0.0, (now - parsed).total_seconds() / 3600.0)
    return math.pow(0.5, age / max(1.0, half_life_hours)), age


def attach_xmins_evidence(predictions: dict, competitive_load: dict, now: datetime | None = None) -> dict:
    """Attach load/news evidence to xMins confidence without double-counting it into xPts.

    Competitive-load policy explicitly permits xMins confidence/rotation review and
    forbids direct points mutation. The actual start probability remains the canonical
    model output until a separately calibrated probability adjustment is promoted.
    """
    current = now or datetime.now(timezone.utc)
    cfg = (read_json(POLICY, {}) or {}).get("xmins") or {}
    half_life = _f(cfg.get("team_news_half_life_hours"), 18.0)
    by_element = {int(row.get("element") or 0): row for row in competitive_load.get("players") or [] if row.get("element") is not None}
    covered = 0; verified_press = 0
    for player in predictions.get("players") or []:
        element = int(player.get("element") or 0); evidence = by_element.get(element) or {}; matches = list(evidence.get("current_gw_matches") or []); press = evidence.get("press_conference") or {}; weight, age = _freshness_weight(press.get("verified_at"), current, half_life); press_verified = str(press.get("status") or "").upper() == "VERIFIED"
        if matches: covered += 1
        if press_verified: verified_press += 1
        latest_match = matches[-1] if matches else None; rest_hours = (latest_match or {}).get("rest_hours_to_next_fixture")
        load_state = "HEAVY" if rest_hours is not None and _f(rest_hours) < 72 and _f((latest_match or {}).get("minutes")) >= 60 else "NORMAL" if latest_match else "UNVERIFIED"
        for fixture in player.get("fixtures") or []:
            xm = fixture.get("xmins") or {}; base_conf = _f(xm.get("start_probability_confidence"), .5)
            evidence_completeness = 0.35 + (0.25 if latest_match else 0.0) + (0.40 * weight if press_verified else 0.0)
            confidence = max(0.0, min(1.0, 0.75 * base_conf + 0.25 * evidence_completeness))
            xm["start_probability_confidence"] = round(confidence, 4); xm["start_probability_confidence_grade"] = "HIGH" if confidence >= .78 else "MEDIUM" if confidence >= .58 else "LOW"
            decomposition = xm.setdefault("source_decomposition", {})
            decomposition["competitive_load"] = {"state":load_state,"latest_match":latest_match,"direct_start_probability_mutation":False,"decision_usage":"xmins_confidence_and_rotation_review"}
            decomposition["official_beat_evidence"] = {"state":"VERIFIED" if press_verified else "UNAVAILABLE","freshness_weight":round(weight,4),"age_hours":round(age,2) if age is not None else None,"availability":press.get("availability"),"rotation_hint":press.get("rotation_hint"),"fitness_or_knock":press.get("fitness_or_knock"),"source":press.get("source"),"direct_start_probability_mutation":False}
            decomposition["freshness_decay_applied_to_evidence_confidence"] = press_verified
            decomposition["same_physical_load_signal_counted_once"] = True
    predictions.setdefault("capability_evidence", {})["competitive_load_xmins_confidence_players"] = covered
    predictions["capability_evidence"]["verified_press_xmins_confidence_players"] = verified_press
    predictions.setdefault("guardrails", {})["competitive_load_direct_xpts_mutation_forbidden"] = True
    predictions["guardrails"]["team_news_freshness_decay"] = True
    predictions["guardrails"]["single_load_signal_double_count_forbidden"] = True
    return predictions
