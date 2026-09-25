from __future__ import annotations

"""Traceable provenance helpers for advisory V12 analytical metrics."""

from typing import Any, Mapping, Sequence


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def provider(row: Mapping[str, Any]) -> str | None:
    value = row.get("source") or row.get("provider")
    return str(value).strip() if value else None


def retrieved_at(row: Mapping[str, Any]) -> str | None:
    provenance = row.get("provenance")
    if isinstance(provenance, Mapping):
        for key in ("retrieved_at", "snapshot_timestamp", "effective_at"):
            if provenance.get(key):
                return str(provenance[key])
    for key in ("retrieved_at", "snapshot_timestamp", "freshness", "effective_at"):
        if row.get(key):
            return str(row[key])
    return None


def season(row: Mapping[str, Any], default: str | None = None) -> str | None:
    if row.get("season"):
        return str(row["season"])
    provenance = row.get("provenance")
    if isinstance(provenance, Mapping) and provenance.get("season"):
        return str(provenance["season"])
    return str(default) if default else None


def match_ref(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "gw": as_int(row.get("gw")),
        "match_id": row.get("match_id") or row.get("fixture"),
    }


def sample_confidence(matches: int, minutes: float) -> dict[str, Any]:
    if matches <= 0 or minutes <= 0:
        return {"label": "NONE", "score": 0.0}
    score = min(1.0, matches / 5.0) * min(1.0, minutes / 360.0)
    if matches < 2 or minutes < 90:
        label = "LOW"
    elif matches < 3 or minutes < 180:
        label = "DEVELOPING"
    elif matches < 5 or minutes < 300:
        label = "MODERATE"
    else:
        label = "MATURE"
    return {"label": label, "score": round(score, 4)}


def provider_guard(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    providers = sorted({value for row in rows if (value := provider(row))})
    return {
        "providers_seen": providers,
        "status": "OK" if len(providers) <= 1 else "PROVIDER_MISMATCH",
        "aggregation_allowed": len(providers) <= 1,
    }


def build_provenance(
    rows: Sequence[Mapping[str, Any]],
    *,
    metric_name: str,
    metric_definition: str,
    window: str,
    raw_or_derived: str,
    sample_minutes: float,
    sample_matches: int,
    confidence: Mapping[str, Any],
    availability: str,
    default_season: str | None = None,
    inputs: Sequence[str] = (),
) -> dict[str, Any]:
    providers = sorted({value for row in rows if (value := provider(row))})
    stamps = sorted({value for row in rows if (value := retrieved_at(row))})
    seasons = sorted({value for row in rows if (value := season(row, default_season))})
    return {
        "provider": providers[0] if len(providers) == 1 else None,
        "providers_seen": providers,
        "retrieved_at": stamps[-1] if stamps else None,
        "snapshot_timestamps_seen": stamps,
        "season": seasons[0] if len(seasons) == 1 else None,
        "season_availability": (
            "AVAILABLE" if len(seasons) == 1 else "UNAVAILABLE_OR_AMBIGUOUS"
        ),
        "seasons_seen": seasons,
        "gw_match": [match_ref(row) for row in rows],
        "metric_name": metric_name,
        "metric_definition": metric_definition,
        "window": window,
        "raw_or_derived": raw_or_derived,
        "sample_minutes": round(sample_minutes, 3),
        "sample_matches": int(sample_matches),
        "confidence": dict(confidence),
        "availability": availability,
        "inputs": list(inputs),
    }


def combine_window_provenance(
    windows: Sequence[Mapping[str, Any]],
    *,
    metric_name: str,
    metric_definition: str,
    output_window: str,
    availability: str,
    inputs: Sequence[str] = (),
) -> dict[str, Any]:
    contexts = [dict(window.get("provenance_context") or {}) for window in windows]
    providers = sorted(
        {value for ctx in contexts for value in ctx.get("providers_seen") or [] if value}
    )
    stamps = sorted(
        {
            value
            for ctx in contexts
            for value in ctx.get("snapshot_timestamps_seen") or []
            if value
        }
    )
    seasons = sorted(
        {value for ctx in contexts for value in ctx.get("seasons_seen") or [] if value}
    )
    refs: dict[tuple[Any, Any], dict[str, Any]] = {}
    for ctx in contexts:
        for ref in ctx.get("gw_match") or []:
            if isinstance(ref, Mapping):
                key = (ref.get("gw"), ref.get("match_id"))
                refs[key] = {"gw": key[0], "match_id": key[1]}
    confidence_scores = [
        as_float((ctx.get("confidence") or {}).get("score"))
        for ctx in contexts
        if isinstance(ctx.get("confidence"), Mapping)
    ]
    confidence_scores = [value for value in confidence_scores if value is not None]
    sample_minutes = max(
        (as_float(ctx.get("sample_minutes")) or 0.0 for ctx in contexts),
        default=0.0,
    )
    sample_matches = max(
        (int(ctx.get("sample_matches") or 0) for ctx in contexts),
        default=0,
    )
    return {
        "provider": providers[0] if len(providers) == 1 else None,
        "providers_seen": providers,
        "retrieved_at": stamps[-1] if stamps else None,
        "snapshot_timestamps_seen": stamps,
        "season": seasons[0] if len(seasons) == 1 else None,
        "season_availability": (
            "AVAILABLE" if len(seasons) == 1 else "UNAVAILABLE_OR_AMBIGUOUS"
        ),
        "seasons_seen": seasons,
        "gw_match": sorted(
            refs.values(),
            key=lambda ref: (ref.get("gw") or 0, str(ref.get("match_id") or "")),
        ),
        "metric_name": metric_name,
        "metric_definition": metric_definition,
        "window": output_window,
        "raw_or_derived": "DERIVED",
        "sample_minutes": round(sample_minutes, 3),
        "sample_matches": sample_matches,
        "source_samples": {
            str(window.get("window") or index): {
                "sample_minutes": window.get("sample_minutes"),
                "sample_matches": window.get("sample_matches"),
            }
            for index, window in enumerate(windows)
        },
        "confidence": {
            "label": "DERIVED_MIN_INPUT_CONFIDENCE",
            "score": round(min(confidence_scores), 4) if confidence_scores else 0.0,
        },
        "availability": availability,
        "inputs": list(inputs),
    }
