from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.utils import CONFIG, read_json

XMINS_CONTRACT_VALIDATION = read_json(CONFIG / "intelligence" / "xmins_v2.json", {}).get("contract_validation") or {}
XMINS_PROBABILITY_SUM_TOLERANCE = float(XMINS_CONTRACT_VALIDATION["probability_sum_tolerance"])
XMINS_EXPECTED_MINUTES_IDENTITY_TOLERANCE = float(XMINS_CONTRACT_VALIDATION["expected_minutes_identity_tolerance"])


DEFENSIVE_POSITIONS = {"GK", "DEF"}
DEFENSIVE_COMPONENTS = ("clean_sheet", "saves", "defensive_contribution", "bonus")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _target_gw(value: Any) -> int | None:
    try:
        gw = int(value)
        return gw if gw > 0 else None
    except (TypeError, ValueError):
        return None


def resolve_locked_chip_context(
    lock: dict[str, Any],
    chips: dict[str, Any],
    planning_gw: int,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Resolve a planning chip without allowing an earlier-GW lock to leak forward."""
    chip_cfg = policy.get("chip_governance") or {}
    planning_gw = int(planning_gw)
    override_target_gw = _target_gw(lock.get("target_gw"))
    target_is_explicit = override_target_gw is not None
    override_matches_planning = (not target_is_explicit) or override_target_gw == planning_gw

    active: str | None = None
    wildcard_requested = bool(
        chip_cfg.get("wildcard_context_from_locked_authority")
        and lock.get("wildcard_active")
        and lock.get("authoritative_phase") == "pre_deadline_wc"
    )
    if wildcard_requested and override_matches_planning:
        active = "wildcard"

    used_this_gw: list[str] = []
    for row in chips.get("used") or []:
        if int(row.get("event") or -1) == planning_gw:
            name = row.get("name")
            if name:
                used_this_gw.append(str(name))

    active_count = len(used_this_gw) + (1 if active and active not in used_this_gw else 0)
    stale_override_suppressed = bool(wildcard_requested and target_is_explicit and not override_matches_planning)
    return {
        "planning_gw": planning_gw,
        "active_chip": active,
        "used_this_gw": used_this_gw,
        "single_chip_rule_respected": active_count <= 1,
        "auto_activate_chip": bool(chip_cfg.get("auto_activate_chip", False)),
        "override_target_gw": override_target_gw,
        "override_matches_planning_gw": override_matches_planning,
        "stale_chip_override_suppressed": stale_override_suppressed,
        "governance": {
            "planning_chip_is_gw_scoped": True,
            "stale_override_cannot_become_active": True,
            "historical_chip_state_is_not_rewritten": True,
            "legacy_untargeted_lock_behavior_preserved": True,
        },
    }


def projection_signature(projections: dict[str, Any]) -> dict[int, tuple[tuple[int, float], ...]]:
    """Capture decision-bearing xPts before advisory tactical enrichment."""
    signature: dict[int, tuple[tuple[int, float], ...]] = {}
    for player in projections.get("players") or []:
        element = int(player.get("element") or -1)
        rows = tuple(
            (int(row.get("gw") or -1), round(_f(row.get("mean")), 6))
            for row in player.get("xpts_by_gw") or []
        )
        signature[element] = rows
    return signature


def assert_projection_signature_unchanged(
    before: dict[int, tuple[tuple[int, float], ...]],
    after: dict[str, Any],
) -> None:
    current = projection_signature(after)
    if current != before:
        changed = sorted(set(before) | set(current))
        changed = [element for element in changed if before.get(element) != current.get(element)]
        raise RuntimeError(
            "tactical enrichment mutated decision-bearing xPts; double-count guard failed "
            f"for elements={changed[:10]}"
        )


def build_position_projection_diagnostics(projections: dict[str, Any]) -> dict[str, Any]:
    """Non-mutating ablation summary of the active projection composition by position."""
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "players": set(),
            "fixtures": 0,
            "xpts": 0.0,
            "appearance": 0.0,
            "attack": 0.0,
            "clean_sheet": 0.0,
            "saves": 0.0,
            "defensive_contribution": 0.0,
            "bonus": 0.0,
        }
    )
    for player in projections.get("players") or []:
        position = str(player.get("position") or "UNKNOWN")
        bucket = buckets[position]
        bucket["players"].add(int(player.get("element") or -1))
        for gw_row in player.get("xpts_by_gw") or []:
            for fixture in gw_row.get("fixtures") or []:
                components = fixture.get("components") or {}
                mean = _f(fixture.get("mean"))
                bucket["fixtures"] += 1
                bucket["xpts"] += mean
                for name in ("appearance", "attack", *DEFENSIVE_COMPONENTS):
                    bucket[name] += _f(components.get(name))

    positions: dict[str, Any] = {}
    for position, bucket in sorted(buckets.items()):
        fixture_count = int(bucket["fixtures"])
        total = _f(bucket["xpts"])
        defensive_total = sum(_f(bucket[name]) for name in DEFENSIVE_COMPONENTS)
        divisor = max(1, fixture_count)
        ablation = {
            f"without_{name}": round((total - _f(bucket[name])) / divisor, 4)
            for name in DEFENSIVE_COMPONENTS
        }
        positions[position] = {
            "player_count": len(bucket["players"]),
            "fixture_rows": fixture_count,
            "mean_xpts_per_fixture": round(total / divisor, 4),
            "mean_components_per_fixture": {
                name: round(_f(bucket[name]) / divisor, 4)
                for name in ("appearance", "attack", *DEFENSIVE_COMPONENTS)
            },
            "defensive_component_share": round(defensive_total / total, 4) if total > 0 else 0.0,
            "ablation_mean_xpts_per_fixture": ablation,
            "defensive_position": position in DEFENSIVE_POSITIONS,
        }

    return {
        "status": "READY" if positions else "NO_FIXTURE_SAMPLE",
        "comparison_authority": "REALIZED_HISTORICAL_VALIDATION_NOT_V4",
        "mutates_xpts": False,
        "positions": positions,
        "guardrails": {
            "tactical_enrichment_may_not_mutate_xpts": True,
            "clean_sheet_probability_consumed_once_in_projection_components": True,
            "v4_is_not_calibration_truth": True,
            "diagnostics_are_observational_until_settled_validation_exists": True,
        },
    }


def enrich_xmins_contract(out: dict[str, Any]) -> dict[str, Any]:
    """Expose the existing probability decomposition explicitly without changing its model."""
    start = _f(out.get("start_probability"))
    bench = _f(out.get("bench_probability"))
    dnp = _f(out.get("dnp_probability"))
    probability_sum = start + bench + dnp
    if abs(probability_sum - 1.0) > XMINS_PROBABILITY_SUM_TOLERANCE:
        raise RuntimeError(f"xMins probability decomposition invalid: sum={probability_sum:.6f}")

    start_minutes = _f(out.get("starter_minutes_if_start"))
    bench_minutes = _f(out.get("bench_minutes_if_used"))
    expected = start * start_minutes + bench * bench_minutes
    published = _f(out.get("expected_minutes"))
    if abs(expected - published) > XMINS_EXPECTED_MINUTES_IDENTITY_TOLERANCE:
        raise RuntimeError(
            "xMins expected_minutes is not derived from explicit start/bench probabilities: "
            f"derived={expected:.3f} published={published:.3f}"
        )

    out["expected_minutes_if_start"] = round(start_minutes, 1)
    out["overall_availability"] = round(_f(out.get("availability")), 4)
    out["probability_sum"] = round(probability_sum, 4)
    out["expected_minutes_components"] = {
        "start_minutes_contribution": round(start * start_minutes, 2),
        "bench_minutes_contribution": round(bench * bench_minutes, 2),
        "dnp_minutes_contribution": 0.0,
    }
    out.setdefault("governance", {}).update({
        "expected_minutes_derived_from_explicit_probabilities": True,
        "start_bench_dnp_probabilities_are_mutually_exclusive": True,
        "availability_published_separately": True,
        "compatibility_expected_minutes_preserved": True,
    })
    return out
