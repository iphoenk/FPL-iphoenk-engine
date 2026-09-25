from __future__ import annotations

"""Advisory multi-window player form, regression and trajectory evidence."""

from collections import defaultdict
from typing import Any, Mapping, Sequence

from src.models.v12_metric_provenance import (
    as_float,
    as_int,
    build_provenance,
    combine_window_provenance,
    match_ref,
    provider_guard,
    sample_confidence,
)

WINDOWS = ("MATCH", "L3", "L5", "SEASON")
BASE_METRICS = (
    "minutes", "starts", "goals", "assists", "xg", "npxg", "xa", "xgi",
    "shots", "shots_in_box", "shots_on_target", "box_touches", "key_passes",
    "chances_created",
)
PER90_METRICS = tuple(x for x in BASE_METRICS if x not in {"minutes", "starts"})
DEFINITIONS = {
    "minutes": "minutes played",
    "starts": "started match indicator aggregated as count",
    "goals": "goals scored",
    "assists": "assists recorded by source",
    "xg": "expected goals",
    "npxg": "non-penalty expected goals",
    "xa": "expected assists",
    "xgi": "expected goal involvements",
    "shots": "total shots",
    "shots_in_box": "shots from inside the penalty area",
    "shots_on_target": "shots on target",
    "box_touches": "touches in opposition penalty area",
    "key_passes": "key passes",
    "chances_created": "chances created",
}


def _sort_key(row: Mapping[str, Any]) -> tuple[int, str]:
    return (
        as_int(row.get("gw")) or 0,
        str(row.get("match_id") or row.get("fixture") or ""),
    )


def _played_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    played, excluded = [], 0
    for source in rows:
        row = dict(source)
        minutes = as_float(row.get("minutes"))
        if minutes is None or minutes <= 0:
            excluded += 1
        else:
            played.append(row)
    played.sort(key=_sort_key)
    return played, excluded


def _window_rows(
    played: Sequence[Mapping[str, Any]],
    name: str,
) -> list[dict[str, Any]]:
    rows = list(played)
    sizes = {"MATCH": 1, "L3": 3, "L5": 5}
    return rows if name == "SEASON" else rows[-sizes[name]:]


def _raw(row: Mapping[str, Any], metric: str) -> float | None:
    if metric == "starts":
        return None if row.get("starter") is None else float(bool(row.get("starter")))
    aliases = {
        "shots_on_target": ("shots_on_target", "sot"),
        "box_touches": (
            "box_touches",
            "touches_in_box",
            "touches_opposition_box",
        ),
    }.get(metric, (metric,))
    for key in aliases:
        if key in row:
            return as_float(row.get(key))
    return None


def _availability(rows: Sequence[Any], present: Sequence[Any]) -> str:
    if not rows:
        return "UNAVAILABLE_NO_APPEARANCES"
    if not present:
        return "UNAVAILABLE"
    if len(present) != len(rows):
        return "PARTIAL"
    return "AVAILABLE"


def _aggregate_metric(
    rows: Sequence[Mapping[str, Any]],
    metric: str,
    name: str,
    sample_minutes: float,
    confidence: Mapping[str, Any],
    season: str | None,
) -> dict[str, Any]:
    values = [_raw(row, metric) for row in rows]
    present = [value for value in values if value is not None]
    availability = _availability(rows, present)
    value = round(sum(present), 6) if availability == "AVAILABLE" else None
    provenance = build_provenance(
        rows,
        metric_name=metric,
        metric_definition=DEFINITIONS[metric],
        window=name,
        raw_or_derived="RAW_AGGREGATED",
        sample_minutes=sample_minutes,
        sample_matches=len(rows),
        confidence=confidence,
        availability=availability,
        default_season=season,
    )
    node = {
        "value": value,
        "availability": availability,
        "available_matches": len(present),
        "missing_matches": len(rows) - len(present),
        "provenance": provenance,
    }
    if metric in PER90_METRICS:
        per90 = (
            round(value * 90.0 / sample_minutes, 6)
            if value is not None and sample_minutes > 0
            else None
        )
        node["per90"] = per90
        node["per90_provenance"] = build_provenance(
            rows,
            metric_name=f"{metric}_per90",
            metric_definition=f"{DEFINITIONS[metric]} per 90 minutes",
            window=name,
            raw_or_derived="DERIVED",
            sample_minutes=sample_minutes,
            sample_matches=len(rows),
            confidence=confidence,
            availability="AVAILABLE" if per90 is not None else availability,
            default_season=season,
            inputs=(metric, "minutes"),
        )
    return node


