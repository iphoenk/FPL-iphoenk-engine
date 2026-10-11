"""P0 authenticated S09/S14/S18 binding regression tests."""
from src.engines.v12_integrated_report_runner import (
    _verified_official_chip_ledger,
    _route_execution_economics_state,
)
from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines


def _render(section_id, content):
    lines, _ = _render_deep_visible_contract_lines(
        section_id=section_id, content=content, owned_ids=set(), owned_names={}
    )
    return "\n".join(lines)


def test_official_chip_list_is_visible_without_guessing():
    ledger = _verified_official_chip_ledger([
        {"name": "bboost", "status_for_entry": "played"},
        {"name": "3xc", "status_for_entry": "played"},
        {"name": "wildcard", "status_for_entry": "played"},
        {"name": "freehit", "status_for_entry": "available"},
    ])
    assert ledger == {"BB": "USED", "WC": "USED", "TC": "USED", "FH": "AVAILABLE"}
    visible = _render("S09", {"chip_ledger": ledger})
    assert "| Bench Boost | USED |" in visible
    assert "| Free Hit | AVAILABLE |" in visible


def test_duplicate_or_ambiguous_chip_fails_closed():
    ledger = _verified_official_chip_ledger([
        {"name": "bboost", "status_for_entry": "played"},
        {"name": "bboost", "status_for_entry": "available"},
    ])
    assert all(value == "UNAVAILABLE" for value in ledger.values())


def test_pass_route_requires_available_authenticated_finance():
    finance = {
        "bank": 2, "free_transfers": 1,
        "bank_status": "AVAILABLE",
        "sell_value_status": "AVAILABLE",
        "free_transfers_status": "AVAILABLE",
    }
    assert _route_execution_economics_state(
        route_id="1:411->271", route_economics_status="PASS", finance=finance
    ) == {"status": "AVAILABLE", "executable": True}
    finance["free_transfers"] = None
    assert _route_execution_economics_state(
        route_id="1:411->271", route_economics_status="PASS", finance=finance
    ) == {"status": "DEGRADED", "executable": False}


def test_s14_uses_authenticated_economics_authority():
    visible = _render("S14", {"execution_economics_authority": {
        "bank": 2, "free_transfers": 1, "free_transfers_status": "AVAILABLE",
        "sell_value_status": "AVAILABLE",
    }})
    assert "FT: 1" in visible
    missing = _render("S14", {"execution_economics_authority": {
        "free_transfers": 1, "free_transfers_status": "AUTH_EXPIRED",
    }})
    assert "FT: UNAVAILABLE" in missing
