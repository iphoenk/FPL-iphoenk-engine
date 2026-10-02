from src.engines.v12_deep_presentation_lock import (
    load_deep_presentation_lock,
    validate_deep_presentation_lock_contract,
)


def test_locked_deep_presentation_contract_is_exact():
    contract = load_deep_presentation_lock()
    assert validate_deep_presentation_lock_contract(contract) == []


def test_s15b_tables_are_separate_and_columns_are_locked():
    contract = load_deep_presentation_lock()
    s15b = contract["sections"]["S15B"]
    assert s15b["forbid_table_merge"] is True
    tables = s15b["tables"]
    assert tables[2]["name"] == "OUR15 exposure, LEAGUE58"
    assert tables[2]["columns"] == [
        "Player","Owned","Starter","Bench","Captain","Vice","EO"
    ]
    assert tables[3]["name"] == "OUR15 exposure, RIVALS57"
    assert tables[3]["columns"] == [
        "Player","Owned","Starter","Captain","EO"
    ]
    assert tables[4]["name"] == "OUR15 exposure, DIRECT6"
    assert tables[4]["columns"] == [
        "Player","Owned","Starter","Bench","Captain","Vice","EO"
    ]


def test_rank20_and_watchlist_columns_are_locked():
    contract = load_deep_presentation_lock()
    assert contract["sections"]["S11"]["tables"][0]["columns"] == [
        "Player","Pos","£","xMins","Pstart","DNP","Score","Admit","Evidence"
    ]
    assert contract["sections"]["S12"]["tables"][0]["columns"] == [
        "#","Player","£","Progress","ETA"
    ]
    assert contract["sections"]["S13"]["tables"][0]["columns"] == [
        "#","Player","£","Progress","ETA"
    ]


def test_s16b_keeps_current_post_gw_lifecycle():
    contract = load_deep_presentation_lock()
    assert contract["sections"]["S16B"]["visibility"] == "lifecycle_controlled"
    assert "MATCH-BY-MATCH REVIEW" in contract["sections"]["S16B"]["lifecycle_rule"]
    assert "AFTER-GW REASSESSMENT" in contract["sections"]["S16B"]["lifecycle_rule"]
