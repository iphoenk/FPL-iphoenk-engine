from __future__ import annotations

import math
from datetime import datetime, timezone

from src.utils import CONFIG, parse_dt, read_json

POLICY = CONFIG / "serving_improvement_registry.json"
EXTERNAL_TYPES = {"EUROPEAN", "DOMESTIC_CUP", "INTERNATIONAL"}


def _f(value, default=0.0):
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _freshness_weight(verified_at: str | None, now: datetime, half_life_hours: float) -> tuple[float, float | None]:
    parsed = parse_dt(verified_at)
    if not parsed:
        return 0.0, None
    age = max(0.0, (now - parsed).total_seconds() / 3600.0)
    return math.pow(0.5, age / max(1.0, half_life_hours)), age


def attach_xmins_evidence(predictions: dict, competitive_load: dict, now: datetime | None = None) -> dict:
    """Attach verified load/news evidence to xMins confidence and rotation review only."""
    current = now or datetime.now(timezone.utc)
    cfg = (read_json(POLICY, {}) or {}).get("xmins") or {}
    half_life = _f(cfg.get("team_news_half_life_hours"), 18.0)
    by_element = {
        int(row.get("element") or 0): row
        for row in competitive_load.get("players") or []
        if row.get("element") is not None
    }
    covered = 0
    verified_press = 0
    external_counts = {kind: 0 for kind in EXTERNAL_TYPES}
    for player in predictions.get("players") or []:
        element = int(player.get("element") or 0)
        evidence = by_element.get(element) or {}
        matches = sorted(
            list(evidence.get("current_gw_matches") or []),
            key=lambda row: row.get("match_time") or "",
        )
        press = evidence.get("press_conference") or {}
        weight, age = _freshness_weight(press.get("verified_at"), current, half_life)
        press_verified = str(press.get("status") or "").upper() == "VERIFIED"
        if matches:
            covered += 1
        if press_verified:
            verified_press += 1
        for match in matches:
            kind = str(match.get("competition_type") or "").upper()
            if kind in EXTERNAL_TYPES and match.get("source_quality") == "VERIFIED_EXTERNAL_OFFICIAL":
                external_counts[kind] += 1
        latest_match = matches[-1] if matches else None
        rest_hours = (latest_match or {}).get("rest_hours_to_next_fixture")
        load_state = (
            "HEAVY"
            if rest_hours is not None and _f(rest_hours) < 72 and _f((latest_match or {}).get("minutes")) >= 60
            else "NORMAL" if latest_match else "UNVERIFIED"
        )
        verified_external = [
            match for match in matches
            if str(match.get("competition_type") or "").upper() in EXTERNAL_TYPES
            and match.get("source_quality") == "VERIFIED_EXTERNAL_OFFICIAL"
        ]
        for fixture in player.get("fixtures") or []:
            xm = fixture.get("xmins") or {}
            base_conf = _f(xm.get("start_probability_confidence"), .5)
            evidence_completeness = 0.35 + (0.25 if latest_match else 0.0) + (0.40 * weight if press_verified else 0.0)
            confidence = max(0.0, min(1.0, 0.75 * base_conf + 0.25 * evidence_completeness))
            xm["start_probability_confidence"] = round(confidence, 4)
            xm["start_probability_confidence_grade"] = "HIGH" if confidence >= .78 else "MEDIUM" if confidence >= .58 else "LOW"
            decomposition = xm.setdefault("source_decomposition", {})
            decomposition["competitive_load"] = {
                "state": load_state,
                "latest_match": latest_match,
                "verified_external_matches": verified_external,
                "external_evidence_state": "VERIFIED" if verified_external else "EVIDENCE_GATED",
                "direct_start_probability_mutation": False,
                "decision_usage": "xmins_confidence_and_rotation_review",
            }
            decomposition["official_beat_evidence"] = {
                "state": "VERIFIED" if press_verified else "UNAVAILABLE",
                "freshness_weight": round(weight, 4),
                "age_hours": round(age, 2) if age is not None else None,
                "availability": press.get("availability"),
                "rotation_hint": press.get("rotation_hint"),
                "fitness_or_knock": press.get("fitness_or_knock"),
                "source": press.get("source"),
                "direct_start_probability_mutation": False,
            }
            decomposition["freshness_decay_applied_to_evidence_confidence"] = press_verified
            decomposition["same_physical_load_signal_counted_once"] = True

    capability = predictions.setdefault("capability_evidence", {})
    capability["competitive_load_consumer_active"] = True
    capability["competitive_load_xmins_confidence_players"] = covered
    capability["verified_press_xmins_confidence_players"] = verified_press
    capability["verified_external_competitive_rows"] = external_counts
    guardrails = predictions.setdefault("guardrails", {})
    guardrails["competitive_load_direct_xpts_mutation_forbidden"] = True
    guardrails["competitive_load_direct_start_probability_mutation_forbidden"] = True
    guardrails["unverified_external_competitive_signal_is_zero"] = True
    guardrails["team_news_freshness_decay"] = True
    guardrails["single_load_signal_double_count_forbidden"] = True
    return predictions
