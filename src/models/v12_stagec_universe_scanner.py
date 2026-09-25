from __future__ import annotations

"""Universe-wide Stage C candidate scanner.

This module owns candidate generation only. It consumes Stage A multi-window
evidence, Stage B shadow evidence and existing canonical projection surfaces.
It does not own final ranking, transfer decisions, P1.7, P1.2B or Monte Carlo.
"""

from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.models.v12_multiwindow_form import build_multiwindow_form_snapshot
from src.models.v12_stageb_evidence import attach_stageb_shadow_evidence


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "v12_stagec_universe_scanner.json"
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
POSITIVE_SIGNALS = frozenset(
    {
        "BREAKOUT",
        "POSITIVE_REGRESSION",
        "ROLE_GAIN",
        "MINUTES_GAIN",
        "DEFCON_VALUE",
    }
)
NEGATIVE_SIGNALS = frozenset(
    {
        "NEGATIVE_REGRESSION",
        "ROLE_LOSS",
        "MINUTES_RISK",
    }
)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "V12_STAGEC_UNIVERSE_SCANNER_V1":
        raise RuntimeError("unexpected Stage C scanner contract")
    return payload


def _f(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _i(value: Any) -> int | None:
    value = _f(value)
    return None if value is None else int(value)


def _position(player: Mapping[str, Any]) -> str:
    raw = str(player.get("position") or "").upper().strip()
    if raw in {"GK", "DEF", "MID", "FWD"}:
        return raw
    return POSITIONS.get(_i(player.get("element_type")) or 0, "UNKNOWN")


def _price_m(player: Mapping[str, Any]) -> float | None:
    raw = _f(player.get("now_cost"))
    if raw is None:
        raw = _f(player.get("price"))
    if raw is None or raw <= 0:
        return None
    return round(raw / 10.0, 2) if raw >= 20.0 else round(raw, 2)


def _ownership(player: Mapping[str, Any]) -> float | None:
    for key in (
        "ownership_pct",
        "selected_by_percent",
        "official_ownership",
        "ownership",
    ):
        value = _f(player.get(key))
        if value is not None:
            return value
    official = player.get("official_current")
    if isinstance(official, Mapping):
        return _f(official.get("selected_by_percent"))
    return None


def _window(form: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    return ((form.get("windows") or {}).get(name) or {})


def _metric_node(form: Mapping[str, Any], window: str, metric: str) -> Mapping[str, Any]:
    return ((_window(form, window).get("metrics") or {}).get(metric) or {})


def _metric_value(form: Mapping[str, Any], window: str, metric: str) -> float | None:
    return _f(_metric_node(form, window, metric).get("value"))


def _metric_per90(form: Mapping[str, Any], window: str, metric: str) -> float | None:
    return _f(_metric_node(form, window, metric).get("per90"))


def _derived_value(form: Mapping[str, Any], window: str, metric: str) -> float | None:
    return _f(
        (((_window(form, window).get("derived") or {}).get(metric) or {}).get("value"))
    )


def _trajectory_value(form: Mapping[str, Any], key: str) -> float | None:
    return _f(
        (((form.get("signals") or {}).get("trajectory_components") or {}).get(key) or {}).get(
            "value"
        )
    )


def _regression_per90(form: Mapping[str, Any], window: str, key: str) -> float | None:
    return _f(
        ((((form.get("regression") or {}).get(window) or {}).get(key) or {}).get("per90"))
    )


def _active_stage_a_signal(form: Mapping[str, Any], key: str) -> bool:
    return bool((((form.get("signals") or {}).get(key) or {}).get("active")))


def _sample_confidence(form: Mapping[str, Any]) -> float:
    recent = _f((_window(form, "L3").get("confidence") or {}).get("score")) or 0.0
    season = _f((_window(form, "SEASON").get("confidence") or {}).get("score")) or 0.0
    return round(min(recent, season), 4)


def _horizon_mean(player: Mapping[str, Any], horizon: int) -> float | None:
    horizons = player.get("horizons")
    if isinstance(horizons, Mapping):
        node = horizons.get(str(horizon))
        if isinstance(node, Mapping):
            value = _f(node.get("mean"))
            if value is not None:
                return value
        value = _f(node)
        if value is not None:
            return value

    rows = [
        row
        for row in (player.get("xpts_by_gw") or [])
        if isinstance(row, Mapping)
    ]
    if not rows:
        return None
    means: list[float] = []
    for row in rows[:horizon]:
        value = _f(row.get("mean"))
        if value is None:
            return None
        means.append(value)
    if len(means) < horizon:
        return None
    return round(sum(means), 6)


def _fixture_horizons(player: Mapping[str, Any]) -> dict[str, float | None]:
    return {str(h): _horizon_mean(player, h) for h in (1, 2, 3, 5)}


def _fixture_swing(horizons: Mapping[str, Any], cfg: Mapping[str, Any]) -> tuple[bool, str | None, float | None]:
    h3 = _f(horizons.get("3"))
    h5 = _f(horizons.get("5"))
    if h3 is None or h5 is None or h5 <= 0:
        return False, None, None
    recent_per_gw = h3 / 3.0
    five_per_gw = h5 / 5.0
    if five_per_gw <= 0:
        return False, None, None
    ratio = recent_per_gw / five_per_gw
    positive = _f(cfg.get("fixture_positive_ratio")) or 1.1
    negative = _f(cfg.get("fixture_negative_ratio")) or 0.9
    if ratio >= positive:
        return True, "POSITIVE", round(ratio, 6)
    if ratio <= negative:
        return True, "NEGATIVE", round(ratio, 6)
    return False, None, round(ratio, 6)


def _first_fixture(player: Mapping[str, Any]) -> Mapping[str, Any]:
    for gw_row in player.get("xpts_by_gw") or []:
        if not isinstance(gw_row, Mapping):
            continue
        fixtures = [x for x in gw_row.get("fixtures") or [] if isinstance(x, Mapping)]
        if fixtures:
            return fixtures[0]
    return {}


def _cs_outlook(player: Mapping[str, Any]) -> float | None:
    fixture = _first_fixture(player)
    events = fixture.get("events")
    if isinstance(events, Mapping):
        clean = events.get("clean_sheet")
        if isinstance(clean, Mapping):
            for key in ("P_points_awarded", "probability", "p_clean_sheet"):
                value = _f(clean.get(key))
                if value is not None:
                    return value
    for key in ("clean_sheet_probability", "p_clean_sheet"):
        value = _f(fixture.get(key))
        if value is not None:
            return value
    return None


def _xmins(player: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(player.get("xmins") or {})
    return {
        "expected_minutes": _f(raw.get("expected_minutes")),
        "p_start": _f(raw.get("start_probability")),
        "p_dnp": _f(raw.get("dnp_probability")),
        "confidence": raw.get("confidence"),
    }


def _role(player: Mapping[str, Any]) -> dict[str, Any]:
    stageb = dict(player.get("stageb_evidence") or {})
    role_duty = dict(stageb.get("role_duty") or {})
    derived = dict(role_duty.get("DERIVED") or {})
    actual = dict(derived.get("actual_tactical_role") or {})
    value = actual.get("value")
    if value is None:
        tactical = player.get("tactical_role")
        if isinstance(tactical, Mapping):
            value = tactical.get("profile") or tactical.get("role")
    return {
        "actual": value,
        "classification": actual.get("class") or ("DERIVED" if value else None),
        "nominal": (
            (((role_duty.get("FACT") or {}).get("nominal_position") or {}).get("value"))
            or _position(player)
        ),
    }


def _underlying_window(form: Mapping[str, Any], window: str) -> dict[str, Any]:
    keys = (
        "xgi",
        "xg",
        "npxg",
        "xa",
        "shots",
        "shots_in_box",
        "shots_on_target",
        "box_touches",
        "key_passes",
        "chances_created",
    )
    return {
        key: {
            "total": _metric_value(form, window, key),
            "per90": _metric_per90(form, window, key),
            "availability": _metric_node(form, window, key).get("availability"),
        }
        for key in keys
    }


def _actual_returns(form: Mapping[str, Any], window: str) -> dict[str, Any]:
    goals = _metric_value(form, window, "goals")
    assists = _metric_value(form, window, "assists")
    gi = goals + assists if goals is not None and assists is not None else None
    return {"goals": goals, "assists": assists, "goal_involvements": gi}


def _defcon(player: Mapping[str, Any]) -> dict[str, Any]:
    stageb = dict(player.get("stageb_evidence") or {})
    raw = dict(stageb.get("defcon") or {})
    return {
        "DEFCON_EV": _f(raw.get("DEFCON_EV")),
        "projected_hit_probability": _f(raw.get("projected_hit_probability")),
        "hit_rate": _f(raw.get("hit_rate")),
        "eligible_starts": raw.get("eligible_starts"),
        "confidence": raw.get("confidence"),
    }


def _hidden_gem(
    *,
    player: Mapping[str, Any],
    form: Mapping[str, Any],
    horizons: Mapping[str, Any],
    xmins: Mapping[str, Any],
    fixture_ratio: float | None,
    cfg: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    position = _position(player)
    ownership = _ownership(player)
    price = _price_m(player)
    l3_xgi = _metric_per90(form, "L3", "xgi")
    gap = _regression_per90(form, "L3", "gi_minus_xgi")
    h5 = _f(horizons.get("5"))
    min_xgi_by_pos = dict(cfg.get("minimum_l3_xgi_per90_by_position") or {})
    min_xgi = _f(min_xgi_by_pos.get(position))
    value = h5 / price if h5 is not None and price and price > 0 else None

    checks = {
        "low_ownership": ownership is not None and ownership <= (_f(cfg.get("max_ownership_pct")) or 10.0),
        "secure_minutes": (
            (_f(xmins.get("expected_minutes")) or 0.0) >= (_f(cfg.get("minimum_xmins")) or 70.0)
            and (_f(xmins.get("p_start")) or 0.0) >= (_f(cfg.get("minimum_p_start")) or 0.75)
        ),
        "strong_underlying": (
            l3_xgi is not None
            and min_xgi is not None
            and l3_xgi >= min_xgi
        ),
        "returns_lagging": (
            gap is not None
            and gap <= (_f(cfg.get("maximum_recent_gi_minus_xgi_per90")) or -0.12)
        ),
        "value": (
            value is not None
            and value >= (_f(cfg.get("minimum_five_gw_xpts_per_million")) or 2.4)
        ),
        "fixture_support": (
            fixture_ratio is None
            or fixture_ratio >= (_f(cfg.get("minimum_fixture_support_ratio")) or 0.95)
        ),
    }
    active = all(checks.values())
    reasons = [key for key, ok in checks.items() if ok] if active else []
    return active, reasons


def _candidate(
    player: Mapping[str, Any],
    form: Mapping[str, Any],
    *,
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = dict(cfg.get("signal_thresholds") or {})
    xmins = _xmins(player)
    horizons = _fixture_horizons(player)
    fixture_active, fixture_direction, fixture_ratio = _fixture_swing(horizons, thresholds)
    start_delta = _trajectory_value(form, "start_share_delta")
    minutes_ratio = _trajectory_value(form, "minutes_per_appearance_ratio")
    confidence = _sample_confidence(form)
    minimum_confidence = _f(cfg.get("minimum_sample_confidence")) or 0.45

    signals: dict[str, dict[str, Any]] = {}

    def add(name: str, active: bool, *, direction: str | None = None, why: Sequence[str] = ()) -> None:
        signals[name] = {
            "active": bool(active),
            "direction": direction,
            "why": list(why) if active else [],
        }

    add(
        "BREAKOUT",
        _active_stage_a_signal(form, "BREAKOUT"),
        direction="POSITIVE",
        why=("Stage A sample-aware breakout signal is active",),
    )
    add(
        "POSITIVE_REGRESSION",
        _active_stage_a_signal(form, "POSITIVE_REGRESSION_WATCH"),
        direction="POSITIVE",
        why=("recent actual GI trails xGI while opportunity remains supported",),
    )
    add(
        "NEGATIVE_REGRESSION",
        _active_stage_a_signal(form, "NEGATIVE_REGRESSION_WATCH"),
        direction="NEGATIVE",
        why=("recent actual GI materially exceeds xGI without stronger underlying",),
    )

    role_gain = (
        confidence >= minimum_confidence
        and (
            (start_delta is not None and start_delta >= (_f(thresholds.get("role_gain_start_share_delta")) or 0.2))
            or (minutes_ratio is not None and minutes_ratio >= (_f(thresholds.get("minutes_gain_ratio")) or 1.15))
        )
    )
    role_loss = (
        confidence >= minimum_confidence
        and (
            (start_delta is not None and start_delta <= (_f(thresholds.get("role_loss_start_share_delta")) or -0.2))
            or (minutes_ratio is not None and minutes_ratio <= (_f(thresholds.get("minutes_loss_ratio")) or 0.8))
        )
    )
    add(
        "ROLE_GAIN",
        role_gain,
        direction="POSITIVE",
        why=("recent start share/minutes materially improved versus season",),
    )
    add(
        "ROLE_LOSS",
        role_loss,
        direction="NEGATIVE",
        why=("recent start share/minutes materially declined versus season",),
    )

    minutes_gain = (
        role_gain
        and (_f(xmins.get("expected_minutes")) or 0.0) >= (_f(thresholds.get("secure_xmins")) or 70.0)
        and (_f(xmins.get("p_start")) or 0.0) >= (_f(thresholds.get("secure_p_start")) or 0.75)
    )
    minutes_risk = (
        (_f(xmins.get("expected_minutes")) is not None and (_f(xmins.get("expected_minutes")) or 0.0) < (_f(thresholds.get("risk_xmins")) or 60.0))
        or (_f(xmins.get("p_start")) is not None and (_f(xmins.get("p_start")) or 0.0) < (_f(thresholds.get("risk_p_start")) or 0.65))
        or role_loss
    )
    add(
        "MINUTES_GAIN",
        minutes_gain,
        direction="POSITIVE",
        why=("P1.1 xMins/P(start) secure and recent usage improved",),
    )
    add(
        "MINUTES_RISK",
        minutes_risk,
        direction="NEGATIVE",
        why=("P1.1 minutes security or recent role usage is below the Stage C screen",),
    )

    defcon = _defcon(player)
    defcon_value = (
        _f(defcon.get("DEFCON_EV")) is not None
        and (_f(defcon.get("DEFCON_EV")) or 0.0) >= (_f(thresholds.get("defcon_ev")) or 0.8)
        and _f(defcon.get("projected_hit_probability")) is not None
        and (_f(defcon.get("projected_hit_probability")) or 0.0) >= (_f(thresholds.get("defcon_hit_probability")) or 0.4)
    )
    add(
        "DEFCON_VALUE",
        defcon_value,
        direction="POSITIVE",
        why=("Stage B DEFCON_EV and hit probability clear the candidate-generation screen",),
    )
    add(
        "FIXTURE_SWING",
        fixture_active,
        direction=fixture_direction,
        why=(
            f"3GW per-GW projection vs 5GW per-GW ratio={fixture_ratio}"
            if fixture_ratio is not None
            else "projected horizon swing",
        ),
    )

    hidden, hidden_reasons = _hidden_gem(
        player=player,
        form=form,
        horizons=horizons,
        xmins=xmins,
        fixture_ratio=fixture_ratio,
        cfg=dict(cfg.get("hidden_gem") or {}),
    )

    weights = dict(cfg.get("material_signal_weights") or {})
    material_score = 0.0
    for name, node in signals.items():
        if node["active"]:
            material_score += _f(weights.get(name)) or 0.0
    if hidden:
        material_score += _f(weights.get("HIDDEN_GEM")) or 0.0

    active_signals = [name for name, node in signals.items() if node["active"]]
    positive = [
        name
        for name in active_signals
        if name in POSITIVE_SIGNALS
        or (
            name == "FIXTURE_SWING"
            and signals[name].get("direction") == "POSITIVE"
        )
    ]
    negative = [
        name
        for name in active_signals
        if name in NEGATIVE_SIGNALS
        or (
            name == "FIXTURE_SWING"
            and signals[name].get("direction") == "NEGATIVE"
        )
    ]
    why = [
        reason
        for name in active_signals
        for reason in signals[name].get("why") or []
    ]
    if hidden:
        why.append("hidden-gem screen: " + ", ".join(hidden_reasons))

    return {
        "element": _i(player.get("element") or player.get("id")),
        "name": player.get("name") or player.get("web_name"),
        "team_id": _i(player.get("team_id") or player.get("team")),
        "position": _position(player),
        "price_m": _price_m(player),
        "ownership_pct": _ownership(player),
        "actual_returns": {
            "L3": _actual_returns(form, "L3"),
            "L5": _actual_returns(form, "L5"),
            "SEASON": _actual_returns(form, "SEASON"),
        },
        "underlying": {
            "L3": _underlying_window(form, "L3"),
            "L5": _underlying_window(form, "L5"),
            "SEASON": _underlying_window(form, "SEASON"),
        },
        "regression": {
            "L3_gi_minus_xgi_per90": _regression_per90(form, "L3", "gi_minus_xgi"),
            "L5_gi_minus_xgi_per90": _regression_per90(form, "L5", "gi_minus_xgi"),
        },
        "trajectory": {
            "xgi_per90_ratio": _trajectory_value(form, "xgi_per90_ratio"),
            "xg_per90_ratio": _trajectory_value(form, "xg_per90_ratio"),
            "xa_per90_ratio": _trajectory_value(form, "xa_per90_ratio"),
            "shots_per90_ratio": _trajectory_value(form, "shots_per90_ratio"),
            "shots_in_box_per90_ratio": _trajectory_value(form, "shots_in_box_per90_ratio"),
            "sot_rate_ratio": _trajectory_value(form, "sot_rate_ratio"),
            "box_touches_per90_ratio": _trajectory_value(form, "box_touches_per90_ratio"),
            "key_passes_per90_ratio": _trajectory_value(form, "key_passes_per90_ratio"),
            "chances_created_per90_ratio": _trajectory_value(form, "chances_created_per90_ratio"),
            "start_share_delta": start_delta,
            "minutes_per_appearance_ratio": minutes_ratio,
        },
        "xmins": xmins,
        "role": _role(player),
        "fixture_horizon": horizons,
        "fixture_swing_ratio": fixture_ratio,
        "cs_outlook": _cs_outlook(player),
        "defcon": defcon,
        "signals": signals,
        "active_signals": active_signals,
        "positive_signals": positive,
        "negative_signals": negative,
        "hidden_gem": hidden,
        "sample_confidence": confidence,
        "material_score_internal": round(material_score, 6),
        "material": bool(active_signals or hidden),
        "why_flagged": why,
    }


def prepare_stagec_projection_copy(
    projections: Mapping[str, Any],
    *,
    bootstrap: Mapping[str, Any],
    match_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Attach Stage B only to a copy; canonical projection input is untouched."""
    candidate = deepcopy(dict(projections))
    attach_stageb_shadow_evidence(
        candidate,
        bootstrap=bootstrap,
        match_rows=match_rows,
        universe_rows=match_rows,
        enabled=True,
    )
    return candidate


def build_universe_scan(
    *,
    projections: Mapping[str, Any],
    multiwindow_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    cfg = load_config()
    form_map = dict(multiwindow_snapshot.get("players") or {})
    projection_rows = [
        dict(row)
        for row in projections.get("players") or []
        if isinstance(row, Mapping)
    ]
    candidates: list[dict[str, Any]] = []
    unavailable_form = 0
    for player in projection_rows:
        element = _i(player.get("element") or player.get("id"))
        if element is None or element <= 0:
            continue
        form = dict(form_map.get(str(element)) or {})
        if not form or str(form.get("status") or "") not in {"AVAILABLE", "NO_APPEARANCES"}:
            unavailable_form += 1
        candidate = _candidate(player, form, cfg=cfg)
        candidates.append(candidate)

    candidates.sort(
        key=lambda row: (
            -float(row.get("material_score_internal") or 0.0),
            int(row.get("element") or 10**9),
        )
    )
    material = [row for row in candidates if row.get("material")]
    hidden = [row for row in material if row.get("hidden_gem")]
    counts = {
        name: sum(
            bool((row.get("signals") or {}).get(name, {}).get("active"))
            for row in candidates
        )
        for name in (
            "BREAKOUT",
            "POSITIVE_REGRESSION",
            "NEGATIVE_REGRESSION",
            "ROLE_GAIN",
            "ROLE_LOSS",
            "MINUTES_GAIN",
            "MINUTES_RISK",
            "DEFCON_VALUE",
            "FIXTURE_SWING",
        )
    }
    counts["HIDDEN_GEM"] = len(hidden)

    feed = [
        {
            "element": row.get("element"),
            "position": row.get("position"),
            "signals": list(row.get("active_signals") or []),
            "horizons": [1, 2, 3, 5],
            "consumer": (
                "EXISTING_V12_PLAYER_COMPARATOR_AND_PACKAGE_PIPELINE"
            ),
        }
        for row in material
    ]

    return {
        "contract": "V12_STAGEC_UNIVERSE_SCAN_V1",
        "full_universe_count": len(projection_rows),
        "scanned_count": len(candidates),
        "material_candidate_count": len(material),
        "hidden_gem_count": len(hidden),
        "multiwindow_unavailable_count": unavailable_form,
        "signal_counts": counts,
        "material_candidates": material,
        "evaluation_feed": feed,
        "governance": {
            "full_universe_scanned": True,
            "internal_material_score_is_candidate_generation_only": True,
            "final_v12_ranking_unchanged": True,
            "transfer_horizons": [1, 2, 3, 5],
            "gate0_preserved": True,
            "p1_1_preserved": True,
            "p1_3_preserved": True,
            "p1_6_preserved": True,
            "p1_7_preserved": True,
            "p1_2b_preserved": True,
            "monte_carlo_preserved": True,
            "mini_league_preserved": True,
            "xgstat_policy": "MANUAL_VALIDATION_ONLY",
            "external_opinion_is_not_factual_authority": True,
        },
    }


def build_stagec_from_canonical_inputs(
    *,
    projections: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
    match_rows: Sequence[Mapping[str, Any]],
    season: str | None = None,
) -> dict[str, Any]:
    """Convenience orchestration for the bounded Stage C shadow path."""
    multiwindow = build_multiwindow_form_snapshot(match_rows, season=season)
    candidate_projection = prepare_stagec_projection_copy(
        projections,
        bootstrap=bootstrap,
        match_rows=match_rows,
    )
    scan = build_universe_scan(
        projections=candidate_projection,
        multiwindow_snapshot=multiwindow,
    )
    return {
        "contract": "V12_STAGEC_CANONICAL_INPUT_BRIDGE_V1",
        "scan": scan,
        "multiwindow": multiwindow,
        "canonical_projection_mutated": False,
        "candidate_projection_stageb_attached": True,
        "decision_owner_created": False,
    }
