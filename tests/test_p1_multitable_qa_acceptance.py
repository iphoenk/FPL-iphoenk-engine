"""P1 visible evidence tables remain strict without double-counting OUR15."""

from src.engines.v12_deep_presentation_lock import (
    load_deep_presentation_lock,
    validate_deep_presentation_lock_contract,
    _rendered_tables,
)
from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines
from src.runtime_v6.domains.report_plane.visible_body_contract import (
    _s02_primary_visible_tables,
)


def _visible(section, content):
    lines, _ = _render_deep_visible_contract_lines(
        section_id=section, content=content,
        owned_ids=set(), owned_names={},
    )
    return "\n".join(lines)


def _our15_rows():
    return [
        {
            "player": f"P{index}",
            "position": "MID",
            "opponent": "EXAMPLE",
            "p_start": 0.83,
            "p_dnp": 0.09,
            "xmins": 70,
            "projection_1gw": 4.0,
            "projection_3gw": 12.0,
            "projection_5gw": 20.0,
            "p_start_evidence": {
                "source": "V12_PLAYER_MINUTES",
                "quality": "PRIOR_DOMINATED",
                "confidence": "LOW",
                "signal_count": 1,
                "model_probability_agrees": True,
            },
        }
        for index in range(15)
    ]


def test_complete_p1_schema_contract_accepts_all_additive_tables():
    assert validate_deep_presentation_lock_contract() == []
    expected = load_deep_presentation_lock()["sections"]
    assert [len(expected[sid]["tables"]) for sid in ("S02", "S08", "S10")] == [2, 3, 2]


def test_s02_has_one_roster_and_one_ordered_identity_matched_audit():
    rendered = _visible("S02", {"rows": _our15_rows()})
    tables = _rendered_tables(rendered)
    assert len(tables) == 2
    assert [len(table["rows"]) for table in tables] == [15, 15]
    count, ids, names, errors = _s02_primary_visible_tables(rendered)
    assert count == 15 and not ids
    assert len(names) == len(set(names)) == 15
    assert not errors
    assert names == [f"P{index}" for index in range(15)]


def test_s02_rejects_audit_player_identity_drift_not_a_false_30_player_squad():
    rendered = _visible("S02", {"rows": _our15_rows()})
    primary, secondary = rendered.split("#### PSTART EVIDENCE / DNP AUDIT", 1)
    secondary = secondary.replace("| P13 |", "| OTHER |", 1)
    count, _, names, errors = _s02_primary_visible_tables(
        primary + "#### PSTART EVIDENCE / DNP AUDIT" + secondary
    )
    assert count == 15 and len(names) == 15
    assert "VISIBLE_OUR15_AUDIT_IDENTITY_MISMATCH" in errors


def test_s08_has_existing_two_tables_plus_exact_five_row_tail_table():
    profiles = [{
        "player": f"P{index}", "football_rank": index + 1,
        "expected_points": 5.0, "p_start": 0.83, "xmins": 70,
        "p_blank": 0.4, "p_haul": 0.2, "p_ge_10": 0.2,
        "q90": 12.0, "p_ge_15": 0.06, "q75": 8.0,
        "variance": 20.0, "p_dnp": 0.09,
    } for index in range(5)]
    rendered = _visible("S08", {"captain_profiles": profiles, "decision_state": "PREPARE"})
    tables = _rendered_tables(rendered)
    expected = load_deep_presentation_lock()["sections"]["S08"]["tables"]
    assert len(tables) == 3
    assert [len(table["rows"]) for table in tables] == [5, 5, 5]
    assert [list(table["columns"]) for table in tables] == [row["columns"] for row in expected]
    assert "Joint C/VC MC: UNAVAILABLE" in rendered


def test_s10_has_existing_fifteen_price_rows_plus_fifteen_evidence_rows():
    rows = [
        {"player": f"P{i}", "current_price": 5.5,
         "direction": "RISE", "official_or_provider_progress": 92.0,
         "prediction_strength": None, "date_state": "DATE_UNAVAILABLE"}
        for i in range(15)
    ]
    rendered = _visible("S10", {"rows": rows})
    tables = _rendered_tables(rendered)
    expected = load_deep_presentation_lock()["sections"]["S10"]["tables"]
    assert len(tables) == 2
    assert [len(table["rows"]) for table in tables] == [15, 15]
    assert [list(table["columns"]) for table in tables] == [row["columns"] for row in expected]
    assert "NATIVE_FIELD 0/15 populated" in rendered
    assert "NOT_CALIBRATED" in rendered
