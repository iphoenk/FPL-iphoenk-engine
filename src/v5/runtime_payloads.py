from __future__ import annotations

from typing import Any


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _pick(mapping: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: mapping.get(key) for key in keys if key in mapping}


def _degraded_capability_view(payload: Any) -> dict[str, Any]:
    row = _dict(payload)
    return _pick(row, "capabilities", "degraded_context")


def _evaluation_prediction(prediction: Any) -> dict[str, Any]:
    row = _dict(prediction)
    players = []
    for player in _list(row.get("players")):
        if not isinstance(player, dict):
            continue
        xmins = _dict(player.get("xmins"))
        events = []
        for event in _list(player.get("xpts_by_gw")):
            if not isinstance(event, dict):
                continue
            events.append(_pick(event, "gw", "mean", "std", "clean_sheet_probability"))
        players.append(
            {
                **_pick(player, "element", "name", "position", "current_season"),
                "xmins": _pick(xmins, "expected_minutes", "start_probability"),
                "xpts_by_gw": events,
            }
        )
    return {
        **_pick(
            row,
            "generated_at",
            "planning_gw",
            "horizon_gws",
            "ruleset_id",
            "prediction_quality",
            "capabilities",
            "degraded_context",
        ),
        "players": players,
    }


def _decision_finalize_prediction(prediction: Any) -> dict[str, Any]:
    row = _dict(prediction)
    return _pick(row, "model_version", "ruleset_id", "capabilities", "degraded_context")


def _decision_finalize_truth(truth: Any) -> dict[str, Any]:
    row = _dict(truth)
    team = _dict(row.get("team"))
    return {
        "rules": _dict(row.get("rules")),
        "team": _pick(team, "authority"),
        **_pick(row, "capabilities", "degraded_context"),
    }


def _decision_finalize_price(price: Any) -> dict[str, Any]:
    row = _dict(price)
    return {
        "alerts": _dict(row.get("alerts")),
        **_pick(row, "capabilities", "degraded_context"),
    }


def _governance_truth(truth: Any) -> dict[str, Any]:
    row = _dict(truth)
    team = _dict(row.get("team"))
    return {
        "rules": _dict(row.get("rules")),
        "team": _pick(team, "squad", "validation", "finance", "authority"),
        "chip_state": _dict(row.get("chip_state")),
        **_pick(row, "capabilities", "degraded_context"),
    }


def _governance_decision(decision: Any) -> dict[str, Any]:
    row = _dict(decision)
    return _pick(
        row,
        "status",
        "packages",
        "hold",
        "lineup",
        "dss",
        "decision_trace",
        "capabilities",
        "degraded_context",
        "production_recommendation",
    )


def compact_payload(service_id: str, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return the minimum semantics-preserving network contract for hot calls.

    Compaction is deliberately operation-specific and fail-open to the original
    payload for unknown calls. No analytical row is removed from its owning
    service or persistence artifact; only unused inter-service transport fields
    are omitted.
    """
    if service_id == "evaluation" and operation == "build":
        bootstrap = _dict(payload.get("bootstrap"))
        return {
            **payload,
            "prediction": _evaluation_prediction(payload.get("prediction")),
            "bootstrap": {"events": _list(bootstrap.get("events"))},
        }

    if service_id == "decision" and operation == "finalize":
        return {
            **payload,
            "truth": _decision_finalize_truth(payload.get("truth")),
            "prediction": _decision_finalize_prediction(payload.get("prediction")),
            "price": _decision_finalize_price(payload.get("price")),
            "evaluation": _degraded_capability_view(payload.get("evaluation")),
        }

    if service_id == "governance" and operation == "audit":
        return {
            **payload,
            "truth": _governance_truth(payload.get("truth")),
            "prediction": _degraded_capability_view(payload.get("prediction")),
            "price": _degraded_capability_view(payload.get("price")),
            "evaluation": _degraded_capability_view(payload.get("evaluation")),
            "decision": _governance_decision(payload.get("decision")),
        }

    return payload
