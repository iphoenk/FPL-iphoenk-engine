from __future__ import annotations

from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def validate_config(config: dict[str, Any]) -> None:
    if config.get("model") != "adaptive_shrinkage_winsor_v1":
        raise RuntimeError("REC-02 robust attack rate model missing from projection config")
    tiers = config.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        raise RuntimeError("REC-02 robust rate tiers missing")
    previous_max: float | None = None
    saw_open_ended = False
    for tier in tiers:
        if not isinstance(tier, dict):
            raise RuntimeError("REC-02 robust rate tier must be an object")
        max_minutes = tier.get("max_minutes")
        shrink_minutes = _f(tier.get("shrink_minutes"), -1.0)
        cap_multiplier = _f(tier.get("upper_prior_multiplier"), -1.0)
        if shrink_minutes < 0 or cap_multiplier < 1.0:
            raise RuntimeError("REC-02 robust rate tier parameters invalid")
        if max_minutes is None:
            saw_open_ended = True
            continue
        current_max = _f(max_minutes, -1.0)
        if current_max <= 0 or (previous_max is not None and current_max <= previous_max):
            raise RuntimeError("REC-02 robust rate tier max_minutes must increase")
        previous_max = current_max
    if not saw_open_ended:
        raise RuntimeError("REC-02 robust rate tiers require an open-ended final tier")


def robust_attack_rate(
    player: dict[str, Any],
    cumulative_field: str,
    prior: float,
    config: dict[str, Any],
) -> tuple[float, str, dict[str, Any]]:
    """Bound early-season per-90 noise, then shrink it toward governed priors.

    This is native V5 code. It mirrors the accepted production statistical
    contract without importing V3 runtime or decision ownership.
    """
    validate_config(config)
    minutes = max(0.0, _f(player.get("minutes")))
    cumulative = max(0.0, _f(player.get(cumulative_field)))
    if minutes <= 0:
        return (
            max(0.0, prior),
            "position_or_historical_prior",
            {
                "minutes": 0.0,
                "raw_observed90": None,
                "bounded_observed90": None,
                "upper_rate90": None,
                "cap_multiplier": None,
                "shrink_minutes": None,
                "winsorized": False,
            },
        )

    tiers = list(config.get("tiers") or [])
    selected = next(
        (
            tier
            for tier in tiers
            if tier.get("max_minutes") is None or minutes <= float(tier.get("max_minutes"))
        ),
        tiers[-1],
    )
    cap_multiplier = max(1.0, _f(selected.get("upper_prior_multiplier"), 6.0))
    shrink_minutes = max(0.0, _f(selected.get("shrink_minutes"), 450.0))
    raw_observed = cumulative * 90.0 / minutes
    upper = max(max(0.0, prior) * cap_multiplier, _f(config.get("absolute_upper_rate90"), 1.5))
    bounded = clamp(raw_observed, 0.0, upper)
    blended = (bounded * minutes + max(0.0, prior) * shrink_minutes) / max(1e-6, minutes + shrink_minutes)
    winsorized = abs(bounded - raw_observed) > 1e-12
    source = "robust_observed_shrunk_to_prior" + ("_winsorized" if winsorized else "")
    return (
        max(0.0, blended),
        source,
        {
            "minutes": round(minutes, 1),
            "raw_observed90": round(raw_observed, 4),
            "bounded_observed90": round(bounded, 4),
            "upper_rate90": round(upper, 4),
            "cap_multiplier": cap_multiplier,
            "shrink_minutes": shrink_minutes,
            "winsorized": winsorized,
        },
    )
