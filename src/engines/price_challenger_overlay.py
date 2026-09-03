from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from src.sources.observations import OBSERVATION_CONTRACT, normalize_subject_key
from src.utils import atomic_json, read_json

PRICE_LIST_KEYS = ("players", "top_buy_pressure", "top_sell_pressure", "top_rise_risk", "top_fall_risk")


def _fresh_price_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in payload.get("observations") or []
        if isinstance(row, dict)
        and row.get("contract") == OBSERVATION_CONTRACT
        and row.get("capability") == "price_prediction"
        and row.get("status") == "AVAILABLE"
        and not row.get("stale")
        and isinstance(row.get("value"), dict)
    ]


def _context_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in _fresh_price_rows(payload):
        key = str(row.get("subject_key") or normalize_subject_key((row.get("subject") or {}).get("player")))
        if key:
            grouped.setdefault(key, []).append(row)
    cross = {str(row.get("subject_key")): row for row in payload.get("cross_source") or [] if isinstance(row, dict)}
    out: dict[str, dict[str, Any]] = {}
    for key, rows in grouped.items():
        sources = []
        for row in sorted(rows, key=lambda item: str(item.get("source_id") or item.get("provider") or "")):
            value = row.get("value") or {}
            sources.append({
                "source_id": row.get("source_id") or row.get("provider"),
                "direction": value.get("direction"),
                "observed_at": row.get("observed_at"),
                "fetched_at": row.get("fetched_at"),
                "source_url": row.get("source_url"),
                "confidence": row.get("confidence"),
                "parser_version": row.get("parser_version"),
                "source_value": value,
            })
        state = cross.get(key) or {}
        out[key] = {
            "mode": "CONTEXT_ONLY",
            "authority": "Official FPL",
            "official_fields_overridden": False,
            "state": state.get("state") or ("SINGLE_SOURCE" if len(sources) == 1 else "MULTI_SOURCE"),
            "providers": state.get("providers") or [row["source_id"] for row in sources],
            "directions": state.get("directions") or sorted({str(row.get("direction")) for row in sources if row.get("direction")}),
            "sources": sources,
        }
    return out


def _summary(observations: dict[str, Any], *, matched: set[str] | None = None, skipped_ambiguous: set[str] | None = None) -> dict[str, Any]:
    fresh = _fresh_price_rows(observations)
    return {
        "contract": "price_challenger_context_v1",
        "authority": "Official FPL",
        "context_only": True,
        "official_fields_overridden": False,
        "fresh_observation_count": len(fresh),
        "matched_player_count": len(matched or set()),
        "matched_subject_keys": sorted(matched or set()),
        "ambiguous_subject_keys_skipped": sorted(skipped_ambiguous or set()),
        "cross_source_disagreements": sum(1 for row in observations.get("cross_source") or [] if row.get("state") == "DISAGREEMENT"),
        "policy": {
            "only_available_nonstale_observations_consumed": True,
            "name_match_must_be_unique_in_official_price_universe": True,
            "challenger_never_changes_official_price_or_urgency": True,
        },
    }


def apply_context(prices: dict[str, Any], observations: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    index = _context_index(observations)
    if not index:
        # No challenger evidence means there is nothing to attach. Avoid a full
        # deep-copy of the 651-player Official price universe while preserving
        # the exact empty-context contract and Official authority.
        enriched = dict(prices)
        summary = _summary(observations)
        enriched["challenger_price_summary"] = summary
        return enriched, summary

    enriched = copy.deepcopy(prices)
    canonical = enriched.get("players") or []
    name_counts: dict[str, int] = {}
    for row in canonical:
        key = normalize_subject_key(row.get("name"))
        if key:
            name_counts[key] = name_counts.get(key, 0) + 1

    matched: set[str] = set()
    skipped_ambiguous: set[str] = set()
    for list_key in PRICE_LIST_KEYS:
        rows = enriched.get(list_key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            key = normalize_subject_key(row.get("name"))
            context = index.get(key)
            if not key or not context:
                continue
            if name_counts.get(key, 0) != 1:
                skipped_ambiguous.add(key)
                continue
            row["challenger_price_context"] = copy.deepcopy(context)
            matched.add(key)

    summary = _summary(observations, matched=matched, skipped_ambiguous=skipped_ambiguous)
    enriched["challenger_price_summary"] = summary
    return enriched, summary


def _attach_to_alert_rows(payload: dict[str, Any], index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not index:
        return payload
    out = copy.deepcopy(payload)
    for key in ("alerts", "market_watch_candidates"):
        rows = out.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            context = index.get(normalize_subject_key(row.get("name")))
            if context:
                row["challenger_price_context"] = copy.deepcopy(context)
    return out


def patch_files(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    prices_path = root / "prices.json"
    observations_path = root / "challenger_observations.json"
    context_path = root / "price_challenger_context.json"
    latest_path = root / "latest.json"
    alerts_path = root / "price_alerts.json"

    prices = read_json(prices_path, {})
    observations = read_json(observations_path, {"observations": [], "cross_source": []}) if observations_path.exists() else {"observations": [], "cross_source": []}
    enriched, summary = apply_context(prices, observations)
    atomic_json(prices_path, enriched)
    atomic_json(context_path, summary)

    index = _context_index(observations)
    if alerts_path.exists() and index:
        alerts = read_json(alerts_path, {})
        atomic_json(alerts_path, _attach_to_alert_rows(alerts, index))

    if latest_path.exists():
        latest = read_json(latest_path, {})
        price_summary = latest.get("price_summary") or {}
        if index:
            for key in ("top_buy_pressure", "top_sell_pressure", "top_rise_risk", "top_fall_risk", "alerts"):
                rows = price_summary.get(key)
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    context = index.get(normalize_subject_key(row.get("name")))
                    if context:
                        row["challenger_price_context"] = copy.deepcopy(context)
        price_summary["challenger_context"] = summary
        latest["price_summary"] = price_summary
        latest.setdefault("files", {})["price_challenger_context"] = "data/price_challenger_context.json"
        atomic_json(latest_path, latest)
    return summary


if __name__ == "__main__":
    print(json.dumps(patch_files(), ensure_ascii=False))
