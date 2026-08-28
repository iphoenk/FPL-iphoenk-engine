from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from src.models.calibration import mae
from src.sources.observations import OBSERVATION_CONTRACT
from src.utils import DATA, ROOT, atomic_json, read_json

CONFIG_PATH = ROOT / "config" / "intelligence" / "challenger_registry.json"
OUT_PATH = DATA / "challenger_scorecard.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _observations() -> dict[str, Any]:
    registry = load_registry()
    path = ROOT / str(registry.get("observation_file") or "data/challenger_observations.json")
    return read_json(path, {"schema_version": 2, "observations": []})


def _current_internal(projections: dict[str, Any], gw: int) -> dict[int, dict[str, Any]]:
    out = {}
    for player in projections.get("players") or []:
        event = next((x for x in player.get("xpts_by_gw") or [] if int(x.get("gw") or -1) == gw), None)
        if not event:
            continue
        out[int(player["element"])] = {
            "provider": "internal",
            "gw": gw,
            "element": int(player["element"]),
            "name": player.get("name"),
            "xpts": _f(event.get("mean")),
            "xmins": _f((player.get("xmins") or {}).get("expected_minutes")),
            "start_probability": _f((player.get("xmins") or {}).get("start_probability")),
        }
    return out


def _historical_accuracy(provider: str, observations: list[dict[str, Any]], ledger: dict[str, Any]) -> dict[str, Any]:
    pairs_xpts = []
    pairs_xmins = []
    for obs in observations:
        if obs.get("provider") != provider or obs.get("contract") == OBSERVATION_CONTRACT:
            continue
        gw = str(obs.get("gw"))
        record = (ledger.get("records") or {}).get(gw) or {}
        if record.get("status") != "SETTLED":
            continue
        actual_map = {int(x["element"]): x for x in (record.get("actual") or {}).get("players") or []}
        actual = actual_map.get(int(obs.get("element") or -1))
        if not actual:
            continue
        if obs.get("xpts") is not None:
            pairs_xpts.append((_f(obs.get("xpts")), _f(actual.get("points"))))
        if obs.get("xmins") is not None:
            pairs_xmins.append((_f(obs.get("xmins")), _f(actual.get("minutes"))))
    return {
        "xpts_sample": len(pairs_xpts),
        "xpts_mae": round(mae([x[0] for x in pairs_xpts], [x[1] for x in pairs_xpts]), 4) if pairs_xpts else None,
        "xmins_sample": len(pairs_xmins),
        "xmins_mae": round(mae([x[0] for x in pairs_xmins], [x[1] for x in pairs_xmins]), 4) if pairs_xmins else None,
    }


def _fresh_structured(provider: str, observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in observations
        if row.get("provider") == provider
        and row.get("contract") == OBSERVATION_CONTRACT
        and row.get("status") == "AVAILABLE"
        and not row.get("stale")
    ]


