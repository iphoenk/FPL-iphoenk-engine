import json
from pathlib import Path

LOCK = Path("config/delivery/v12_deep_presentation_lock.json")


def _lock():
    return json.loads(LOCK.read_text(encoding="utf-8"))


def test_locked_deep_presentation_has_exact_23_section_order():
    cfg = _lock()
    assert cfg["section_ids"] == [
        "S01","S02","S03","S04","S05","S06","S06B","S07","S08","S09",
        "S10","S11","S12","S13","S14","S14B","S15","S15B","S16","S16B",
        "S17","S18","S19",
    ]


def test_locked_deep_presentation_preserves_rank20_and_s15b_denominators():
    cfg = _lock()
    assert cfg["contracts"]["S11"]["rows_when_complete"] == 20
    assert cfg["contracts"]["S11"]["position_split"] == {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}
    assert cfg["contracts"]["S12"]["rows_when_complete"] == 20
    assert cfg["contracts"]["S13"]["rows_when_complete"] == 20
    assert cfg["contracts"]["S15B"]["population_display"] == "NUMERATOR_DENOMINATOR_PERCENT"
    assert cfg["contracts"]["S15B"]["scopes"] == ["LEAGUE", "RIVALS", "DIRECT6"]


def test_locked_deep_presentation_forbids_generic_machine_dump():
    cfg = _lock()
    forbidden = set(cfg["forbidden_visible_patterns"])
    assert "RAW_PYTHON_DICT" in forbidden
    assert "GENERIC_RECURSIVE_KEY_VALUE_DUMP" in forbidden
    assert "RAW_LONG_SNAKE_CASE_AS_PRIMARY_TEXT" in forbidden