def _derived_window_node(
    value: float | None,
    *,
    rows: Sequence[Mapping[str, Any]],
    name: str,
    sample_minutes: float,
    confidence: Mapping[str, Any],
    season: str | None,
    metric_name: str,
    definition: str,
    inputs: Sequence[str],
) -> dict[str, Any]:
    availability = "AVAILABLE" if value is not None else "UNAVAILABLE"
    return {
        "value": value,
        "availability": availability,
        "provenance": build_provenance(
            rows,
            metric_name=metric_name,
            metric_definition=definition,
            window=name,
            raw_or_derived="DERIVED",
            sample_minutes=sample_minutes,
            sample_matches=len(rows),
            confidence=confidence,
            availability=availability,
            default_season=season,
            inputs=inputs,
        ),
    }


def _window_payload(
    rows: Sequence[Mapping[str, Any]],
    name: str,
    season: str | None,
) -> dict[str, Any]:
    minutes = sum(as_float(row.get("minutes")) or 0.0 for row in rows)
    confidence = sample_confidence(len(rows), minutes)
    metrics = {
        metric: _aggregate_metric(
            rows,
            metric,
            name,
            minutes,
            confidence,
            season,
        )
        for metric in BASE_METRICS
    }
    starts = metrics["starts"]["value"]
    start_share = (
        round(starts / len(rows), 6)
        if starts is not None and rows
        else None
    )
    minutes_per_app = round(minutes / len(rows), 6) if rows else None
    context = build_provenance(
        rows,
        metric_name="window_context",
        metric_definition=(
            "source and sample context for all metrics in rolling window"
        ),
        window=name,
        raw_or_derived="CONTEXT",
        sample_minutes=minutes,
        sample_matches=len(rows),
        confidence=confidence,
        availability="AVAILABLE" if rows else "UNAVAILABLE_NO_APPEARANCES",
        default_season=season,
    )
    return {
        "window": name,
        "sample_matches": len(rows),
        "sample_minutes": round(minutes, 3),
        "confidence": confidence,
        "match_refs": [match_ref(row) for row in rows],
        "provenance_context": context,
        "metrics": metrics,
        "derived": {
            "start_share": _derived_window_node(
                start_share,
                rows=rows,
                name=name,
                sample_minutes=minutes,
                confidence=confidence,
                season=season,
                metric_name="start_share",
                definition="starts divided by played appearances in window",
                inputs=("starts", "sample_matches"),
            ),
            "minutes_per_appearance": _derived_window_node(
                minutes_per_app,
                rows=rows,
                name=name,
                sample_minutes=minutes,
                confidence=confidence,
                season=season,
                metric_name="minutes_per_appearance",
                definition=(
                    "sample minutes divided by played appearances in window"
                ),
                inputs=("minutes", "sample_matches"),
            ),
        },
    }


def _value(window: Mapping[str, Any], metric: str) -> float | None:
    return as_float(
        (((window.get("metrics") or {}).get(metric) or {}).get("value"))
    )


def _per90(window: Mapping[str, Any], metric: str) -> float | None:
    return as_float(
        (((window.get("metrics") or {}).get(metric) or {}).get("per90"))
    )


def _derived_value(window: Mapping[str, Any], metric: str) -> float | None:
    return as_float(
        (((window.get("derived") or {}).get(metric) or {}).get("value"))
    )


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round(a - b, 6)


