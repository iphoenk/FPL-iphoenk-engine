from __future__ import annotations

"""External analyst challenge layer for Stage C.

External claims are opinion evidence only. They never enter V6 factual data,
predicted points, or ensemble weights.
"""

from datetime import datetime
from typing import Any, Mapping, Sequence


ALLOWED_STANCES = frozenset({"BUY", "WATCH", "SELL"})
RESULTS = frozenset({"AGREE", "DISAGREE", "UNRESOLVED"})
XGSTAT_NAMES = frozenset({"XGSTAT", "XGSTAT.COM"})


class ExternalChallengeError(ValueError):
    pass


def _timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExternalChallengeError("timestamp is required")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExternalChallengeError("timestamp must be ISO-8601") from exc
    return text


def _normalize_claim(raw: Mapping[str, Any]) -> dict[str, Any]:
    source = str(raw.get("source") or "").strip()
    if not source:
        raise ExternalChallengeError("source is required")
    stance = str(
        raw.get("claim")
        or raw.get("stance")
        or raw.get("recommendation")
        or raw.get("buy_watch_sell")
        or ""
    ).upper().strip()
    if stance not in ALLOWED_STANCES:
        raise ExternalChallengeError("external claim must be BUY/WATCH/SELL")
    source_token = source.upper()
    ingestion_mode = str(raw.get("ingestion_mode") or "MANUAL_CAPTURE").upper().strip()
    if source_token in XGSTAT_NAMES and ingestion_mode != "MANUAL_VALIDATION_ONLY":
        raise ExternalChallengeError(
            "xGStat is MANUAL_VALIDATION_ONLY; automated or unspecified ingestion is forbidden"
        )
    element = raw.get("element")
    if element is None:
        element = raw.get("player_id")
    try:
        element_id = None if element is None else int(element)
    except (TypeError, ValueError) as exc:
        raise ExternalChallengeError("element/player_id must be an integer when supplied") from exc

    rationale = raw.get("rationale_tags") or []
    if isinstance(rationale, str):
        rationale = [rationale]
    return {
        "source": source,
        "timestamp": _timestamp(raw.get("timestamp") or raw.get("observed_at")),
        "player": raw.get("player"),
        "element": element_id,
        "team": raw.get("team"),
        "claim_type": raw.get("claim_type") or "PLAYER_STANCE",
        "stance": stance,
        "captain_claim": raw.get("captain_claim"),
        "route_claim": raw.get("route_claim"),
        "rationale_tags": [str(value) for value in rationale],
        "raw_reference": raw.get("raw_reference"),
        "ingestion_mode": ingestion_mode,
        "confidence": "EXTERNAL_OPINION",
        "factual_authority": False,
    }


