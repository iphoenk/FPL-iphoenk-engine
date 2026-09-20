from __future__ import annotations

"""V12-native contextual player dynamics.

This module is a derived methodology layer over existing V6 factual rows. It
does not acquire data, own a scheduler, replace P1.1/P1.3 Bayesian machinery,
or create player-specific parameters. It supplies bounded, evidence-derived
trajectory, opponent-matchup and teammate-dependency modifiers for the existing
V12 event projection path.
"""

from collections import Counter
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "v12_contextual_dynamics.json"
MODEL_OWNER = "V12_CONTEXTUAL_DYNAMICS"
MODEL_ID = "v12_gw1_matchup_linkup_dynamics_v1"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value in {None, ""} else value)
    except (TypeError, ValueError):
        return float(default)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(default if value in {None, ""} else value))
    except (TypeError, ValueError):
        return int(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "V12_CONTEXTUAL_DYNAMICS_V1":
        raise RuntimeError("V12 contextual dynamics contract drift")
    return payload


def data_capability_audit() -> dict[str, str]:
    """Canonical availability proven by existing V6/owner code paths."""
    return {
        "match_id": "AVAILABLE",
        "gw": "PARTIAL",
        "opponent": "AVAILABLE_DERIVED_WHEN_TWO_TEAMS_IDENTIFIABLE",
        "home_away": "PARTIAL",
        "minutes": "AVAILABLE",
        "starter_substitute": "AVAILABLE",
        "substitution_timing": "PARTIAL",
        "actual_role_position": "PARTIAL",
        "xg": "AVAILABLE",
        "xa": "AVAILABLE",
        "xgi": "DERIVED_AVAILABLE",
        "shots": "AVAILABLE",
        "shots_on_target": "AVAILABLE",
        "big_chances": "PARTIAL",
        "touches": "AVAILABLE",
        "touches_opposition_box": "AVAILABLE",
        "key_passes": "UNAVAILABLE",
        "chances_created": "AVAILABLE",
        "progressive_passes_receptions": "PARTIAL",
        "crosses": "AVAILABLE",
        "cutbacks": "UNAVAILABLE",
        "set_piece_involvement": "AVAILABLE",
        "penalty_involvement": "AVAILABLE",
        "defensive_contribution": "AVAILABLE",
        "fpl_points": "AVAILABLE",
        "score_game_state": "PARTIAL",
        "team_attacking_metrics": "AVAILABLE",
        "availability_injury_suspension": "AVAILABLE",
        "lineup_teammate_presence": "AVAILABLE",
        "direct_player_to_player_passes": "UNAVAILABLE",
        "direct_chance_recipient": "UNAVAILABLE",
        "heatmap_true_position": "UNAVAILABLE",
    }


def _gw(row: Mapping[str, Any]) -> int:
    return _i(
        row.get("gw"),
        _i(
            row.get("event"),
            _i(row.get("gameweek"), _i(row.get("round"), 0)),
        ),
    )


def _match_id(row: Mapping[str, Any]) -> str:
    return str(row.get("match_id") or row.get("fixture") or row.get("id") or "")


def enrich_match_rows(
    match_rows: Sequence[Mapping[str, Any]],
    *,
    player_team: Mapping[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Derive only identities that are provable from the existing row set."""
    team_map = {int(k): int(v) for k, v in dict(player_team or {}).items()}
    prepared: list[dict[str, Any]] = []
    teams_by_match: dict[str, set[int]] = {}
    for raw in match_rows:
        row = dict(raw)
        player_id = _i(row.get("player_id"), _i(row.get("element"), -1))
        team_id = _i(row.get("team_id"), team_map.get(player_id, -1))
        if team_id > 0:
            row["team_id"] = team_id
        gw = _gw(row)
        if gw > 0:
            row["gw"] = gw
        match_id = _match_id(row)
        if match_id and team_id > 0:
            teams_by_match.setdefault(match_id, set()).add(team_id)
        prepared.append(row)

    for row in prepared:
        match_id = _match_id(row)
        team_id = _i(row.get("team_id"), -1)
        if (
            row.get("opponent_team_id") is None
            and match_id
            and team_id > 0
        ):
            candidates = teams_by_match.get(match_id) or set()
            others = sorted(candidates - {team_id})
            if len(others) == 1:
                row["opponent_team_id"] = others[0]
        if row.get("home") is None and row.get("is_home") is not None:
            row["home"] = bool(row.get("is_home"))
    return prepared


def _minutes(row: Mapping[str, Any]) -> float:
    return max(0.0, _f(row.get("minutes_played"), _f(row.get("minutes"))))


def _starter(row: Mapping[str, Any]) -> bool:
    if row.get("started") is not None:
        return bool(row.get("started"))
    return _i(row.get("start_min"), -1) == 0


def _metric(row: Mapping[str, Any], name: str) -> float:
    aliases = {
        "xg": ("xg", "expected_goals"),
        "xa": ("xa", "expected_assists"),
        "shots": ("total_shots", "shots"),
        "sot": ("shots_on_target", "sot"),
        "box_touches": ("touches_opposition_box", "box_touches"),
        "chances_created": ("chances_created",),
        "big_chances": ("big_chances",),
        "touches": ("touches",),
        "final_third_passes": ("final_third_passes",),
        "accurate_crosses": ("accurate_crosses", "crosses"),
        "defensive": (
            "defensive_contributions",
            "defensive_contribution",
            "dc_reconstructed",
        ),
        "goals": ("goals_scored", "goals"),
        "assists": ("assists",),
        "fpl_points": ("total_points", "fpl_points", "points"),
    }
    for key in aliases.get(name, (name,)):
        if row.get(key) is not None:
            return max(0.0, _f(row.get(key)))
    if name == "xgi":
        return _metric(row, "xg") + _metric(row, "xa")
    return 0.0


def _rate90(rows: Sequence[Mapping[str, Any]], metric: str, weights: Sequence[float] | None = None) -> float | None:
    if not rows:
        return None
    use_weights = list(weights or [1.0] * len(rows))
    weighted_minutes = sum(_minutes(row) * weight for row, weight in zip(rows, use_weights))
    if weighted_minutes <= 0.0:
        return None
    total = sum(_metric(row, metric) * weight for row, weight in zip(rows, use_weights))
    return 90.0 * total / weighted_minutes


def _recency_weights(rows: Sequence[Mapping[str, Any]], current_gw: int) -> list[float]:
    half_life = max(0.25, _f((load_config().get("recency") or {}).get("half_life_gws"), 2.5))
    out = []
    for row in rows:
        age = max(0, current_gw - max(1, _gw(row)))
        out.append(0.5 ** (age / half_life))
    return out


def _posterior_recent_rate(
    rows: Sequence[Mapping[str, Any]],
    metric: str,
    current_gw: int,
) -> dict[str, Any]:
    if not rows:
        return {"season_rate90": None, "weighted_rate90": None, "posterior_rate90": None, "effective_sample": 0.0}
    weights = _recency_weights(rows, current_gw)
    season = _rate90(rows, metric)
    weighted = _rate90(rows, metric, weights)
    effective_sample = sum(weights)
    shrink = max(
        0.0,
        _f(
            (load_config().get("recency") or {}).get("posterior_shrinkage_equivalent_matches"),
            4.0,
        ),
    )
    if season is None or weighted is None:
        posterior = season if weighted is None else weighted
    else:
        posterior = (weighted * effective_sample + season * shrink) / max(1e-9, effective_sample + shrink)
    return {
        "season_rate90": None if season is None else round(season, 6),
        "weighted_rate90": None if weighted is None else round(weighted, 6),
        "posterior_rate90": None if posterior is None else round(posterior, 6),
        "effective_sample": round(effective_sample, 6),
        "raw_match_count": len(rows),
    }


def _role_label(row: Mapping[str, Any]) -> str | None:
    value = row.get("actual_role") or row.get("role") or row.get("position")
    text = str(value or "").strip().upper()
    return text or None


def _result_vs_process(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    minutes = sum(_minutes(row) for row in rows)
    goals = sum(_metric(row, "goals") for row in rows)
    assists = sum(_metric(row, "assists") for row in rows)
    xg = sum(_metric(row, "xg") for row in rows)
    xa = sum(_metric(row, "xa") for row in rows)
    actual = goals + assists
    process = xg + xa
    if minutes <= 0:
        label = "INSUFFICIENT_PROCESS_EVIDENCE"
    elif process >= 0.8 and actual <= max(0.0, process * 0.45):
        label = "OUTPUT_BELOW_PROCESS"
    elif actual >= 2.0 and process <= max(0.35, actual * 0.45):
        label = "OUTPUT_ABOVE_PROCESS"
    elif process <= 0.2 and actual <= 0:
        label = "LOW_PROCESS_LOW_RESULT"
    else:
        label = "RESULT_PROCESS_BROADLY_ALIGNED"
    return {
        "result_evidence": {
            "goals": round(goals, 4),
            "assists": round(assists, 4),
            "returns": round(actual, 4),
        },
        "process_evidence": {
            "minutes": round(minutes, 1),
            "xg": round(xg, 4),
            "xa": round(xa, 4),
            "xgi": round(process, 4),
            "shots": round(sum(_metric(row, "shots") for row in rows), 4),
            "shots_on_target": round(sum(_metric(row, "sot") for row in rows), 4),
            "box_touches": round(sum(_metric(row, "box_touches") for row in rows), 4),
            "chances_created": round(sum(_metric(row, "chances_created") for row in rows), 4),
        },
        "interpretation": label,
    }


def build_player_trajectory(
    match_rows: Sequence[Mapping[str, Any]],
    *,
    player_id: int,
    current_gw: int,
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in match_rows
        if _i(row.get("player_id"), _i(row.get("element"), -1)) == int(player_id)
        and 1 <= _gw(row) <= int(current_gw)
        and _minutes(row) >= 0
    ]
    rows.sort(key=lambda row: (_gw(row), _match_id(row)))
    recency_cfg = load_config().get("recency") or {}
    recent_n = max(1, _i(recency_cfg.get("recent_window_matches"), 3))
    recent = rows[-recent_n:]
    rate_metrics = ("xg", "xa", "xgi", "shots", "sot", "box_touches", "chances_created")
    rates = {metric: _posterior_recent_rate(rows, metric, current_gw) for metric in rate_metrics}
    xgi = rates["xgi"]
    season = xgi.get("season_rate90")
    posterior = xgi.get("posterior_rate90")
    trend_ratio = None
    if season is not None and posterior is not None and season > 1e-9:
        trend_ratio = posterior / season
    threshold = max(0.01, _f(recency_cfg.get("trend_ratio_threshold"), 0.18))

    starter_recent = sum(1 for row in recent if _starter(row))
    starter_prior_rows = rows[:-len(recent)] if len(rows) > len(recent) else []
    starter_prior_rate = (
        sum(1 for row in starter_prior_rows if _starter(row)) / len(starter_prior_rows)
        if starter_prior_rows
        else None
    )
    starter_recent_rate = starter_recent / len(recent) if recent else 0.0
    recent_roles = [_role_label(row) for row in recent if _role_label(row)]
    prior_roles = [_role_label(row) for row in starter_prior_rows if _role_label(row)]
    recent_role = Counter(recent_roles).most_common(1)[0][0] if recent_roles else None
    prior_role = Counter(prior_roles).most_common(1)[0][0] if prior_roles else None
    role_change_min = max(2, _i(recency_cfg.get("role_change_min_matches"), 2))
    sustained_role_change = bool(
        recent_role
        and prior_role
        and recent_role != prior_role
        and recent_roles.count(recent_role) >= min(role_change_min, len(recent_roles))
    )

    if sustained_role_change:
        classification = "ROLE_TRANSITION"
    elif starter_prior_rate is not None and starter_recent_rate - starter_prior_rate >= 0.35:
        classification = "MINUTES_ROLE_IMPROVING"
    elif starter_prior_rate is not None and starter_prior_rate - starter_recent_rate >= 0.35:
        classification = "MINUTES_ROLE_DECLINING"
    elif trend_ratio is not None and trend_ratio >= 1.0 + threshold:
        classification = "IMPROVING"
    elif trend_ratio is not None and trend_ratio <= 1.0 - threshold:
        classification = "DECLINING"
    else:
        classification = "STABLE_OR_NOISY"

    match_by_match = []
    for row in rows:
        minutes = _minutes(row)
        match_by_match.append(
            {
                "gw": _gw(row),
                "match_id": _match_id(row),
                "opponent_team_id": row.get("opponent_team_id") or row.get("opponent"),
                "home": row.get("home") if row.get("home") is not None else row.get("is_home"),
                "minutes": round(minutes, 1),
                "starter": _starter(row),
                "role": _role_label(row),
                "xg": round(_metric(row, "xg"), 4),
                "xa": round(_metric(row, "xa"), 4),
                "xgi": round(_metric(row, "xgi"), 4),
                "goals": round(_metric(row, "goals"), 4),
                "assists": round(_metric(row, "assists"), 4),
                "returns": round(
                    _metric(row, "goals") + _metric(row, "assists"), 4
                ),
                "shots": round(_metric(row, "shots"), 4),
                "shots_on_target": round(_metric(row, "sot"), 4),
                "big_chances": round(_metric(row, "big_chances"), 4),
                "touches": round(_metric(row, "touches"), 4),
                "box_touches": round(_metric(row, "box_touches"), 4),
                "chances_created": round(_metric(row, "chances_created"), 4),
                "set_piece_involvement": round(_metric(row, "corners"), 4),
                "penalty_involvement": round(
                    _metric(row, "penalties_scored") + _metric(row, "penalties_missed"),
                    4,
                ),
                "defensive_contribution": round(_metric(row, "defensive"), 4),
                "fpl_points": round(_metric(row, "fpl_points"), 4),
            }
        )

    return {
        "model": MODEL_ID,
        "player_id": int(player_id),
        "from_gw": 1,
        "to_gw": int(current_gw),
        "matches": match_by_match,
        "sample_size": len(rows),
        "recency_weighting": "EXPONENTIAL_HALF_LIFE_GW",
        "rates": rates,
        "latest_match_evidence": match_by_match[-1] if match_by_match else None,
        "role_minutes_evolution": {
            "recent_start_rate": round(starter_recent_rate, 6),
            "prior_start_rate": None if starter_prior_rate is None else round(starter_prior_rate, 6),
            "recent_role": recent_role,
            "prior_role": prior_role,
            "sustained_role_change": sustained_role_change,
        },
        "trajectory_classification": classification,
        "result_vs_process": _result_vs_process(rows),
    }


POST_MATCH_EVIDENCE_CLASSES = frozenset(
    {
        "BREAKOUT_PROCESS",
        "ROLE_BREAKOUT",
        "MINUTES_BREAKOUT",
        "LINKUP_BREAKOUT",
        "SET_PIECE_GAIN",
        "UNDERLYING_IMPROVING_NO_RETURN",
        "OUTPUT_CONFIRMING_PROCESS",
        "OUTPUT_WITHOUT_PROCESS",
        "REGRESSION_RISK",
        "ROLE_DECLINE",
        "MINUTES_DECLINE",
        "LINKUP_BROKEN",
        "NO_MATERIAL_CHANGE",
    }
)


def _match_metric_rate90(
    rows: Sequence[Mapping[str, Any]],
    metric: str,
) -> float | None:
    minutes = sum(max(0.0, _f(row.get("minutes"))) for row in rows)
    if minutes <= 0.0:
        return None
    return 90.0 * sum(_f(row.get(metric)) for row in rows) / minutes


def _safe_ratio(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior <= 1e-9:
        return None
    return current / prior


def _projection_map(
    rows: Sequence[Mapping[str, Any]] | None,
) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        element = _i(row.get("element"), _i(row.get("element_id"), -1))
        if element > 0:
            out[element] = dict(row)
    return out


def _projection_xmins(row: Mapping[str, Any] | None) -> tuple[float | None, float | None]:
    payload = dict((row or {}).get("xmins") or {})
    expected = payload.get("expected_minutes")
    p_start = payload.get("start_probability")
    return (
        None if expected is None else _f(expected),
        None if p_start is None else _f(p_start),
    )


def _linkup_snapshot(row: Mapping[str, Any] | None) -> dict[str, Any]:
    contexts = (
        ((row or {}).get("contextual_dynamics") or {}).get("fixture_contexts")
        or []
    )
    context = next(
        (dict(item) for item in contexts if isinstance(item, Mapping)),
        {},
    )
    network = dict(context.get("linkup_network") or {})
    relationships = [
        dict(item)
        for item in network.get("relationships") or []
        if isinstance(item, Mapping)
        and _f(item.get("confidence")) > 0.0
    ]
    edge_ids = sorted(
        {
            _edge_id(item)
            for item in relationships
            if _i(
                item.get("source_player_id"),
                _i(item.get("teammate_player_id"), -1),
            )
            > 0
            and _i(item.get("target_player_id"), -1) > 0
        }
    )
    multipliers = dict(context.get("event_multipliers") or {})
    goal = _f(
        multipliers.get(
            "final_dependency_goal",
            multipliers.get("linkup_goal"),
        ),
        1.0,
    )
    assist = _f(
        multipliers.get(
            "final_dependency_assist",
            multipliers.get("linkup_assist"),
        ),
        1.0,
    )
    score = math.sqrt(max(0.01, goal) * max(0.01, assist))
    return {
        "relationship_count": len(relationships),
        "edge_ids": edge_ids,
        "dependency_score": round(score, 6),
        "goal_multiplier": round(goal, 6),
        "assist_multiplier": round(assist, 6),
    }


def _monotonic_process_improving(
    rows: Sequence[Mapping[str, Any]],
) -> bool:
    played = [row for row in rows if _f(row.get("minutes")) > 0.0]
    if len(played) < 3:
        return False
    tail = played[-4:]
    values = []
    for row in tail:
        minutes = max(1.0, _f(row.get("minutes")))
        values.append(90.0 * _f(row.get("xgi")) / minutes)
    increases = sum(
        1 for left, right in zip(values, values[1:]) if right > left + 1e-9
    )
    return increases >= max(2, len(values) - 2) and values[-1] > values[0]


def build_post_match_universe_scan(
    *,
    current_projection_players: Sequence[Mapping[str, Any]],
    previous_projection_players: Sequence[Mapping[str, Any]] | None,
    player_match_rows: Sequence[Mapping[str, Any]],
    current_gw: int,
    owned_element_ids: Sequence[int] | None = None,
    price_risk_by_player: Mapping[int, bool] | None = None,
    fixture_swing_by_player: Mapping[int, bool] | None = None,
) -> dict[str, Any]:
    """Cheap full-universe post-match evidence scan before deep reporting.

    This is evidence classification only. It never creates WAIT/PREPARE/ACT
    and it never replaces the existing full-universe optimizer/comparator.
    """
    cfg = load_config().get("post_match_scan") or {}
    recent_n = max(2, _i(cfg.get("recent_window_matches"), 3))
    min_matches = max(1, _i(cfg.get("minimum_trajectory_matches"), 2))
    xgi_threshold = max(1.0, _f(cfg.get("xgi_trend_ratio"), 1.18))
    box_threshold = max(1.0, _f(cfg.get("box_touch_trend_ratio"), 1.20))
    shot_threshold = max(1.0, _f(cfg.get("shots_trend_ratio"), 1.15))
    xmins_up = _f(cfg.get("xmins_breakout_delta"), 15.0)
    pstart_up = _f(cfg.get("pstart_breakout_delta"), 0.15)
    xmins_down = _f(cfg.get("xmins_decline_delta"), -15.0)
    pstart_down = _f(cfg.get("pstart_decline_delta"), -0.15)
    strong_latest_xgi = _f(cfg.get("strong_latest_xgi"), 0.55)
    weak_latest_xgi = _f(cfg.get("weak_latest_xgi"), 0.20)
    spike_returns = max(1, _i(cfg.get("output_spike_return_count"), 2))
    spike_points = max(1.0, _f(cfg.get("output_spike_fpl_points"), 10.0))
    link_delta_threshold = max(
        0.0, _f(cfg.get("linkup_material_delta"), 0.05)
    )
    set_piece_min = max(
        0.0, _f(cfg.get("set_piece_gain_min_latest"), 1.0)
    )
    material_min = max(
        0.0, _f(cfg.get("materiality_min_score"), 1.0)
    )
    class_priority = [
        str(value)
        for value in cfg.get("class_priority") or []
        if str(value) in POST_MATCH_EVIDENCE_CLASSES
    ]

    current_map = _projection_map(current_projection_players)
    previous_map = _projection_map(previous_projection_players)
    owned = {int(value) for value in owned_element_ids or []}
    price_flags = {
        int(key): bool(value)
        for key, value in dict(price_risk_by_player or {}).items()
    }
    fixture_flags = {
        int(key): bool(value)
        for key, value in dict(fixture_swing_by_player or {}).items()
    }
    match_rows_by_player: dict[int, list[dict[str, Any]]] = {}
    for raw in player_match_rows:
        if not isinstance(raw, Mapping):
            continue
        element = _i(raw.get("player_id"), _i(raw.get("element"), -1))
        if element > 0:
            match_rows_by_player.setdefault(element, []).append(dict(raw))

    scanned: list[dict[str, Any]] = []
    for element, projection in sorted(current_map.items()):
        position = str(projection.get("position") or "").upper()
        if position not in {"GK", "DEF", "MID", "FWD"}:
            continue
        if str(projection.get("status") or "").lower() == "u":
            continue

        trajectory = build_player_trajectory(
            match_rows_by_player.get(element, []),
            player_id=element,
            current_gw=current_gw,
        )
        matches = [
            dict(row)
            for row in trajectory.get("matches") or []
            if _f(row.get("minutes")) > 0.0
        ]
        recent = matches[-recent_n:]
        prior = matches[:-recent_n] if len(matches) > recent_n else matches[:-1]
        latest = matches[-1] if matches else {}

        recent_xgi90 = _match_metric_rate90(recent, "xgi")
        prior_xgi90 = _match_metric_rate90(prior, "xgi")
        recent_box90 = _match_metric_rate90(recent, "box_touches")
        prior_box90 = _match_metric_rate90(prior, "box_touches")
        recent_shots90 = _match_metric_rate90(recent, "shots")
        prior_shots90 = _match_metric_rate90(prior, "shots")
        xgi_ratio = _safe_ratio(recent_xgi90, prior_xgi90)
        box_ratio = _safe_ratio(recent_box90, prior_box90)
        shots_ratio = _safe_ratio(recent_shots90, prior_shots90)

        current_xmins, current_pstart = _projection_xmins(projection)
        previous_projection = previous_map.get(element) or {}
        previous_xmins, previous_pstart = _projection_xmins(
            previous_projection
        )
        xmins_delta = (
            None
            if current_xmins is None or previous_xmins is None
            else current_xmins - previous_xmins
        )
        pstart_delta = (
            None
            if current_pstart is None or previous_pstart is None
            else current_pstart - previous_pstart
        )

        role = dict(trajectory.get("role_minutes_evolution") or {})
        trajectory_class = str(
            trajectory.get("trajectory_classification") or ""
        )
        latest_returns = _f(latest.get("returns"))
        latest_points = _f(latest.get("fpl_points"))
        latest_xgi = _f(latest.get("xgi"))
        recent_returns = sum(_f(row.get("returns")) for row in recent)
        prior_process_strong = (
            prior_xgi90 is not None and prior_xgi90 >= 0.30
        )
        sustained_process = (
            _monotonic_process_improving(matches)
            or trajectory_class == "IMPROVING"
            or (
                xgi_ratio is not None
                and xgi_ratio >= xgi_threshold
                and len(recent) >= 2
                and sum(1 for row in recent if _f(row.get("xgi")) >= 0.25)
                >= 2
            )
        )

        current_link = _linkup_snapshot(projection)
        previous_link = _linkup_snapshot(previous_projection)
        link_delta = (
            _f(current_link.get("dependency_score"), 1.0)
            - _f(previous_link.get("dependency_score"), 1.0)
        )
        new_links = sorted(
            set(current_link.get("edge_ids") or [])
            - set(previous_link.get("edge_ids") or [])
        )
        lost_links = sorted(
            set(previous_link.get("edge_ids") or [])
            - set(current_link.get("edge_ids") or [])
        )

        classes: list[str] = []
        if sustained_process and len(matches) >= min_matches:
            classes.append("BREAKOUT_PROCESS")

        if role.get("sustained_role_change"):
            decline_context = (
                (xmins_delta is not None and xmins_delta <= xmins_down)
                or (pstart_delta is not None and pstart_delta <= pstart_down)
                or trajectory_class == "DECLINING"
            )
            classes.append(
                "ROLE_DECLINE" if decline_context else "ROLE_BREAKOUT"
            )

        if (
            (xmins_delta is not None and xmins_delta >= xmins_up)
            or (pstart_delta is not None and pstart_delta >= pstart_up)
            or trajectory_class == "MINUTES_ROLE_IMPROVING"
        ):
            classes.append("MINUTES_BREAKOUT")
        if (
            (xmins_delta is not None and xmins_delta <= xmins_down)
            or (pstart_delta is not None and pstart_delta <= pstart_down)
            or trajectory_class == "MINUTES_ROLE_DECLINING"
        ):
            classes.append("MINUTES_DECLINE")

        latest_set_piece = _f(latest.get("set_piece_involvement"))
        prior_set_piece = (
            sum(_f(row.get("set_piece_involvement")) for row in prior)
            / len(prior)
            if prior
            else 0.0
        )
        if (
            latest_set_piece >= set_piece_min
            and latest_set_piece > prior_set_piece + 0.5
        ):
            classes.append("SET_PIECE_GAIN")

        if (
            new_links
            or (
                previous_link.get("relationship_count", 0) > 0
                and link_delta >= link_delta_threshold
            )
        ):
            classes.append("LINKUP_BREAKOUT")
        if (
            lost_links
            or (
                previous_link.get("relationship_count", 0) > 0
                and link_delta <= -link_delta_threshold
            )
        ):
            classes.append("LINKUP_BROKEN")

        haul = (
            latest_returns >= spike_returns
            or latest_points >= spike_points
        )
        pre_latest_rows = matches[:-1][-4:]
        pre_latest_xgi90 = _match_metric_rate90(
            pre_latest_rows, "xgi"
        )
        poor_prior_process = (
            pre_latest_xgi90 is not None
            and pre_latest_xgi90 <= weak_latest_xgi
            and not sustained_process
        )
        declining_context = (
            trajectory_class in {"DECLINING", "MINUTES_ROLE_DECLINING"}
            or "ROLE_DECLINE" in classes
            or "MINUTES_DECLINE" in classes
        )
        if haul:
            if sustained_process and not poor_prior_process:
                classes.append("OUTPUT_CONFIRMING_PROCESS")
            elif (
                poor_prior_process
                or latest_xgi <= weak_latest_xgi
                or declining_context
            ):
                classes.extend(
                    ["OUTPUT_WITHOUT_PROCESS", "REGRESSION_RISK"]
                )
        elif (
            latest_returns > 0
            and latest_xgi <= weak_latest_xgi
            and declining_context
        ):
            classes.extend(["OUTPUT_WITHOUT_PROCESS", "REGRESSION_RISK"])

        process_up = (
            (
                xgi_ratio is not None and xgi_ratio >= xgi_threshold
            )
            or (
                box_ratio is not None and box_ratio >= box_threshold
            )
            or (
                shots_ratio is not None and shots_ratio >= shot_threshold
            )
            or latest_xgi >= strong_latest_xgi
        )
        if (
            recent
            and recent_returns <= 0.0
            and process_up
            and (
                "MINUTES_BREAKOUT" in classes
                or sustained_process
                or (
                    current_pstart is not None
                    and current_pstart >= 0.65
                )
            )
        ):
            classes.append("UNDERLYING_IMPROVING_NO_RETURN")

        # Preserve deterministic order and remove duplicate labels.
        classes = list(dict.fromkeys(classes))
        materiality_reasons = list(classes)
        if element in owned:
            materiality_reasons.append("OUR15_RELEVANCE")
        if price_flags.get(element):
            materiality_reasons.append("PRICE_RISK")
        if fixture_flags.get(element):
            materiality_reasons.append("FIXTURE_SWING")

        materiality_score = float(
            len([value for value in classes if value != "NO_MATERIAL_CHANGE"])
        )
        materiality_score += 1.0 if element in owned else 0.0
        materiality_score += 1.0 if price_flags.get(element) else 0.0
        materiality_score += 1.0 if fixture_flags.get(element) else 0.0
        deep_required = materiality_score >= material_min

        if not classes:
            classes = ["NO_MATERIAL_CHANGE"]
        primary = next(
            (value for value in class_priority if value in classes),
            classes[0],
        )

        posterior_xgi90 = (
            ((trajectory.get("rates") or {}).get("xgi") or {}).get(
                "posterior_rate90"
            )
        )
        previous_event_rate = (
            _f((previous_projection.get("rates") or {}).get("xg90"))
            + _f((previous_projection.get("rates") or {}).get("xa90"))
            if previous_projection
            else None
        )
        scanned.append(
            {
                "element_id": element,
                "name": projection.get("name"),
                "team_id": projection.get("team_id"),
                "position": position,
                "now_cost": projection.get("now_cost"),
                "owned": element in owned,
                "sample_size": trajectory.get("sample_size"),
                "trajectory_classification": trajectory_class,
                "latest_match": latest or None,
                "role_trajectory": role,
                "xmins": {
                    "current": None
                    if current_xmins is None
                    else round(current_xmins, 3),
                    "previous": None
                    if previous_xmins is None
                    else round(previous_xmins, 3),
                    "delta": None
                    if xmins_delta is None
                    else round(xmins_delta, 3),
                },
                "p_start": {
                    "current": None
                    if current_pstart is None
                    else round(current_pstart, 6),
                    "previous": None
                    if previous_pstart is None
                    else round(previous_pstart, 6),
                    "delta": None
                    if pstart_delta is None
                    else round(pstart_delta, 6),
                },
                "process_trend": {
                    "recent_xgi90": None
                    if recent_xgi90 is None
                    else round(recent_xgi90, 6),
                    "prior_xgi90": None
                    if prior_xgi90 is None
                    else round(prior_xgi90, 6),
                    "xgi_ratio": None
                    if xgi_ratio is None
                    else round(xgi_ratio, 6),
                    "box_touch_ratio": None
                    if box_ratio is None
                    else round(box_ratio, 6),
                    "shots_ratio": None
                    if shots_ratio is None
                    else round(shots_ratio, 6),
                    "posterior_xgi90": posterior_xgi90,
                    "previous_event_rate90": None
                    if previous_event_rate is None
                    else round(previous_event_rate, 6),
                    "sustained_process_improvement": sustained_process,
                },
                "result_vs_process": {
                    "latest_returns": round(latest_returns, 4),
                    "latest_fpl_points": round(latest_points, 4),
                    "latest_xgi": round(latest_xgi, 4),
                    "recent_returns": round(recent_returns, 4),
                    "prior_process_strong": prior_process_strong,
                    "pre_latest_xgi90": None
                    if pre_latest_xgi90 is None
                    else round(pre_latest_xgi90, 6),
                },
                "team_attacking_environment": projection.get(
                    "system_context"
                ),
                "linkup_change": {
                    "current": current_link,
                    "previous": previous_link,
                    "dependency_delta": round(link_delta, 6),
                    "new_links": new_links,
                    "lost_links": lost_links,
                },
                "classifications": classes,
                "primary_classification": primary,
                "materiality_score": round(materiality_score, 3),
                "materiality_reasons": materiality_reasons,
                "deep_analysis_required": deep_required,
                "evidence_classification_only": True,
                "operational_action_created": False,
            }
        )

    material = [row for row in scanned if row["deep_analysis_required"]]
    material.sort(
        key=lambda row: (
            _f(row.get("materiality_score")),
            _f(
                ((row.get("process_trend") or {}).get("posterior_xgi90"))
            ),
            -int(row.get("element_id") or 0),
        ),
        reverse=True,
    )
    return {
        "model": MODEL_ID,
        "scope": "FULL_ELIGIBLE_FPL_PLAYER_UNIVERSE",
        "current_gw": int(current_gw),
        "eligible_count": len(scanned),
        "scanned_count": len(scanned),
        "material_count": len(material),
        "no_material_count": len(scanned) - len(material),
        "players": scanned,
        "material_players": material,
        "deep_analysis_element_ids": [
            int(row["element_id"]) for row in material
        ],
        "governance": {
            "full_universe_scan": True,
            "scorer_assister_only_filter": False,
            "our15_only_filter": False,
            "watchlist_only_filter": False,
            "gw1_current_trajectory_required": True,
            "result_interpreted_against_process": True,
            "breakout_before_returns_supported": True,
            "one_match_haul_never_creates_act": True,
            "deep_analysis_gated_by_materiality": True,
            "linkup_changes_participate": True,
            "operational_action_owner_unchanged": "WAIT_PREPARE_ACT",
            "methodology_weights_20_25_30_25_unchanged": True,
        },
    }


def apply_post_match_universe_comparison(
    scan: Mapping[str, Any],
    *,
    package_optimizer: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach existing full-universe optimizer evidence without new scoring."""
    out = dict(scan)
    players = [dict(row) for row in out.get("players") or []]
    diagnostics = dict(package_optimizer.get("search_diagnostics") or {})
    candidate_pool = dict(package_optimizer.get("candidate_pool") or {})
    pool_rank: dict[int, dict[str, Any]] = {}
    for position, rows in candidate_pool.items():
        for rank, raw in enumerate(rows or [], start=1):
            if not isinstance(raw, Mapping):
                continue
            element = _i(raw.get("element"), -1)
            if element > 0:
                pool_rank[element] = {
                    "position": str(position),
                    "published_position_pool_rank": rank,
                    "candidate_score": raw.get("candidate_score"),
                }

    packages = [
        dict(row)
        for row in package_optimizer.get("packages") or []
        if isinstance(row, Mapping)
    ]
    hold_robust = _f(
        (((package_optimizer.get("hold") or {}).get("score") or {}).get(
            "robust_score"
        ))
    )
    incoming_routes: dict[int, list[dict[str, Any]]] = {}
    outgoing_routes: dict[int, list[dict[str, Any]]] = {}
    for package_rank, package in enumerate(packages, start=1):
        robust = _f((package.get("score") or {}).get("robust_score"))
        for incoming in package.get("ins") or []:
            if not isinstance(incoming, Mapping):
                continue
            element = _i(incoming.get("element"), -1)
            if element > 0:
                incoming_routes.setdefault(element, []).append(
                    {
                        "package_rank": package_rank,
                        "package_id": package.get("id"),
                        "robust_delta_vs_hold": round(
                            robust - hold_robust, 6
                        ),
                    }
                )
        for outgoing in package.get("outs") or []:
            if not isinstance(outgoing, Mapping):
                continue
            element = _i(outgoing.get("element"), -1)
            if element > 0:
                outgoing_routes.setdefault(element, []).append(
                    {
                        "package_rank": package_rank,
                        "package_id": package.get("id"),
                        "robust_delta_vs_hold": round(
                            robust - hold_robust, 6
                        ),
                    }
                )

    priority_map = {
        "BREAKOUT_PROCESS": "BREAKOUT CANDIDATE",
        "OUTPUT_CONFIRMING_PROCESS": "CONFIRMATION CANDIDATE",
        "UNDERLYING_IMPROVING_NO_RETURN": "EARLY PROCESS CANDIDATE",
        "REGRESSION_RISK": "REGRESSION CANDIDATE",
        "ROLE_BREAKOUT": "ROLE-CHANGE CANDIDATE",
        "ROLE_DECLINE": "ROLE-CHANGE CANDIDATE",
        "MINUTES_BREAKOUT": "MINUTES-CHANGE CANDIDATE",
        "MINUTES_DECLINE": "MINUTES-CHANGE CANDIDATE",
        "LINKUP_BREAKOUT": "LINK-UP-DEPENDENCY CANDIDATE",
        "LINKUP_BROKEN": "LINK-UP-DEPENDENCY CANDIDATE",
    }
    for row in players:
        element = int(row["element_id"])
        pool = dict(pool_rank.get(element) or {})
        ins = list(incoming_routes.get(element) or [])
        outs = list(outgoing_routes.get(element) or [])
        if row.get("owned"):
            comparison_state = "OWNED_PLAYER_REVIEW"
        elif ins:
            comparison_state = "FULL_UNIVERSE_PACKAGE_CHALLENGER"
        elif pool:
            comparison_state = "PUBLISHED_POSITION_POOL_ONLY"
        else:
            comparison_state = "OUTSIDE_PUBLISHED_POSITION_POOL"
        labels = list(
            dict.fromkeys(
                priority_map[value]
                for value in row.get("classifications") or []
                if value in priority_map
            )
        )
        row["universe_comparison"] = {
            "state": comparison_state,
            **pool,
            "incoming_package_routes": ins,
            "outgoing_package_routes": outs,
            "beats_hold_in_any_published_package": any(
                _f(route.get("robust_delta_vs_hold")) > 0.0
                for route in ins
            ),
            "priority_candidate_labels": labels,
            "automatic_transfer_recommendation": False,
        }

    material = [row for row in players if row.get("deep_analysis_required")]
    material.sort(
        key=lambda row: (
            1
            if (row.get("universe_comparison") or {}).get(
                "beats_hold_in_any_published_package"
            )
            else 0,
            -_i(
                (row.get("universe_comparison") or {}).get(
                    "published_position_pool_rank"
                ),
                999,
            ),
            _f(row.get("materiality_score")),
        ),
        reverse=True,
    )
    out["players"] = players
    out["material_players"] = material
    out["deep_analysis_element_ids"] = [
        int(row["element_id"]) for row in material
    ]
    out["universe_comparison"] = {
        "search_authority": diagnostics.get("search_authority"),
        "candidate_origin": diagnostics.get("candidate_origin"),
        "official_projection_universe_count": diagnostics.get(
            "official_projection_universe_count"
        ),
        "eligible_universe_count": diagnostics.get("eligible_universe_count"),
        "candidate_pool_is_preview_only": package_optimizer.get(
            "candidate_pool_is_preview_only"
        ),
        "full_universe_scanned_before_pruning": (
            (package_optimizer.get("governance") or {}).get(
                "official_fpl_full_universe_scanned_before_pruning"
            )
            is True
        ),
        "fresh_ranking_rebuilt_from_existing_optimizer": True,
        "new_scoring_authority_created": False,
        "transfer_action_created_by_scan": False,
    }
    return out


def _similarity_component(old: Any, current: Any) -> float | None:
    if old in {None, ""} or current in {None, ""}:
        return None
    if isinstance(old, (int, float)) and isinstance(current, (int, float)):
        return _clamp(1.0 - abs(float(old) - float(current)), 0.0, 1.0)
    return 1.0 if str(old).strip().upper() == str(current).strip().upper() else 0.0


def tactical_similarity(
    historical_row: Mapping[str, Any],
    current_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    current = dict(current_context or {})
    fields = (
        ("manager", historical_row.get("manager_id") or historical_row.get("manager"), current.get("manager_id") or current.get("manager")),
        ("formation", historical_row.get("formation"), current.get("formation")),
        ("block_height", historical_row.get("block_height"), current.get("block_height")),
        ("pressing_style", historical_row.get("pressing_style"), current.get("pressing_style")),
        ("cb_personnel", historical_row.get("cb_personnel"), current.get("cb_personnel")),
        ("fb_personnel", historical_row.get("fb_personnel"), current.get("fb_personnel")),
        ("midfield_structure", historical_row.get("midfield_structure"), current.get("midfield_structure")),
        (
            "team_strength_regime",
            historical_row.get("team_strength_regime"),
            current.get("team_strength_regime"),
        ),
        ("player_role", _role_label(historical_row), current.get("player_role")),
    )
    observed = [(name, _similarity_component(old, now)) for name, old, now in fields]
    observed = [(name, value) for name, value in observed if value is not None]
    if not observed:
        return {"status": "UNAVAILABLE", "coefficient": 0.0, "coverage": 0.0, "components": {}}
    coefficient = sum(value for _, value in observed) / len(observed)
    return {
        "status": "AVAILABLE" if len(observed) >= 3 else "PARTIAL",
        "coefficient": round(coefficient, 6),
        "coverage": round(len(observed) / len(fields), 6),
        "components": {name: round(value, 6) for name, value in observed},
    }


def evaluate_opponent_matchup(
    trajectory: Mapping[str, Any],
    raw_match_rows: Sequence[Mapping[str, Any]],
    *,
    player_id: int,
    opponent_team_id: int,
    current_context: Mapping[str, Any] | None = None,
    history_scope: str | None = None,
) -> dict[str, Any]:
    player_rows = [
        dict(row)
        for row in raw_match_rows
        if _i(row.get("player_id"), _i(row.get("element"), -1)) == int(player_id)
    ]
    meetings = [
        row
        for row in player_rows
        if _i(row.get("opponent_team_id"), _i(row.get("opponent"), -1)) == int(opponent_team_id)
        and _minutes(row) > 0
    ]
    baseline_xgi90 = ((trajectory.get("rates") or {}).get("xgi") or {}).get("posterior_rate90")
    cfg = load_config().get("matchup") or {}
    prior_decay = _clamp(_f(cfg.get("prior_season_decay"), 0.65), 0.0, 1.0)

    def season_age(row: Mapping[str, Any]) -> int:
        return max(
            0,
            _i(
                row.get("season_age"),
                _i(row.get("season_offset"), 0),
            ),
        )

    season_weights = [prior_decay ** season_age(row) for row in meetings]
    matchup_xgi90 = _rate90(meetings, "xgi", season_weights)
    k = max(0.1, _f(cfg.get("sample_shrinkage_k"), 3.0))
    effective_sample = sum(season_weights)
    sample_strength = (
        effective_sample / (effective_sample + k)
        if effective_sample > 0.0
        else 0.0
    )
    similarities = [tactical_similarity(row, current_context) for row in meetings]
    similarity_weight_pairs = [
        (similarity["coefficient"], season_weight)
        for similarity, season_weight in zip(similarities, season_weights)
        if similarity.get("status") != "UNAVAILABLE"
    ]
    relevance_denominator = sum(weight for _, weight in similarity_weight_pairs)
    relevance = (
        sum(value * weight for value, weight in similarity_weight_pairs)
        / relevance_denominator
        if relevance_denominator > 0.0
        else 0.0
    )
    ratio = None
    if matchup_xgi90 is not None and baseline_xgi90 not in {None, 0}:
        ratio = max(0.05, matchup_xgi90 / float(baseline_xgi90))
    log_cap = max(0.0, _f(cfg.get("maximum_log_rate_adjustment"), math.log(1.2)))
    log_delta = 0.0
    if ratio is not None:
        log_delta = _clamp(math.log(ratio) * sample_strength * relevance, -log_cap, log_cap)
    modifier = math.exp(log_delta)
    min_minutes = max(0.0, _f(cfg.get("minimum_process_minutes"), 60.0))
    process_minutes = sum(_minutes(row) for row in meetings)
    if not meetings or process_minutes < min_minutes or relevance <= 0.0:
        classification = "INSUFFICIENT SAMPLE"
    elif modifier >= _f(cfg.get("supportive_ratio"), 1.12):
        classification = "SUPPORTIVE"
    elif modifier <= _f(cfg.get("adverse_ratio"), 0.88):
        classification = "ADVERSE"
    else:
        classification = "NEUTRAL"
    return {
        "model": MODEL_ID,
        "opponent_team_id": int(opponent_team_id),
        "historical_meetings": len(meetings),
        "sample_size": len(meetings),
        "effective_sample_size": round(effective_sample, 6),
        "current_season_meetings": sum(1 for row in meetings if season_age(row) == 0),
        "prior_season_meetings": sum(1 for row in meetings if season_age(row) > 0),
        "opponent_history_scope": (
            history_scope
            or (
                "MULTI-SEASON GOVERNED"
                if any(season_age(row) > 0 for row in meetings)
                else "CURRENT-SEASON ONLY"
            )
        ),
        "prior_season_matchup_status": (
            "AVAILABLE"
            if any(season_age(row) > 0 for row in meetings)
            else "UNAVAILABLE — NO GOVERNED MATCH-LEVEL FACTUAL SOURCE"
        ),
        "prior_season_decay": round(prior_decay, 6),
        "process_minutes": round(process_minutes, 1),
        "result_process": _result_vs_process(meetings),
        "matchup_xgi90": None if matchup_xgi90 is None else round(matchup_xgi90, 6),
        "current_baseline_xgi90": baseline_xgi90,
        "sample_shrinkage": round(sample_strength, 6),
        "tactical_similarity": round(relevance, 6),
        "tactical_similarity_details": similarities,
        "posterior_rate_modifier": round(modifier, 6),
        "classification": classification,
        "governance": {
            "raw_scoreline_is_not_authority": True,
            "small_sample_shrunk_to_current_baseline": True,
            "manager_system_personnel_change_discounts_history": True,
        },
    }


def _role_complementarity(target_role: Any, teammate_role: Any) -> float:
    target = str(target_role or "").upper()
    teammate = str(teammate_role or "").upper()
    if not target or not teammate:
        return 0.0
    creator_tokens = ("CREATOR", "PLAYMAKER", "WINGER", "FULLBACK", "WB")
    finisher_tokens = ("FINISHER", "STRIKER", "FWD", "9")
    progressor_tokens = ("PROGRESSOR", "DM", "CM", "DEEP")
    target_finisher = any(token in target for token in finisher_tokens)
    teammate_creator = any(token in teammate for token in creator_tokens)
    target_creator = any(token in target for token in creator_tokens)
    teammate_progressor = any(token in teammate for token in progressor_tokens)
    if target_finisher and teammate_creator:
        return 1.0
    if target_creator and teammate_progressor:
        return 0.75
    return 0.25 if target != teammate else 0.1


def evaluate_linkup(
    target_rows: Sequence[Mapping[str, Any]],
    teammate_rows: Sequence[Mapping[str, Any]],
    *,
    target_player_id: int,
    teammate_player_id: int,
    target_role: Any = None,
    teammate_role: Any = None,
    connection_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    target = {
        _match_id(row): dict(row)
        for row in target_rows
        if _i(row.get("player_id"), _i(row.get("element"), -1)) == int(target_player_id)
        and _match_id(row)
    }
    teammate = {
        _match_id(row): dict(row)
        for row in teammate_rows
        if _i(row.get("player_id"), _i(row.get("element"), -1)) == int(teammate_player_id)
        and _match_id(row)
    }
    with_rows = []
    without_rows = []
    shared_minutes = 0.0
    for match_id, row in target.items():
        other = teammate.get(match_id)
        if other is not None and _minutes(other) > 0:
            with_rows.append(row)
            shared_minutes += min(_minutes(row), _minutes(other))
        else:
            without_rows.append(row)
    with_xgi90 = _rate90(with_rows, "xgi")
    without_xgi90 = _rate90(without_rows, "xgi")
    baseline_xgi90 = _rate90(list(target.values()), "xgi")
    ratio = None
    if with_xgi90 is not None and without_xgi90 not in {None, 0}:
        ratio = max(0.05, with_xgi90 / float(without_xgi90))
    elif with_xgi90 is not None and baseline_xgi90 not in {None, 0}:
        ratio = max(0.05, with_xgi90 / float(baseline_xgi90))

    connections = [
        dict(row)
        for row in (connection_rows or [])
        if _i(row.get("from_player_id"), -1) == int(teammate_player_id)
        and _i(row.get("to_player_id"), -1) == int(target_player_id)
    ]
    direct_count = sum(
        _f(row.get("chances_created_to"))
        + _f(row.get("xa_to_xg"))
        + 0.25 * _f(row.get("progressive_passes_to"))
        + 0.20 * _f(row.get("crosses_to"))
        + 0.30 * _f(row.get("cutbacks_to"))
        for row in connections
    )
    direct_score = 1.0 - math.exp(-max(0.0, direct_count) / 3.0) if direct_count > 0 else 0.0
    role_score = _role_complementarity(target_role, teammate_role)

    def role_relevance(
        rows: Sequence[Mapping[str, Any]],
        current_role: Any,
    ) -> tuple[float, str]:
        current = str(current_role or "").strip().upper()
        observed = [
            str(_role_label(row) or "").strip().upper()
            for row in rows
            if _role_label(row)
        ]
        if not current or not observed:
            return 1.0, "UNAVAILABLE_NO_DISCOUNT"
        matches = sum(1 for role in observed if role == current)
        relevance = matches / len(observed)
        return relevance, "AVAILABLE"

    target_role_relevance, target_role_relevance_status = role_relevance(
        with_rows, target_role
    )
    teammate_role_relevance, teammate_role_relevance_status = role_relevance(
        [
            teammate[match_id]
            for match_id in target
            if match_id in teammate and _minutes(teammate[match_id]) > 0
        ],
        teammate_role,
    )
    tactical_role_relevance = min(
        target_role_relevance, teammate_role_relevance
    )

    cfg = load_config().get("linkup") or {}
    k = max(0.1, _f(cfg.get("sample_shrinkage_k"), 4.0))
    sample_n = len(with_rows)
    sample_strength = sample_n / (sample_n + k) if sample_n else 0.0
    with_without_score = 0.0
    if ratio is not None:
        with_without_score = _clamp(abs(math.log(ratio)) / math.log(2.0), 0.0, 1.0)
    evidence_strength = (
        _f(cfg.get("direct_connection_weight"), 0.55) * direct_score
        + _f(cfg.get("with_without_weight"), 0.30) * with_without_score
        + _f(cfg.get("role_complementarity_weight"), 0.15) * role_score
    )
    confidence = sample_strength * evidence_strength * tactical_role_relevance
    if not connections and role_score <= 0.0:
        # With/without co-movement without a process bridge is correlation only.
        confidence = 0.0
    elif not connections:
        confidence = min(confidence, _f(cfg.get("low_confidence_cap"), 0.35))
    if shared_minutes < _f(cfg.get("minimum_shared_minutes"), 90.0):
        confidence *= shared_minutes / max(1.0, _f(cfg.get("minimum_shared_minutes"), 90.0))
    log_cap = max(0.0, _f(cfg.get("maximum_log_rate_adjustment"), math.log(1.25)))
    signed_log = 0.0 if ratio is None else _clamp(math.log(ratio) * confidence, -log_cap, log_cap)
    with_modifier = math.exp(signed_log)
    without_modifier = math.exp(-signed_log)
    direction = "POSITIVE" if signed_log > 0.01 else "NEGATIVE" if signed_log < -0.01 else "WEAK_OR_NONE"
    return {
        "model": MODEL_ID,
        "target_player_id": int(target_player_id),
        "source_player_id": int(teammate_player_id),
        "teammate_player_id": int(teammate_player_id),
        "direction": [int(teammate_player_id), int(target_player_id)],
        "relationship_type": "EVIDENCE_DERIVED_DIRECTIONAL_DEPENDENCY",
        "shared_matches": sample_n,
        "shared_minutes": round(shared_minutes, 1),
        "with_target_xgi90": None if with_xgi90 is None else round(with_xgi90, 6),
        "without_target_xgi90": None if without_xgi90 is None else round(without_xgi90, 6),
        "with_without_ratio": None if ratio is None else round(ratio, 6),
        "direct_connection_evidence": {
            "status": "AVAILABLE" if connections else "UNAVAILABLE",
            "rows": len(connections),
            "weighted_connection_count": round(direct_count, 6),
            "score": round(direct_score, 6),
        },
        "role_complementarity": round(role_score, 6),
        "tactical_role_relevance": round(tactical_role_relevance, 6),
        "tactical_role_relevance_status": {
            "target": target_role_relevance_status,
            "teammate": teammate_role_relevance_status,
        },
        "dependency_strength": round(abs(signed_log) / max(log_cap, 1e-9), 6) if log_cap else 0.0,
        "dependency_direction": direction,
        "confidence": round(_clamp(confidence, 0.0, 1.0), 6),
        "sample_size": sample_n,
        "with_player_modifier": round(with_modifier, 6),
        "without_player_modifier": round(without_modifier, 6),
        "governance": {
            "correlation_alone_is_insufficient": True,
            "missing_direct_link_evidence_caps_confidence": not bool(connections),
            "small_sample_bayesian_shrinkage": True,
            "historical_role_change_discounted": True,
        },
    }


def probability_weighted_link_modifier(link: Mapping[str, Any], teammate_p_start: float) -> dict[str, Any]:
    p = _clamp(_f(teammate_p_start), 0.0, 1.0)
    with_mod = max(0.01, _f(link.get("with_player_modifier"), 1.0))
    without_mod = max(0.01, _f(link.get("without_player_modifier"), 1.0))
    marginal = p * with_mod + (1.0 - p) * without_mod
    return {
        "teammate_p_start": round(p, 6),
        "conditional_with_modifier": round(with_mod, 6),
        "conditional_without_modifier": round(without_mod, 6),
        "marginal_modifier": round(marginal, 6),
        "method": "PSTART_WEIGHTED_MARGINALIZATION",
    }


def _edge_id(edge: Mapping[str, Any]) -> str:
    source = _i(
        edge.get("source_player_id"),
        _i(edge.get("teammate_player_id"), -1),
    )
    target = _i(edge.get("target_player_id"), -1)
    return f"{source}->{target}"


def _chain_edge_eligible(edge: Mapping[str, Any]) -> bool:
    cfg = load_config().get("linkup") or {}
    min_confidence = max(
        0.0, _f(cfg.get("minimum_chain_edge_confidence"), 0.05)
    )
    min_shared = max(0.0, _f(cfg.get("minimum_shared_minutes"), 90.0))
    direct_available = (
        (edge.get("direct_connection_evidence") or {}).get("status")
        == "AVAILABLE"
    )
    role_compatible = (
        _f(edge.get("role_complementarity")) > 0.1 or direct_available
    )
    return (
        _i(edge.get("source_player_id"), _i(edge.get("teammate_player_id"), -1))
        > 0
        and _i(edge.get("target_player_id"), -1) > 0
        and _f(edge.get("confidence")) >= min_confidence
        and _f(edge.get("shared_minutes")) >= min_shared
        and str(edge.get("dependency_direction") or "") != "WEAK_OR_NONE"
        and role_compatible
    )


def evaluate_multi_player_chain(
    edges: Sequence[Mapping[str, Any]],
    teammate_start_probabilities: Mapping[int, float],
) -> dict[str, Any]:
    cfg = load_config().get("linkup") or {}
    max_players = max(3, _i(cfg.get("max_chain_length"), 4))
    ordered_edges = [dict(edge) for edge in edges]
    if len(ordered_edges) < 2:
        return {
            "status": "INSUFFICIENT_CHAIN",
            "multiplier": 1.0,
            "confidence": 0.0,
        }
    if not all(_chain_edge_eligible(edge) for edge in ordered_edges):
        return {
            "status": "REJECTED_LOW_CONFIDENCE_OR_INCOMPATIBLE_EDGE",
            "multiplier": 1.0,
            "confidence": 0.0,
        }

    players = [
        _i(
            ordered_edges[0].get("source_player_id"),
            _i(ordered_edges[0].get("teammate_player_id"), -1),
        )
    ]
    valid_direction = True
    for edge in ordered_edges:
        source = _i(
            edge.get("source_player_id"),
            _i(edge.get("teammate_player_id"), -1),
        )
        target = _i(edge.get("target_player_id"), -1)
        if players[-1] != source:
            valid_direction = False
            break
        players.append(target)
    if not valid_direction:
        return {
            "status": "REJECTED_INCOMPATIBLE_DIRECTION",
            "multiplier": 1.0,
            "confidence": 0.0,
        }
    if len(set(players)) != len(players):
        return {
            "status": "REJECTED_CYCLE",
            "players": players,
            "multiplier": 1.0,
            "confidence": 0.0,
        }
    if len(players) > max_players:
        return {
            "status": "REJECTED_MAX_CHAIN_LENGTH",
            "players": players,
            "max_chain_length": max_players,
            "multiplier": 1.0,
            "confidence": 0.0,
        }

    confidence = min(_f(edge.get("confidence")) for edge in ordered_edges)
    upstream_players = players[:-1]
    linked_start = {
        player_id: _clamp(
            _f(teammate_start_probabilities.get(player_id), 1.0),
            0.0,
            1.0,
        )
        for player_id in upstream_players
    }
    intact_probability = math.prod(linked_start.values())
    edge_multiplier = math.prod(
        max(0.01, _f(edge.get("with_player_modifier"), 1.0))
        for edge in ordered_edges
    )
    multiplier = 1.0 + intact_probability * confidence * (
        edge_multiplier - 1.0
    )

    middle_players = players[1:-1]
    middle_absent_probability = 0.0 if middle_players else None
    middle_absence_multiplier = 1.0 if middle_players else None
    player_name_map: dict[int, Any] = {}
    for edge in ordered_edges:
        source = _i(
            edge.get("source_player_id"),
            _i(edge.get("teammate_player_id"), -1),
        )
        target = _i(edge.get("target_player_id"), -1)
        if source > 0 and edge.get("source_name"):
            player_name_map[source] = edge.get("source_name")
        if target > 0 and edge.get("target_name"):
            player_name_map[target] = edge.get("target_name")
    return {
        "status": "AVAILABLE",
        "players": players,
        "direction": players,
        "player_ids": players,
        "player_names": [
            player_name_map.get(player_id) for player_id in players
        ],
        "relationship_type": "BOUNDED_MULTI_PLAYER_DEPENDENCY_CHAIN",
        "edge_count": len(ordered_edges),
        "edges": ordered_edges,
        "chain_intact_probability": round(intact_probability, 6),
        "confidence": round(confidence, 6),
        "weakest_link_confidence": round(confidence, 6),
        "linked_player_p_start": {
            str(player_id): round(probability, 6)
            for player_id, probability in linked_start.items()
        },
        "edge_product_modifier": round(edge_multiplier, 6),
        "raw_chain_multiplier": round(multiplier, 6),
        "legacy_full_edge_raw_multiplier": round(multiplier, 6),
        "overlapping_pairwise_multiplier": None,
        "incremental_chain_multiplier": None,
        "effective_chain_multiplier": None,
        "anti_double_count_applied": False,
        "overlap_edge_ids": [],
        "overlapping_edges": [],
        "chain_incremental_confidence": round(confidence, 6),
        "multiplier": round(multiplier, 6),
        "middle_players": middle_players,
        "middle_absence_multiplier": middle_absence_multiplier,
        "main_dependency_risk": (
            "MIDDLE_NODE_START_RISK"
            if middle_players
            and any(linked_start.get(player_id, 1.0) < 0.8 for player_id in middle_players)
            else "CHAIN_AVAILABILITY"
        ),
        "bounded_approximation": True,
        "combinatorial_expansion_used": False,
        "max_chain_length": max_players,
    }


def construct_directional_chains(
    edges: Sequence[Mapping[str, Any]],
    *,
    target_player_id: int,
    teammate_start_probabilities: Mapping[int, float],
) -> list[dict[str, Any]]:
    cfg = load_config().get("linkup") or {}
    max_players = max(3, _i(cfg.get("max_chain_length"), 4))
    max_incoming = max(
        1,
        _i(cfg.get("maximum_qualified_incoming_edges_per_node"), 3),
    )
    max_chains = max(1, _i(cfg.get("maximum_runtime_chains_per_target"), 5))
    qualified = [dict(edge) for edge in edges if _chain_edge_eligible(edge)]

    incoming: dict[int, list[dict[str, Any]]] = {}
    for edge in qualified:
        incoming.setdefault(_i(edge.get("target_player_id"), -1), []).append(edge)
    for rows in incoming.values():
        rows.sort(
            key=lambda edge: (
                _f(edge.get("confidence")),
                _f(edge.get("dependency_strength")),
            ),
            reverse=True,
        )
        del rows[max_incoming:]

    candidates: list[list[dict[str, Any]]] = []

    def walk(node: int, reverse_path: list[dict[str, Any]], used: set[int]) -> None:
        if len(reverse_path) >= 2:
            candidates.append(list(reversed(reverse_path)))
        if len(used) >= max_players:
            return
        for edge in incoming.get(node, []):
            source = _i(
                edge.get("source_player_id"),
                _i(edge.get("teammate_player_id"), -1),
            )
            if source <= 0 or source in used:
                continue
            walk(
                source,
                reverse_path + [edge],
                used | {source},
            )

    walk(int(target_player_id), [], {int(target_player_id)})
    evaluated = [
        evaluate_multi_player_chain(path, teammate_start_probabilities)
        for path in candidates
    ]
    evaluated = [row for row in evaluated if row.get("status") == "AVAILABLE"]
    evaluated.sort(
        key=lambda row: (
            _f(row.get("confidence")),
            abs(_f(row.get("multiplier"), 1.0) - 1.0),
            _i(row.get("edge_count")),
        ),
        reverse=True,
    )
    return evaluated[:max_chains]


def resolve_incremental_chain_effects(
    chains: Sequence[Mapping[str, Any]],
    pairwise_contributions: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Remove pairwise-owned terminal effects from higher-order chains.

    Pairwise owns direct source->target conditional effects. A chain may use
    that terminal edge as evidence, but runtime chain multiplication owns only
    the upstream interaction that remains after the terminal direct effect.
    """
    resolved: list[dict[str, Any]] = []
    consumed_upstream_edge_ids: set[str] = set()
    ordered = sorted(
        [dict(row) for row in chains if isinstance(row, Mapping)],
        key=lambda row: (
            _f(row.get("confidence")),
            abs(_f(row.get("raw_chain_multiplier"), _f(row.get("multiplier"), 1.0)) - 1.0),
            _i(row.get("edge_count")),
        ),
        reverse=True,
    )
    for chain in ordered:
        edges = [
            dict(edge)
            for edge in chain.get("edges") or []
            if isinstance(edge, Mapping)
        ]
        if len(edges) < 2:
            continue
        terminal = edges[-1]
        terminal_id = _edge_id(terminal)
        pairwise = dict(pairwise_contributions.get(terminal_id) or {})
        if not pairwise:
            # A higher-order chain is incremental to an actually applied
            # terminal pairwise owner. Without that owner, fail closed rather
            # than silently changing chain semantics.
            chain.update(
                {
                    "status": "REJECTED_TERMINAL_PAIRWISE_NOT_APPLIED",
                    "anti_double_count_applied": True,
                    "overlap_edge_ids": [],
                    "overlapping_edges": [],
                    "overlapping_pairwise_multiplier": 1.0,
                    "incremental_chain_multiplier": 1.0,
                    "effective_chain_multiplier": 1.0,
                    "multiplier": 1.0,
                    "chain_incremental_confidence": 0.0,
                }
            )
            resolved.append(chain)
            continue

        upstream_edges = edges[:-1]
        unique_upstream = [
            edge
            for edge in upstream_edges
            if _edge_id(edge) not in consumed_upstream_edge_ids
        ]
        for edge in unique_upstream:
            consumed_upstream_edge_ids.add(_edge_id(edge))

        intact = _clamp(_f(chain.get("chain_intact_probability")), 0.0, 1.0)
        confidence = _clamp(_f(chain.get("confidence")), 0.0, 1.0)
        upstream_product = math.prod(
            max(0.01, _f(edge.get("with_player_modifier"), 1.0))
            for edge in unique_upstream
        )
        residual = 1.0 + intact * confidence * (upstream_product - 1.0)

        final_role = str(terminal.get("target_role") or "").upper()
        creator_target = any(
            token in final_role for token in ("CREATOR", "PLAYMAKER")
        )
        if creator_target:
            incremental_goal = 1.0
            incremental_assist = residual
            overlap_goal = 1.0
            overlap_assist = max(
                0.01, _f(pairwise.get("assist_multiplier"), 1.0)
            )
        else:
            incremental_goal = residual
            incremental_assist = math.exp(math.log(max(0.01, residual)) * 0.5)
            overlap_goal = max(
                0.01, _f(pairwise.get("goal_multiplier"), 1.0)
            )
            overlap_assist = max(
                0.01, _f(pairwise.get("assist_multiplier"), 1.0)
            )

        primary_overlap = overlap_assist if creator_target else overlap_goal
        primary_incremental = (
            incremental_assist if creator_target else incremental_goal
        )
        raw_primary = primary_overlap * primary_incremental

        chain.update(
            {
                "status": "AVAILABLE",
                "raw_chain_multiplier": round(raw_primary, 6),
                "overlapping_pairwise_multiplier": round(primary_overlap, 6),
                "incremental_chain_multiplier": round(
                    primary_incremental, 6
                ),
                "effective_chain_multiplier": round(
                    primary_incremental, 6
                ),
                "anti_double_count_applied": True,
                "overlap_edge_ids": [terminal_id],
                "overlapping_edges": [
                    {
                        "edge_id": terminal_id,
                        "source_player_id": terminal.get(
                            "source_player_id",
                            terminal.get("teammate_player_id"),
                        ),
                        "target_player_id": terminal.get("target_player_id"),
                    }
                ],
                "upstream_incremental_edge_ids": [
                    _edge_id(edge) for edge in unique_upstream
                ],
                "deduplicated_upstream_edge_ids": [
                    _edge_id(edge)
                    for edge in upstream_edges
                    if _edge_id(edge) not in {
                        _edge_id(item) for item in unique_upstream
                    }
                ],
                "chain_incremental_confidence": round(confidence, 6),
                "channel_effects": {
                    "goal": {
                        "raw_chain_contribution": round(
                            overlap_goal * incremental_goal, 6
                        ),
                        "overlap_removed": round(overlap_goal, 6),
                        "incremental_chain_contribution": round(
                            incremental_goal, 6
                        ),
                    },
                    "assist": {
                        "raw_chain_contribution": round(
                            overlap_assist * incremental_assist, 6
                        ),
                        "overlap_removed": round(overlap_assist, 6),
                        "incremental_chain_contribution": round(
                            incremental_assist, 6
                        ),
                    },
                },
                # Backward-facing multiplier now means the runtime-effective
                # residual, not the pre-repair full-edge product.
                "multiplier": round(primary_incremental, 6),
            }
        )
        resolved.append(chain)
    return resolved


def build_contextual_dynamics(
    match_rows: Sequence[Mapping[str, Any]],
    *,
    player_id: int,
    current_gw: int,
    opponent_team_id: int,
    current_context: Mapping[str, Any] | None = None,
    linkups: Sequence[Mapping[str, Any]] | None = None,
    chains: Sequence[Mapping[str, Any]] | None = None,
    teammate_start_probabilities: Mapping[int, float] | None = None,
    opponent_history_rows: Sequence[Mapping[str, Any]] | None = None,
    opponent_history_scope: str | None = None,
) -> dict[str, Any]:
    trajectory = build_player_trajectory(match_rows, player_id=player_id, current_gw=current_gw)
    historical_rows = [
        dict(row) for row in (opponent_history_rows or [])
    ]
    matchup_rows = list(match_rows) + historical_rows
    matchup = evaluate_opponent_matchup(
        trajectory,
        matchup_rows,
        player_id=player_id,
        opponent_team_id=opponent_team_id,
        current_context=current_context,
        history_scope=opponent_history_scope,
    )
    xg_rates = ((trajectory.get("rates") or {}).get("xg") or {})
    xa_rates = ((trajectory.get("rates") or {}).get("xa") or {})

    def recency_multiplier(rate_bundle: Mapping[str, Any]) -> float:
        season = rate_bundle.get("season_rate90")
        posterior = rate_bundle.get("posterior_rate90")
        if season in {None, 0} or posterior is None:
            return 1.0
        effective_sample = max(0.0, _f(rate_bundle.get("effective_sample")))
        shrink = max(
            0.1,
            _f((load_config().get("recency") or {}).get("posterior_shrinkage_equivalent_matches"), 4.0),
        )
        confidence = effective_sample / (effective_sample + shrink)
        return math.exp(_clamp(math.log(max(0.05, float(posterior) / float(season))) * confidence, -math.log(1.2), math.log(1.2)))

    trajectory_goal = recency_multiplier(xg_rates)
    trajectory_assist = recency_multiplier(xa_rates)
    matchup_mod = max(0.01, _f(matchup.get("posterior_rate_modifier"), 1.0))

    link_rows = list(linkups or [])
    teammate_probs = dict(teammate_start_probabilities or {})
    marginal_rows = []
    pairwise_contributions: dict[str, dict[str, Any]] = {}
    link_goal = 1.0
    link_assist = 1.0
    for link in link_rows:
        teammate = _i(link.get("teammate_player_id"), -1)
        target = _i(link.get("target_player_id"), int(player_id))
        marginal = probability_weighted_link_modifier(
            link, teammate_probs.get(teammate, 1.0)
        )
        confidence = _clamp(_f(link.get("confidence")), 0.0, 1.0)
        safe = max(
            0.01, _f(marginal.get("marginal_modifier"), 1.0)
        )
        role_hint = str(link.get("target_role") or "").upper()
        if any(token in role_hint for token in ("CREATOR", "PLAYMAKER")):
            goal_effect = 1.0
            assist_effect = math.exp(math.log(safe) * confidence)
        else:
            goal_effect = math.exp(math.log(safe) * confidence)
            assist_effect = math.exp(math.log(safe) * confidence * 0.5)
        edge_id = f"{teammate}->{target}"
        pairwise_contributions[edge_id] = {
            "edge_id": edge_id,
            "source_player_id": teammate,
            "target_player_id": target,
            "teammate_p_start": marginal.get("teammate_p_start"),
            "marginal_modifier": round(safe, 6),
            "confidence": round(confidence, 6),
            "goal_multiplier": round(goal_effect, 6),
            "assist_multiplier": round(assist_effect, 6),
        }
        marginal_rows.append(
            {
                **marginal,
                "edge_id": edge_id,
                "teammate_player_id": teammate,
                "target_player_id": target,
                "confidence": link.get("confidence"),
                "applied_goal_multiplier": round(goal_effect, 6),
                "applied_assist_multiplier": round(assist_effect, 6),
            }
        )
        link_goal *= goal_effect
        link_assist *= assist_effect

    raw_chain_rows = [
        dict(row)
        for row in (chains or [])
        if isinstance(row, Mapping)
        and row.get("status") == "AVAILABLE"
    ]
    chain_rows = resolve_incremental_chain_effects(
        raw_chain_rows,
        pairwise_contributions,
    )
    chain_goal = 1.0
    chain_assist = 1.0
    for chain in chain_rows:
        if chain.get("status") != "AVAILABLE":
            continue
        effects = dict(chain.get("channel_effects") or {})
        chain_goal *= max(
            0.01,
            _f(
                (effects.get("goal") or {}).get(
                    "incremental_chain_contribution"
                ),
                1.0,
            ),
        )
        chain_assist *= max(
            0.01,
            _f(
                (effects.get("assist") or {}).get(
                    "incremental_chain_contribution"
                ),
                1.0,
            ),
        )

    combined_cfg = load_config().get("combined") or {}
    low = _f(combined_cfg.get("minimum_multiplier"), 0.72)
    high = _f(combined_cfg.get("maximum_multiplier"), 1.35)
    goal_multiplier = _clamp(
        trajectory_goal * matchup_mod * link_goal * chain_goal,
        low,
        high,
    )
    assist_multiplier = _clamp(
        trajectory_assist * matchup_mod * link_assist * chain_assist,
        low,
        high,
    )
    return {
        "model": MODEL_ID,
        "model_owner": MODEL_OWNER,
        "player_id": int(player_id),
        "trajectory": trajectory,
        "opponent_specific_matchup": matchup,
        "linkup_network": {
            "relationships": link_rows,
            "pairwise_links": link_rows,
            "marginalized": marginal_rows,
            "relationship_count": len(link_rows),
            "multi_player_chains": chain_rows,
            "chain_count": len(chain_rows),
        },
        "event_multipliers": {
            "goal": round(goal_multiplier, 6),
            "assist": round(assist_multiplier, 6),
            "trajectory_goal": round(trajectory_goal, 6),
            "trajectory_assist": round(trajectory_assist, 6),
            "matchup": round(matchup_mod, 6),
            "linkup_goal": round(link_goal, 6),
            "linkup_assist": round(link_assist, 6),
            "pairwise_contribution": {
                "goal": round(link_goal, 6),
                "assist": round(link_assist, 6),
            },
            "raw_chain_contribution": {
                "goal": round(
                    math.prod(
                        max(
                            0.01,
                            _f(
                                ((row.get("channel_effects") or {}).get(
                                    "goal"
                                ) or {}).get("raw_chain_contribution"),
                                1.0,
                            ),
                        )
                        for row in chain_rows
                        if row.get("status") == "AVAILABLE"
                    ),
                    6,
                ),
                "assist": round(
                    math.prod(
                        max(
                            0.01,
                            _f(
                                ((row.get("channel_effects") or {}).get(
                                    "assist"
                                ) or {}).get("raw_chain_contribution"),
                                1.0,
                            ),
                        )
                        for row in chain_rows
                        if row.get("status") == "AVAILABLE"
                    ),
                    6,
                ),
            },
            "overlap_removed": {
                "terminal_pairwise_edge_ids": sorted(
                    {
                        edge_id
                        for row in chain_rows
                        for edge_id in row.get("overlap_edge_ids") or []
                    }
                ),
            },
            "incremental_chain_contribution": {
                "goal": round(chain_goal, 6),
                "assist": round(chain_assist, 6),
            },
            "chain_goal": round(chain_goal, 6),
            "chain_assist": round(chain_assist, 6),
            "final_dependency_goal": round(link_goal * chain_goal, 6),
            "final_dependency_assist": round(
                link_assist * chain_assist, 6
            ),
        },
        "governance": {
            "v6_factual_plane_mutated": False,
            "existing_bayesian_core_replaced": False,
            "existing_xmins_replaced": False,
            "existing_monte_carlo_replaced": False,
            "methodology_weights_20_25_30_25_unchanged": True,
            "named_player_rules": False,
            "raw_h2h_result_is_not_sufficient": True,
            "multi_player_chain_runtime_wired": bool(chain_rows),
            "pairwise_chain_anti_double_count": True,
            "terminal_pairwise_owned_once": True,
            "final_cap_is_not_anti_double_count": True,
            "trajectory_window_current_season_only": True,
            "opponent_history_window_separate": True,
        },
    }


def report_blocks(contextual: Mapping[str, Any]) -> dict[str, Any]:
    matchup = dict(contextual.get("opponent_specific_matchup") or {})
    network = dict(contextual.get("linkup_network") or {})
    relationships = [
        row
        for row in network.get("relationships") or []
        if _f(row.get("confidence")) > 0.0
    ]
    return {
        "OPPONENT-SPECIFIC MATCHUP": {
            "historical_meetings": matchup.get("historical_meetings"),
            "result_evidence": (matchup.get("result_process") or {}).get("result_evidence"),
            "process_evidence": (matchup.get("result_process") or {}).get("process_evidence"),
            "tactical_similarity": matchup.get("tactical_similarity"),
            "sample_size": matchup.get("sample_size"),
            "bayesian_confidence": matchup.get("sample_shrinkage"),
            "current_relevance": matchup.get("tactical_similarity"),
            "classification": matchup.get("classification"),
        },
        "LINK-UP / COMBINATION NETWORK": {
            "pairwise_links": relationships,
            "relationships": relationships,
            "relationship_count": len(relationships),
            "multi_player_chains": [
                row
                for row in network.get("multi_player_chains") or []
                if _f(row.get("confidence")) > 0.0
            ],
            "chain_count": len(
                [
                    row
                    for row in network.get("multi_player_chains") or []
                    if _f(row.get("confidence")) > 0.0
                ]
            ),
            "insufficient_pairs_suppressed": True,
        },
    }
