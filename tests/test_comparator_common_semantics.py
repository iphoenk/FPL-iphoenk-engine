from __future__ import annotations

import inspect

from src.engines import owned_challenger_comparator as comparator


def test_common_output_semantics_cover_multi_engine_contract():
    text = inspect.getsource(comparator.build)
    for field in (
        "player_out", "player_in", "challenger_type", "comparison_timestamp", "planning_gw",
        "horizon_1gw", "horizon_2gw", "horizon_3gw", "horizon_5gw", "fixture_by_fixture",
        "xpts_by_gw", "xmins_by_gw", "start_probability_by_gw", "tactical_matchup_by_gw",
        "rest_congestion_by_gw", "midweek_schedule", "international_context", "role_sustainability",
        "performance_signal", "raw_gain_2gw", "raw_gain_3gw", "raw_gain_5gw", "structural_cost",
        "opportunity_cost", "net_transfer_value", "affordability", "confidence", "decision",
        "decision_reasons", "decision_risks", "reversal_triggers", "data_quality",
    ):
        assert field in text
