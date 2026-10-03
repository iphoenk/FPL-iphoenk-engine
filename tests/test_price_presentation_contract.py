from src.engines.v12_price_presentation_lock import (
    load_price_presentation_lock,
    validate_price_presentation_lock,
)


def test_price_presentation_lock_is_exact():
    contract = load_price_presentation_lock()
    assert validate_price_presentation_lock(contract) == []
    assert contract["section_order"] == [f"PRICE{i}" for i in range(1, 13)]


def test_price_tables_are_locked_to_human_columns():
    sections = load_price_presentation_lock()["sections"]
    assert sections["PRICE2"]["tables"][0]["columns"] == [
        "Player","Pos","Market","Sell","Direction","Progress","ETA / Status","Decision impact"
    ]
    assert "element_id" not in sections["PRICE2"]["tables"][0]["columns"]
    assert sections["PRICE8"]["tables"][0]["columns"] == [
        "Route","OUT sell","IN price","Bank before","Affordable","Bank after","FT","Hit"
    ]
    assert sections["PRICE8"]["tables"][1]["columns"] == [
        "Route","Target +0.1","OUT -0.1","Combined","Route survives","1GW","3GW","5GW","Reversal risk"
    ]


def test_price_action_board_and_source_health_shapes_are_exact():
    sections = load_price_presentation_lock()["sections"]
    action = sections["PRICE10"]["tables"][0]
    assert action["rows"] == [
        "NOW","NEXT","TRIGGER TO ACT","LATEST SAFE DECISION POINT","COST OF WAITING","ABORT / REVERSAL"
    ]
    assert sections["PRICE11"]["tables"][0]["columns"] == ["Source","Status","As of"]
