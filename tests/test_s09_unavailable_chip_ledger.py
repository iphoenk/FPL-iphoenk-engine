"""Regression for missing/auth-unavailable S09 chip states in canonical DEEP."""
from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines


def _s09(ledger):
    lines, _ = _render_deep_visible_contract_lines(
        section_id="S09",
        content={"chip_ledger": ledger},
        owned_ids=set(),
        owned_names={},
    )
    return "\n".join(lines)


def test_s09_unavailable_is_not_implicitly_available():
    output = _s09({})
    assert "| Bench Boost | UNAVAILABLE |" in output
    assert "Remaining: UNAVAILABLE" in output
    assert "Remaining: Bench Boost, Wildcard, Triple Captain, Free Hit" not in output


def test_s09_used_chips_are_never_remaining():
    output = _s09({
        "BB": "USED",
        "WC": "USED",
        "TC": "USED",
        "FH": "AVAILABLE",
    })
    assert "Remaining: Free Hit" in output
    assert "chip status unresolved" not in output


def test_s09_partial_ledger_reports_uncertainty_without_fabrication():
    output = _s09({"BB": "USED", "FH": "AVAILABLE"})
    assert "Remaining: UNAVAILABLE (chip status unresolved:" in output
    assert "confirmed available: Free Hit" in output
    assert "Remaining: Free Hit" not in output