def _ratio(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None or b <= 0 else round(a / b, 6)


def _rate(a: float | None, b: float | None) -> float | None:
    return _ratio(a, b)


def _node(
    value: float | None,
    *,
    recent: Mapping[str, Any],
    season: Mapping[str, Any],
    metric_name: str,
    definition: str,
    inputs: Sequence[str],
) -> dict[str, Any]:
    availability = "AVAILABLE" if value is not None else "UNAVAILABLE"
    return {
        "value": value,
        "availability": availability,
        "provenance": combine_window_provenance(
            (recent, season),
            metric_name=metric_name,
            metric_definition=definition,
            output_window=f"{recent.get('window')}_VS_SEASON",
            availability=availability,
            inputs=inputs,
        ),
    }


def _comparisons(windows: Mapping[str, Any]) -> dict[str, Any]:
    season = windows["SEASON"]
    out = {}
    for name in ("MATCH", "L3", "L5"):
        recent, metrics = windows[name], {}
        for metric in PER90_METRICS:
            recent_p90 = _per90(recent, metric)
            season_p90 = _per90(season, metric)
            metrics[metric] = {
                "delta_vs_season": _node(
                    _delta(recent_p90, season_p90),
                    recent=recent,
                    season=season,
                    metric_name=f"{metric}_{name.lower()}_vs_season_delta",
                    definition=f"{metric} recent per90 minus season per90",
                    inputs=(
                        f"{name}.{metric}_per90",
                        f"SEASON.{metric}_per90",
                    ),
                ),
                "ratio_vs_season": _node(
                    _ratio(recent_p90, season_p90),
                    recent=recent,
                    season=season,
                    metric_name=f"{metric}_{name.lower()}_vs_season_ratio",
                    definition=f"{metric} recent per90 divided by season per90",
                    inputs=(
                        f"{name}.{metric}_per90",
                        f"SEASON.{metric}_per90",
                    ),
                ),
                "recent_share": _node(
                    _ratio(_value(recent, metric), _value(season, metric)),
                    recent=recent,
                    season=season,
                    metric_name=f"{metric}_{name.lower()}_share_of_season",
                    definition=f"{metric} recent total divided by season total",
                    inputs=(
                        f"{name}.{metric}",
                        f"SEASON.{metric}",
                    ),
                ),
            }
        out[name] = metrics
    return out


def _regression(window: Mapping[str, Any]) -> dict[str, Any]:
    goals, assists = _value(window, "goals"), _value(window, "assists")
    gi = goals + assists if goals is not None and assists is not None else None
    specs = {
        "goals_minus_xg": (
            _delta(goals, _value(window, "xg")),
            ("goals", "xg"),
        ),
        "goals_minus_npxg": (
            _delta(goals, _value(window, "npxg")),
            ("goals", "npxg"),
        ),
        "assists_minus_xa": (
            _delta(assists, _value(window, "xa")),
            ("assists", "xa"),
        ),
        "gi_minus_xgi": (
            _delta(gi, _value(window, "xgi")),
            ("goals", "assists", "xgi"),
        ),
    }
    minutes = as_float(window.get("sample_minutes")) or 0.0
    out = {}
    for key, (value, inputs) in specs.items():
        per90 = (
            round(value * 90 / minutes, 6)
            if value is not None and minutes > 0
            else None
        )
        availability = "AVAILABLE" if value is not None else "UNAVAILABLE"
        provenance = combine_window_provenance(
            (window,),
            metric_name=key,
            metric_definition=key.replace("_", " "),
            output_window=str(window.get("window")),
            availability=availability,
            inputs=inputs,
        )
        out[key] = {
            "value": value,
            "per90": per90,
            "availability": availability,
            "provenance": provenance,
            "per90_provenance": {
                **provenance,
                "metric_name": f"{key}_per90",
                "metric_definition": f"{key.replace('_', ' ')} per 90 minutes",
                "availability": (
                    "AVAILABLE" if per90 is not None else availability
                ),
                "inputs": [key, "minutes"],
            },
        }
    return out


def _trajectory(windows: Mapping[str, Any]) -> dict[str, Any]:
    recent, season = windows["L3"], windows["SEASON"]
    shots_r, shots_s = _value(recent, "shots"), _value(season, "shots")
    raw = {
        "xgi_per90_ratio": (
            _ratio(_per90(recent, "xgi"), _per90(season, "xgi")),
            ("L3.xgi_per90", "SEASON.xgi_per90"),
        ),
        "xg_per90_ratio": (
            _ratio(_per90(recent, "xg"), _per90(season, "xg")),
            ("L3.xg_per90", "SEASON.xg_per90"),
        ),
        "xa_per90_ratio": (
            _ratio(_per90(recent, "xa"), _per90(season, "xa")),
            ("L3.xa_per90", "SEASON.xa_per90"),
        ),
        "shots_per90_ratio": (
            _ratio(_per90(recent, "shots"), _per90(season, "shots")),
            ("L3.shots_per90", "SEASON.shots_per90"),
        ),
        "shots_in_box_per90_ratio": (
            _ratio(
                _per90(recent, "shots_in_box"),
                _per90(season, "shots_in_box"),
            ),
            ("L3.shots_in_box_per90", "SEASON.shots_in_box_per90"),
        ),
        "shot_quality_ratio": (
            _ratio(
                _rate(_value(recent, "xg"), shots_r),
                _rate(_value(season, "xg"), shots_s),
            ),
            ("L3.xg", "L3.shots", "SEASON.xg", "SEASON.shots"),
        ),
        "sot_rate_ratio": (
            _ratio(
                _rate(_value(recent, "shots_on_target"), shots_r),
                _rate(_value(season, "shots_on_target"), shots_s),
            ),
            (
                "L3.shots_on_target",
                "L3.shots",
                "SEASON.shots_on_target",
                "SEASON.shots",
            ),
        ),
        "box_touches_per90_ratio": (
            _ratio(
                _per90(recent, "box_touches"),
                _per90(season, "box_touches"),
            ),
            ("L3.box_touches_per90", "SEASON.box_touches_per90"),
        ),
        "key_passes_per90_ratio": (
            _ratio(
                _per90(recent, "key_passes"),
                _per90(season, "key_passes"),
            ),
            ("L3.key_passes_per90", "SEASON.key_passes_per90"),
        ),
        "chances_created_per90_ratio": (
            _ratio(
                _per90(recent, "chances_created"),
                _per90(season, "chances_created"),
            ),
            (
                "L3.chances_created_per90",
                "SEASON.chances_created_per90",
            ),
        ),
        "start_share_delta": (
            _delta(
                _derived_value(recent, "start_share"),
                _derived_value(season, "start_share"),
            ),
            ("L3.start_share", "SEASON.start_share"),
        ),
        "minutes_per_appearance_ratio": (
            _ratio(
                _derived_value(recent, "minutes_per_appearance"),
                _derived_value(season, "minutes_per_appearance"),
            ),
            (
                "L3.minutes_per_appearance",
                "SEASON.minutes_per_appearance",
            ),
        ),
    }
    return {
        key: _node(
            value,
            recent=recent,
            season=season,
            metric_name=key,
            definition=(
                "sample-aware L3 versus season trajectory component: "
                f"{key}"
            ),
            inputs=inputs,
        )
        for key, (value, inputs) in raw.items()
    }


def _component(
    components: Mapping[str, Any],
    key: str,
) -> float | None:
    return as_float((components.get(key) or {}).get("value"))


def _signals(
    windows: Mapping[str, Any],
    regression: Mapping[str, Any],
) -> dict[str, Any]:
    recent, season = windows["L3"], windows["SEASON"]
    rc = as_float((recent.get("confidence") or {}).get("score")) or 0.0
    sc = as_float((season.get("confidence") or {}).get("score")) or 0.0
    components = _trajectory(windows)
    eligible = (
        int(recent.get("sample_matches") or 0) >= 2
        and (as_float(recent.get("sample_minutes")) or 0) >= 180
        and int(season.get("sample_matches") or 0) >= 3
        and (as_float(season.get("sample_minutes")) or 0) >= 270
        and rc >= 0.3
        and sc >= 0.45
    )
    gap = as_float(
        ((regression.get("L3") or {}).get("gi_minus_xgi") or {}).get("per90")
    )
    xgi = _component(components, "xgi_per90_ratio")
    minutes = _component(components, "minutes_per_appearance_ratio")
    starts = _component(components, "start_share_delta")
    support = [
        _component(components, key)
        for key in (
            "xg_per90_ratio",
            "xa_per90_ratio",
            "shots_per90_ratio",
            "shots_in_box_per90_ratio",
            "box_touches_per90_ratio",
            "key_passes_per90_ratio",
            "chances_created_per90_ratio",
        )
    ]
    up = sum(value is not None and value >= 1.15 for value in support)
    down = sum(value is not None and value <= 0.8 for value in support)
    states = {
        "POSITIVE_REGRESSION_WATCH": (
            eligible
            and gap is not None
            and gap <= -0.25
            and xgi is not None
            and xgi >= 0.85
            and (minutes is None or minutes >= 0.85),
            [
                "recent GI trails xGI materially",
                "opportunity remains close to or above season baseline",
                "no rebound is guaranteed",
            ],
        ),
        "NEGATIVE_REGRESSION_WATCH": (
            eligible
            and gap is not None
            and gap >= 0.25
            and xgi is not None
            and xgi <= 1.15,
            [
                "recent GI exceeds xGI materially",
                "underlying is not materially above season baseline",
                "future underperformance is not asserted",
            ],
        ),
        "BREAKOUT": (
            eligible
            and xgi is not None
            and xgi >= 1.25
            and up >= 1
            and (minutes is None or minutes >= 0.9)
            and (starts is None or starts >= -0.2),
            [
                "recent xGI rate materially improved",
                "supporting opportunity/involvement also improved",
                "minutes/start security is not materially worse",
            ],
        ),
        "ROLE_DECLINE": (
            eligible
            and (
                (minutes is not None and minutes <= 0.75)
                or (starts is not None and starts <= -0.25)
            )
            and ((xgi is not None and xgi <= 0.8) or down >= 1),
            [
                "recent minutes/start security declined materially",
                "recent underlying involvement also declined where measurable",
            ],
        ),
    }
    provenance = combine_window_provenance(
        (recent, season),
        metric_name="trajectory_signal",
        metric_definition=(
            "sample-aware advisory trajectory/regression classification"
        ),
        output_window="L3_VS_SEASON",
        availability="AVAILABLE" if eligible else "INSUFFICIENT_SAMPLE",
        inputs=("L3", "SEASON", "regression", "trajectory_components"),
    )
    out = {
        key: {
            "active": bool(active),
            "confidence": round(min(rc, sc), 4) if eligible else 0.0,
            "sample_eligible": eligible,
            "reasons": reasons if active else [],
            "provenance": dict(provenance),
        }
        for key, (active, reasons) in states.items()
    }
    out["trajectory_components"] = components
    out["sample_eligibility"] = {
        "eligible": eligible,
        "recent_confidence": rc,
        "season_confidence": sc,
        "minimum_recent_matches": 2,
        "minimum_recent_minutes": 180.0,
        "minimum_season_matches": 3,
        "minimum_season_minutes": 270.0,
    }
    return out


def build_player_multiwindow_form(
    rows: Sequence[Mapping[str, Any]],
    *,
    player_id: int | str | None = None,
    season: str | None = None,
) -> dict[str, Any]:
    guard = provider_guard(rows)
    played, excluded = _played_rows(rows)
    if not guard["aggregation_allowed"]:
        return {
            "contract": "V12_MULTIWINDOW_PLAYER_FORM_V1",
            "player_id": player_id,
            "status": str(guard.get("status") or "PROVIDER_INVALID"),
            "provider_guard": guard,
            "excluded_zero_or_missing_minute_rows": excluded,
            "windows": {},
            "comparisons": {},
            "regression": {},
            "signals": {},
        }
    windows = {
        name: _window_payload(
            _window_rows(played, name),
            name,
            season,
        )
        for name in WINDOWS
    }
    regression = {
        name: _regression(window)
        for name, window in windows.items()
    }
    return {
        "contract": "V12_MULTIWINDOW_PLAYER_FORM_V1",
        "player_id": player_id,
        "status": "AVAILABLE" if played else "NO_APPEARANCES",
        "provider_guard": guard,
        "excluded_zero_or_missing_minute_rows": excluded,
        "windows": windows,
        "comparisons": _comparisons(windows),
        "regression": regression,
        "signals": _signals(windows, regression),
        "governance": {
            "same_provider_longitudinal_only": True,
            "cross_provider_averaging_forbidden": True,
            "cross_provider_use": (
                "TRIANGULATION_OR_QA_ONLY_UNLESS_EXPLICIT_NORMALIZATION_EXISTS"
            ),
            "missing_metric_zero_fill_forbidden": True,
            "zero_minute_nonappearance_excluded_from_rolling_windows": True,
            "advisory_only_no_decision_weight_change": True,
        },
    }


def build_multiwindow_form_snapshot(
    rows: Sequence[Mapping[str, Any]],
    *,
    season: str | None = None,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        player_id = (
            raw.get("player_id")
            or raw.get("element")
            or raw.get("official_element_id")
        )
        if player_id is not None:
            grouped[str(player_id)].append(dict(raw))
    players = {
        player_id: build_player_multiwindow_form(
            player_rows,
            player_id=player_id,
            season=season,
        )
        for player_id, player_rows in sorted(grouped.items())
    }
    return {
        "contract": "V12_MULTIWINDOW_FORM_SNAPSHOT_V1",
        "player_count": len(players),
        "players": players,
        "governance": {
            "decision_math_changed": False,
            "recommendation_changed": False,
            "captaincy_changed": False,
            "feature_layer": "ANALYTICAL_EVIDENCE_ONLY",
            "same_provider_longitudinal_only": True,
            "cross_provider_averaging_forbidden": True,
        },
    }
