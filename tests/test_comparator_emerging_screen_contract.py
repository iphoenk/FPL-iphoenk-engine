from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_emerging_screen_has_minimum_legality_minutes_role_data_and_horizon_gates():
    cfg = json.loads((ROOT / "config" / "intelligence" / "owned_challenger_comparator.json").read_text())["emerging_screen"]
    assert cfg["minimum_expected_minutes"] > 0
    assert cfg["minimum_start_probability"] > 0
    assert cfg["maximum_dnp_probability"] < 1
    assert cfg["minimum_h5_points"] > 0