def run() -> dict[str, Any]:
    registry = load_registry()
    obs_payload = _observations()
    observations = list(obs_payload.get("observations") or [])
    projections = read_json(DATA / "projections.json", {})
    ledger = read_json(DATA / "prediction_ledger.json", {})
    prediction_accuracy = read_json(DATA / "prediction_accuracy.json", {})
    planning_gw = int(projections.get("planning_gw") or 0)
    internal = _current_internal(projections, planning_gw)

    providers = []
    minimum = int(registry.get("minimum_sample_for_dynamic_weight") or 50)
    for provider in registry.get("providers") or []:
        pid = str(provider.get("id"))
        if pid == "internal":
            sample = int((prediction_accuracy.get("overall") or {}).get("sample_size") or 0)
            providers.append({
                **provider,
                "state": "ACTIVE",
                "current_coverage": len(internal),
                "historical_sample": sample,
                "dynamic_weight_eligible": bool(prediction_accuracy.get("dynamic_weight_eligible")),
            })
            continue

        model_rows = [
            row for row in observations
            if row.get("provider") == pid
            and row.get("contract") != OBSERVATION_CONTRACT
            and int(row.get("gw") or -1) == planning_gw
        ]
        structured_rows = _fresh_structured(pid, observations)
        accuracy = _historical_accuracy(pid, observations, ledger)
        sample = max(int(accuracy.get("xpts_sample") or 0), int(accuracy.get("xmins_sample") or 0))
        state = "ACTIVE_MODEL_OBSERVATION" if model_rows else ("ACTIVE_STRUCTURED_OBSERVATION" if structured_rows else "NO_OBSERVATION")
        providers.append({
            **provider,
            "state": state,
            "current_coverage": len(model_rows),
            "structured_current_coverage": len(structured_rows),
            "structured_capabilities": sorted({str(row.get("capability")) for row in structured_rows}),
            "historical_accuracy": accuracy,
            "dynamic_weight_eligible": sample >= minimum,
        })

    current_external: dict[int, list[dict[str, Any]]] = {}
    for obs in observations:
        if obs.get("contract") == OBSERVATION_CONTRACT:
            continue
        if int(obs.get("gw") or -1) != planning_gw or obs.get("provider") == "internal":
            continue
        current_external.setdefault(int(obs.get("element") or -1), []).append(obs)

    comparisons = []
    for element, internal_row in internal.items():
        ext = current_external.get(element, [])
        if not ext:
            continue
        xpts_values = [internal_row["xpts"]] + [_f(x.get("xpts")) for x in ext if x.get("xpts") is not None]
        xmins_values = [internal_row["xmins"]] + [_f(x.get("xmins")) for x in ext if x.get("xmins") is not None]
        mean_xpts = sum(xpts_values) / len(xpts_values) if xpts_values else None
        spread_xpts = max(xpts_values) - min(xpts_values) if len(xpts_values) >= 2 else 0.0
        mean_xmins = sum(xmins_values) / len(xmins_values) if xmins_values else None
        spread_xmins = max(xmins_values) - min(xmins_values) if len(xmins_values) >= 2 else 0.0
        rows = [internal_row] + ext
        comparisons.append({
            "element": element,
            "name": internal_row.get("name"),
            "gw": planning_gw,
            "providers": rows,
            "consensus": {
                "xpts_unweighted_mean": round(mean_xpts, 3) if mean_xpts is not None else None,
                "xpts_spread": round(spread_xpts, 3),
                "xmins_unweighted_mean": round(mean_xmins, 2) if mean_xmins is not None else None,
                "xmins_spread": round(spread_xmins, 2),
            },
            "disagreement_score": round(spread_xpts + spread_xmins / 30.0, 3),
            "weighting": "UNWEIGHTED until provider accuracy sample threshold is met",
        })
    comparisons.sort(key=lambda x: x["disagreement_score"], reverse=True)

    structured_fresh = [row for row in observations if row.get("contract") == OBSERVATION_CONTRACT and row.get("status") == "AVAILABLE" and not row.get("stale")]
    has_external = bool(comparisons or structured_fresh)
    out = {
        "generated_at": _now(),
        "registry": registry.get("registry"),
        "planning_gw": planning_gw,
        "auto_scrape": bool(registry.get("auto_scrape")),
        "providers": providers,
        "current_comparisons": comparisons[:50],
        "external_observation_count": len([x for x in observations if x.get("provider") != "internal"]),
        "structured_fresh_count": len(structured_fresh),
        "structured_cross_source": obs_payload.get("cross_source") or [],
        "governance": registry.get("governance") or {},
        "status": "ACTIVE_WITH_EXTERNAL_OBSERVATIONS" if has_external else "ACTIVE_INTERNAL_ONLY_EXTERNAL_DATA_ABSENT",
    }
    atomic_json(OUT_PATH, out)
    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {})["challenger_scorecard"] = "data/challenger_scorecard.json"
    latest["challenger_scorecard"] = {
        "status": out["status"],
        "providers": {p["id"]: p["state"] for p in providers},
        "current_comparisons": len(comparisons),
        "external_observation_count": out["external_observation_count"],
        "structured_fresh_count": out["structured_fresh_count"],
    }
    atomic_json(DATA / "latest.json", latest)
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
