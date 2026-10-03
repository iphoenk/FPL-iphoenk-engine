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
    assert tables[2]["name"] == "OUR15 exposure, LEAGUE"
    assert tables[2]["columns"] == [
        "Player","Owned","Starter","Bench","Captain","Vice","EO"
    ]
    assert tables[3]["name"] == "OUR15 exposure, RIVALS"
    assert tables[3]["columns"] == [
        "Player","Owned","Starter","Captain","EO"
    ]
    assert tables[4]["name"] == "OUR15 exposure, COMPETITIVE WINDOW"
    assert tables[4]["columns"] == [
        "Player","Owned","Starter","Bench","Captain","Vice","EO"
    ]
    assert tables[5]["name"] == "COMPETITIVE RIVALS"
    assert tables[5]["columns"] == [
        "Rank","Manager","Pts","Gap","Position vs us",
        "Squad overlap","XI overlap","Captain","Vice"
    ]
    assert tables[7]["columns"] == [
        "Player","Football rank","xPts","League C","League EO",
        "Competitive C","Competitive EO","Class"
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

def test_header_s15_s17_information_architecture_is_locked():
    contract = load_deep_presentation_lock()
    assert contract["header_order"] == [
        "FPL MASTER V12 — DEEP REPORT",
        "Planning GW",
        "Logical report slot",
        "Report",
        "Sections",
    ]
    assert contract["sections"]["S15"]["tables"][0]["columns"] == [
        "Evidence domain", "Quality", "Decision impact"
    ]
    assert contract["sections"]["S15"]["blocks"] == [
        "Overall evidence confidence",
        "Evidence limitations",
        "Decision implication",
        "PRIOR != CURRENT",
    ]
    assert contract["sections"]["S17"]["tables"][0]["columns"] == [
        "Plane", "Status"
    ]
    assert contract["sections"]["S17"]["blocks"] == [
        "Freshness",
        "Lineage",
        "Audit note (optional compact)",
    ]
    assert contract["ownership_matrix"]["Price evidence decision usability"] == "S15"
    assert contract["ownership_matrix"]["Price pipeline health"] == "S17"
    assert contract["ownership_matrix"]["Workflow/run IDs"] == "S17_AUDIT_ONLY"

