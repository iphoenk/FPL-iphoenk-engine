from __future__ import annotations

"""Legacy projection API routed to the canonical V4 prediction model.

This module intentionally owns no xMins or points-scoring formula.  Production
prediction authority is ``src.models.v4_prediction``; these functions only adapt
older call shapes for compatibility.
"""

from src.models.v4_prediction import clamp, lineup_distribution, project_fixture


def _compat_context(player: dict, advanced: dict | None = None) -> dict:
    advanced = advanced or {}
    context: dict = {}
    if advanced.get("start_probability") is not None:
        start_probability = clamp(float(advanced["start_probability"]))
        context["current_start_rate"] = start_probability
        context["nailed_prior"] = start_probability
    if advanced.get("expected_minutes") is not None:
        context["current_minutes_rate"] = clamp(float(advanced["expected_minutes"]) / 90.0)
    if advanced.get("clean_sheet_probability") is not None:
        # Treat a legacy explicit probability as the canonical team prior rather
        # than recreating the clean-sheet scoring formula in this adapter.
        context["team_cs_prior"] = clamp(float(advanced["clean_sheet_probability"]), 0.15, 0.50)
    return context


def xmins_distribution(player: dict, advanced: dict | None = None):
    distribution = lineup_distribution(player, _compat_context(player, advanced))
    return {
        "start_probability": distribution["start_probability"],
        "bench_probability": distribution["bench_probability"],
        "dnp_probability": distribution["dnp_probability"],
        "expected_minutes": distribution["expected_minutes"],
    }


def simple_xmins(player: dict, advanced: dict | None = None):
    return xmins_distribution(player, advanced)["expected_minutes"] / 90.0


def project_points(player: dict, advanced: dict | None = None, fixture_difficulty: float = 3.0):
    advanced = advanced or {}
    fixture = {
        "event": None,
        "difficulty": float(fixture_difficulty),
        "home": True,
    }
    result = project_fixture(
        player,
        fixture,
        ctx=_compat_context(player, advanced),
        advanced=advanced,
    )
    return {
        "xmins": result["xmins"],
        "projected_points": result["xpts"],
        "components": result["components"],
        "model": "v4_compat_adapter_to_canonical_prediction",
        "confidence": "CANONICAL_V4_MODEL",
    }
