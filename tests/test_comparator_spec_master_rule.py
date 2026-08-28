from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_master_rule_is_multi_gw_not_latest_points_chasing():
    policy = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())
    assert policy["horizons"] == [1, 2, 3, 5]
    assert policy["governance"]["one_match_haul_is_trigger_not_buy"] is True
    assert policy["governance"]["positive_projected_edge_is_not_sufficient_alone"] is True
