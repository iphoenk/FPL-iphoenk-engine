from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.domains.report_plane.section_contract import validate_report_sections
from test_support.report_rank20 import rank20_rows
from test_support.report_sections import r4_section_payloads


def _our15() -> list[dict]:
    rows: list[dict] = []
    for player_id in (1, 2):
        rows.append({"element_id": player_id, "position": "GK"})
    for player_id in range(3, 8):
        rows.append({"element_id": player_id, "position": "DEF"})
    for player_id in range(8, 13):
        rows.append({"element_id": player_id, "position": "MID"})
    for player_id in range(13, 16):
        rows.append({"element_id": player_id, "position": "FWD"})
    return rows


def _watchlist20() -> list[dict]:
    rows: list[dict] = []
    start = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for offset in range(5):
            rows.append({"element_id": start + offset, "position": position})
        start += 10
    return rows


def _full_sections() -> dict:
    our15 = _our15()
    return {
        "OUR15": our15,
        "XI_BENCH": {
            "starting_xi_ids": [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
            "bench_ids": [2, 7, 12, 15],
        },
        "WATCHLIST20": _watchlist20(),
        "RISE20": rank20_rows(201, "RISE"),
        "FALL20": rank20_rows(301, "FALL"),
        **r4_section_payloads(our15),
    }


def test_r4_required_present_fields_cannot_be_null_false_passes():
    mutations = {
        "WEATHER": lambda payload: payload["WEATHER"]["rows"][0].__setitem__("temperature", None),
        "ICON14B": lambda payload: payload["ICON14B"].__setitem__("current_rank", None),
        "ALL15_TACTICAL": lambda payload: payload["ALL15_TACTICAL"][0].__setitem__("p_start", None),
        "OPTIMIZER": lambda payload: payload["OPTIMIZER"]["routes"][0].__setitem__("net_projected_gain", None),
        "PRICE_RISK": lambda payload: payload["PRICE_RISK"]["owned_rows"][0].__setitem__("current_price", None),
    }

    for section, mutate in mutations.items():
        payload = _full_sections()
        mutate(payload)
        result = validate_report_sections(payload)
        assert result["status"] == "FAIL", section
        assert section in result["failures"], section
        assert result["checks"][section]["status"] == "FAIL", section


def test_r4_malformed_non_mapping_rows_fail_closed_instead_of_raising():
    mutations = {
        "WEATHER": lambda payload: payload["WEATHER"]["rows"].__setitem__(0, "bad-row"),
        "ALL15_TACTICAL": lambda payload: payload["ALL15_TACTICAL"].__setitem__(0, "bad-row"),
        "OPTIMIZER": lambda payload: payload["OPTIMIZER"]["routes"].__setitem__(0, "bad-row"),
        "PRICE_RISK": lambda payload: payload["PRICE_RISK"]["owned_rows"].__setitem__(0, "bad-row"),
    }

    for section, mutate in mutations.items():
        payload = deepcopy(_full_sections())
        mutate(payload)
        result = validate_report_sections(payload)
        assert result["status"] == "FAIL", section
        assert section in result["failures"], section
        assert result["checks"][section]["status"] == "FAIL", section
