from src.engines.visible_mode_presentation_locks import (
    load_deadline_final_presentation_lock,
    load_match_presentation_lock,
    validate_deadline_final_presentation_lock,
    validate_match_presentation_lock,
)


def test_deadline_final_presentation_lock_is_exact():
    cfg=load_deadline_final_presentation_lock()
    assert validate_deadline_final_presentation_lock(cfg) == []
    assert cfg["header_additions"] == ["Official deadline","Countdown","Checkpoint","Decision state"]


def test_deadline_overlay_exact_tables_and_s15b_protection():
    overlay=load_deadline_final_presentation_lock()["deadline_overlay"]
    assert overlay["S05"]["tables"][0]["columns"] == ["Player","News","Availability impact","Evidence tier","As of","Decision impact"]
    assert overlay["S05"]["tables"][1]["columns"] == ["Player","Predicted status","Evidence tier","Confidence","Decision consequence"]
    assert overlay["S14"]["tables"][0]["columns"] == ["Route","Legal","Affordable","1GW","3GW","5GW","P>HOLD","Value of waiting","Reversal / Abort","Action"]
    assert overlay["S15B"]["extra_tables_forbidden"] is True
    assert overlay["S18"]["tables"][0]["rows"] == ["NOW","NEXT","TRIGGER TO ACT","LATEST SAFE DECISION POINT","COST OF WAITING","ABORT / REVERSAL","BEST ALTERNATIVE"]


def test_final_gw_lock_package_is_18_rows_before_alternatives():
    lock=load_deadline_final_presentation_lock()["final_overlay"]["gw_lock_package"]
    assert lock["table_columns"] == ["Field","Value"]
    assert lock["rows_exact"] == 18
    assert len(lock["rows"]) == 18
    assert lock["rows"][0] == "Target GW"
    assert lock["rows"][-1] == "Canonical authority version"
    assert lock["alternatives_below_lock_package_only"] is True


def test_match_presentation_lock_is_exact():
    cfg=load_match_presentation_lock()
    assert validate_match_presentation_lock(cfg) == []
    assert cfg["section_order"] == [f"MATCH{i}" for i in range(1,14)]


def test_match_visible_tables_cover_all_structured_sections():
    sections=load_match_presentation_lock()["sections"]
    assert sections["MATCH2"]["tables"][0]["columns"] == ["Player","Pos","Club","Match status"]
    assert sections["MATCH4"]["tables"][0]["columns"] == ["Slot","Player"]
    assert sections["MATCH8"]["tables"][0]["columns"] == ["Player","Event","Detail","Match status","Decision implication"]
    assert sections["MATCH9"]["tables"][0]["columns"] == ["Player","Club","Signal","Evidence","Sustainable / noisy","OUR15 / next-opponent implication"]
    assert sections["MATCH11"]["tables"][0]["columns"] == ["Player / Team","Learning","Evidence","Next-GW implication","Action state"]
    assert "element_id" not in sections["MATCH6"]["tables"][0]["columns"]


def test_match_icon_live_keeps_exposure_and_rivals_separate():
    tables=load_match_presentation_lock()["sections"]["MATCH10"]["tables"]
    assert tables[0]["name"] == "Material player exposure"
    assert tables[1]["name"] == "Direct rival live consequence"
    assert tables[0]["columns"] == ["Player","Owned","Starter","Captain","Vice","EO","Live consequence"]