def _candidate_map(scan: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in scan.get("material_candidates") or []:
        if not isinstance(row, Mapping):
            continue
        try:
            element = int(row.get("element"))
        except (TypeError, ValueError):
            continue
        out[element] = dict(row)
    return out


def _stance_challenge(
    stance: str,
    candidate: Mapping[str, Any] | None,
) -> tuple[str, list[str]]:
    if not candidate:
        return "UNRESOLVED", ["player has no material Stage C model signal"]
    positive = list(candidate.get("positive_signals") or [])
    negative = list(candidate.get("negative_signals") or [])
    if stance == "BUY":
        if positive and not negative:
            return "AGREE", [f"positive model signals: {', '.join(positive)}"]
        if negative and not positive:
            return "DISAGREE", [f"negative model signals: {', '.join(negative)}"]
        return "UNRESOLVED", [
            "model evidence is mixed" if positive or negative else "no directional model evidence"
        ]
    if stance == "SELL":
        if negative and not positive:
            return "AGREE", [f"negative model signals: {', '.join(negative)}"]
        if positive and not negative:
            return "DISAGREE", [f"positive model signals: {', '.join(positive)}"]
        return "UNRESOLVED", [
            "model evidence is mixed" if positive or negative else "no directional model evidence"
        ]
    # WATCH is a claim that the player merits attention, not that V12 should act.
    if positive or negative:
        return "AGREE", [
            "Stage C also identifies material evidence worth monitoring"
        ]
    return "UNRESOLVED", ["no material Stage C signal to validate WATCH"]


def _captain_challenge(
    claim: Any,
    *,
    element: int | None,
    decision_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if claim in {None, False, "", "NONE"}:
        return {"result": "UNRESOLVED", "applicable": False, "reason": "NO_CAPTAIN_CLAIM"}
    context = dict(decision_context or {})
    canonical = context.get("captain_element")
    if canonical is None:
        return {
            "result": "UNRESOLVED",
            "applicable": True,
            "reason": "P1_7_CAPTAIN_EVIDENCE_NOT_SUPPLIED",
        }
    try:
        canonical_id = int(canonical)
    except (TypeError, ValueError):
        return {
            "result": "UNRESOLVED",
            "applicable": True,
            "reason": "P1_7_CAPTAIN_EVIDENCE_INVALID",
        }
    return {
        "result": "AGREE" if element is not None and canonical_id == element else "DISAGREE",
        "applicable": True,
        "canonical_captain_element": canonical_id,
        "reason": "COMPARED_TO_EXISTING_P1_7_CAPTAIN",
    }


def _route_challenge(
    claim: Any,
    *,
    decision_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if claim in {None, False, "", "NONE"}:
        return {"result": "UNRESOLVED", "applicable": False, "reason": "NO_ROUTE_CLAIM"}
    context = dict(decision_context or {})
    canonical = context.get("selected_route_id")
    if canonical in {None, ""}:
        return {
            "result": "UNRESOLVED",
            "applicable": True,
            "reason": "P1_2B_ROUTE_EVIDENCE_NOT_SUPPLIED",
        }
    claim_text = str(claim)
    return {
        "result": "AGREE" if claim_text == str(canonical) else "DISAGREE",
        "applicable": True,
        "canonical_route_id": str(canonical),
        "reason": "COMPARED_TO_EXISTING_P1_2B_ROUTE",
    }


def challenge_external_claim(
    raw_claim: Mapping[str, Any],
    *,
    scan: Mapping[str, Any],
    decision_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    claim = _normalize_claim(raw_claim)
    candidate = _candidate_map(scan).get(int(claim["element"])) if claim["element"] is not None else None
    stance_result, reasons = _stance_challenge(claim["stance"], candidate)
    captain = _captain_challenge(
        claim.get("captain_claim"),
        element=claim.get("element"),
        decision_context=decision_context,
    )
    route = _route_challenge(
        claim.get("route_claim"),
        decision_context=decision_context,
    )
    return {
        "contract": "V12_STAGEC_EXTERNAL_CLAIM_CHALLENGE_V1",
        "claim": claim,
        "model_challenge": {
            "result": stance_result,
            "reasons": reasons,
            "model_positive_signals": list((candidate or {}).get("positive_signals") or []),
            "model_negative_signals": list((candidate or {}).get("negative_signals") or []),
            "sample_confidence": (candidate or {}).get("sample_confidence"),
            "why_flagged": list((candidate or {}).get("why_flagged") or []),
        },
        "captain_challenge": captain,
        "route_challenge": route,
        "predicted_points_adjustment": 0.0,
        "factual_plane_mutated": False,
        "ensemble_weight_applied": False,
    }


def build_external_challenge_layer(
    claims: Sequence[Mapping[str, Any]] | None,
    *,
    scan: Mapping[str, Any],
    decision_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [
        challenge_external_claim(
            claim,
            scan=scan,
            decision_context=decision_context,
        )
        for claim in (claims or ())
        if isinstance(claim, Mapping)
    ]
    counts = {
        result: sum(
            row.get("model_challenge", {}).get("result") == result
            for row in rows
        )
        for result in ("AGREE", "DISAGREE", "UNRESOLVED")
    }
    return {
        "contract": "V12_STAGEC_EXTERNAL_CHALLENGE_LAYER_V1",
        "state": "AVAILABLE" if rows else "NO_EXTERNAL_DATA",
        "claim_count": len(rows),
        "counts": counts,
        "rows": rows,
        "governance": {
            "external_opinion_is_not_factual_authority": True,
            "external_buy_sell_never_adjusts_predicted_points": True,
            "silent_ensemble_forbidden": True,
            "xgstat_policy": "MANUAL_VALIDATION_ONLY",
            "xgstat_scraping_forbidden": True,
            "automated_social_capture_forbidden": True,
            "manual_capture_may_be_challenged": True,
        },
    }
