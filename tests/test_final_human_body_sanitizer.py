from src.engines.v12_report_orchestration import (
    _sanitize_mapping_reprs,
    _render_deep_visible_contract_lines,
)


def test_s07_locked_marker_is_visible():
    lines, _ = _render_deep_visible_contract_lines(
        section_id="S07",
        content={"risk_rows": [], "lineup_implication": "UNAVAILABLE"},
        owned_ids=set(),
        owned_names={},
    )
    assert "LINEUP RISK / AUTOSUB LOGIC" in lines


def test_final_body_sanitizes_nested_python_mapping_repr():
    body = "Evidence: {'outer': {'state': 'UNAVAILABLE'}}"
    result = _sanitize_mapping_reprs(body)
    assert "{'outer'" not in result
    assert "outer: state=UNAVAILABLE" in result
