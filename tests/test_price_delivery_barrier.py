from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

import pytest

from src.engines.v12_price_delivery import (
    PRICE_SECTION_IDS,
    build_price_delivery_report,
    render_price_report,
    resolve_current15,
    validate_price_report_model,
    validate_price_visible_body,
)


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_CANONICAL_V12.txt"


def _canonical() -> str:
    return CANONICAL.read_text(encoding="utf-8")


def _position_for_index(index: int) -> str:
    return ("GK", "DEF", "MID", "FWD")[index % 4]


def _element_type(position: str) -> int:
    return {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}[position]


def _bootstrap(max_id: int = 260) -> dict:
    elements = []
    for element_id in range(1, max_id + 1):
        position = _position_for_index(element_id - 1)
        elements.append(
            {
                "id": element_id,
                "web_name": f"P{element_id}",
                "element_type": _element_type(position),
                "team": ((element_id - 1) % 20) + 1,
                "now_cost": 45 + (element_id % 40),
                "cost_change_event": 0,
            }
        )
    return {
        "events": [{"id": 6, "is_next": True, "finished": False}],
        "elements": elements,
    }


def _team_rows(ids: list[int], *, sell_value: int = 55) -> list[dict]:
    rows = []
    for idx, element_id in enumerate(ids):
        position = _position_for_index(idx)
        rows.append(
            {
                "element_id": element_id,
                "name": f"P{element_id}",
                "position": position,
                "current_price": 50 + (idx % 10),
                "selling_price": sell_value,
                "sell_value": sell_value,
                "authenticated_state": "CURRENT_AUTHENTICATED",
            }
        )
    return rows


def _team_resolution(
    ids: list[int] | None = None,
    *,
    bank: int | None = 10,
    free_transfers=None,
    hit_cost=None,
) -> dict:
    ids = ids or list(range(1, 16))
    return {
        "state": "CURRENT",
        "supportable": True,
        "rows": _team_rows(ids),
        "element_ids": ids,
        "source_class": "SYNTHETIC_CURRENT_GW",
        "gw": 6,
        "observed_at": "2026-09-23T05:20:00+07:00",
        "finance": {
            "bank": bank,
            "free_transfers": free_transfers,
            "hit_cost": hit_cost,
        },
        "reason": None,
    }


def _predictor(count: int = 120, *, health: str = "GREEN") -> dict:
    rows = []
    for element_id in range(1, count + 1):
        sign = 1 if element_id <= count // 2 else -1
        magnitude = 130 - (element_id % 50)
        projected = sign * magnitude
        position = _position_for_index(element_id - 1)
        rows.append(
            {
                "id": element_id,
                "web_name": f"P{element_id}",
                "element_type": _element_type(position),
                "team": ((element_id - 1) % 20) + 1,
                "now_cost": 45 + (element_id % 40),
                "price_change_percent": projected - sign * 3,
                "price_change_hourly_rate": sign * 0.8,
                "selected_by_percent": "1.0",
                "transfers_in_event": 1000 + element_id,
                "transfers_out_event": 500 + element_id,
                "price_change_locked_until": None,
                "price_change_calibrating": False,
                "price_change_projections": [
                    {
                        "offset": 0,
                        "projected_percent": projected,
                        "likelihood": 4 if sign > 0 else -4,
                    },
                    {
                        "offset": 1,
                        "projected_percent": projected + sign * 10,
                        "likelihood": 4 if sign > 0 else -4,
                    },
                    {
                        "offset": 2,
                        "projected_percent": projected + sign * 20,
                        "likelihood": 5 if sign > 0 else -5,
                    },
                ],
            }
        )
    return {
        "health": health,
        "checked_at": "2026-09-22T22:29:43+00:00",
        "data": {"players": rows},
    }


def _universe() -> list[dict]:
    rows = []
    element_id = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for rank in range(10):
            rows.append(
                {
                    "element_id": element_id,
                    "name": f"P{element_id}",
                    "position": position,
                    "eligible": True,
                    "canonical_evaluation_complete": True,
                    "canonical_rank": rank + 1,
                    "football_score": 100 - rank,
                }
            )
            element_id += 1
    return rows


def _healthy_report(*, routes=()) -> dict:
    return build_price_delivery_report(
        canonical_text=_canonical(),
        report_slot="2026-09-23T05:30:00+07:00",
        planning_gw=6,
        bootstrap=_bootstrap(),
        team_resolution=_team_resolution(),
        predictor_artifact=_predictor(),
        evaluated_universe=_universe(),
        universe_authority="FULL",
        transfer_routes=routes,
        mini_league={
            "complete": True,
            "league_name": "Synthetic League",
            "expected_manager_count": 58,
            "collected_manager_count": 58,
            "generated_at": "2026-09-23T05:20:00+07:00",
            "user_summary": {"rank": 7},
        },
        source_lineage={
            "official_timestamp": "2026-09-23T05:29:45+07:00",
            "core_logical_slot": "2026-09-23T05:00:00+07:00",
            "core_run_id": "synthetic",
            "runtime_snapshot": "synthetic",
            "next_checkpoint": "NEXT PRICE CYCLE",
        },
    )


def test_a_healthy_price_exact20_eta_12_sections_and_human_pass():
    report = _healthy_report()
    body = render_price_report(report)
    assert validate_price_report_model(report) == []
    assert validate_price_visible_body(body, report=report) == []
    assert [row["section_id"] for row in report["sections"]] == list(PRICE_SECTION_IDS)
    assert len(report["watchlist20"]["rows"]) == 20
    assert len(report["rise20"]["rows"]) == 20
    assert len(report["fall20"]["rows"]) == 20


def test_b_dynamic_current15_precedence_and_next_gw_re_resolve():
    bootstrap = _bootstrap(100)
    squad_a = {
        "players": _team_rows(list(range(1, 16))),
        "gw": 6,
        "generated_at": "2026-09-23T04:00:00+07:00",
        "auth_state": "AUTH_AVAILABLE",
        "squad_state": "AUTHENTICATED_CURRENT_TEAM",
    }
    squad_b = {
        "players": _team_rows(list(range(21, 36))),
        "gw": 6,
        "observed_at": "2026-09-23T04:30:00+07:00",
    }
    got_b = resolve_current15(
        planning_gw=6,
        bootstrap=bootstrap,
        explicit_user_evidence=squad_b,
        authenticated_current_team=squad_a,
    )
    assert got_b["element_ids"] == list(range(21, 36))

    squad_c = {
        "players": _team_rows(list(range(41, 56))),
        "gw": 6,
        "generated_at": "2026-09-23T05:00:00+07:00",
        "auth_state": "AUTH_AVAILABLE",
        "squad_state": "AUTHENTICATED_CURRENT_TEAM",
    }
    got_c = resolve_current15(
        planning_gw=6,
        bootstrap=bootstrap,
        explicit_user_evidence=squad_b,
        authenticated_current_team=squad_c,
    )
    assert got_c["element_ids"] == list(range(41, 56))

    squad_d = {
        "players": _team_rows(list(range(61, 76))),
        "gw": 7,
        "generated_at": "2026-10-11T01:00:00+07:00",
        "auth_state": "AUTH_AVAILABLE",
        "squad_state": "AUTHENTICATED_CURRENT_TEAM",
    }
    got_d = resolve_current15(
        planning_gw=7,
        bootstrap=bootstrap,
        explicit_user_evidence=squad_b,
        authenticated_current_team=squad_d,
    )
    assert got_d["element_ids"] == list(range(61, 76))


def test_c_contemplated_transfer_does_not_mutate_current15():
    resolution = _team_resolution()
    before = list(resolution["element_ids"])
    report = build_price_delivery_report(
        canonical_text=_canonical(),
        report_slot="2026-09-23T05:30:00+07:00",
        planning_gw=6,
        bootstrap=_bootstrap(),
        team_resolution=resolution,
        predictor_artifact=_predictor(),
        evaluated_universe=_universe(),
        universe_authority="FULL",
        transfer_routes=[
            {
                "out_element_id": 1,
                "in_element_id": 90,
                "football_action": "PREPARE",
            }
        ],
    )
    assert report["current15"]["element_ids"] == before
    assert 90 not in report["current15"]["element_ids"]


def test_d_materialization_without_pre_rendered_exact20():
    report = _healthy_report()
    assert report["rise20"]["state"] == "COMPLETE"
    assert report["fall20"]["state"] == "COMPLETE"
    assert len(report["rise20"]["rows"]) == 20
    assert len(report["fall20"]["rows"]) == 20
    assert report["governance"]["pre_rendered_exact20_required"] is False


def test_e_genuine_predictor_failure_keeps_12_section_structure():
    report = build_price_delivery_report(
        canonical_text=_canonical(),
        report_slot="2026-09-23T05:30:00+07:00",
        planning_gw=6,
        bootstrap=_bootstrap(),
        team_resolution=_team_resolution(),
        predictor_artifact={"health": "RED", "data": {"players": []}},
        evaluated_universe=_universe(),
        universe_authority="FULL",
        transfer_routes=(),
        mini_league={},
    )
    body = render_price_report(report)
    assert len(report["sections"]) == 12
    assert report["rise20"]["state"] != "COMPLETE"
    assert report["fall20"]["state"] != "COMPLETE"
    assert validate_price_visible_body(body, report=report) == []


@pytest.mark.parametrize("key", ["rise20", "fall20", "watchlist20"])
def test_f_false_exact20_claim_fails_qa(key):
    report = _healthy_report()
    report[key]["state"] = "COMPLETE"
    report[key]["rows"] = list(report[key]["rows"])[:19]
    failures = validate_price_report_model(report)
    assert any("FALSE_EXACT20" in failure for failure in failures)


def test_f_directional_exact20_requires_twenty_actual_direction_rows():
    report = build_price_delivery_report(
        canonical_text=_canonical(),
        report_slot="2026-09-23T05:30:00+07:00",
        planning_gw=6,
        bootstrap=_bootstrap(),
        team_resolution=_team_resolution(),
        predictor_artifact=_predictor(count=38),
        evaluated_universe=_universe(),
        universe_authority="FULL",
    )
    assert report["rise20"]["state"] != "COMPLETE"
    assert report["fall20"]["state"] != "COMPLETE"
    assert len(report["rise20"]["rows"]) == 19
    assert len(report["fall20"]["rows"]) == 19


def test_g_eta_omitted_from_relevant_visible_rows_fails_qa():
    report = _healthy_report()
    body = render_price_report(report).replace("ETA/status", "ETA")
    failures = validate_price_visible_body(body, report=report)
    assert any("ETA_MISSING" in failure for failure in failures)


def test_h_incomplete_action_board_fails_qa():
    report = _healthy_report()
    body = render_price_report(report)
    body = re.sub(r"(?m)^ABORT / REVERSAL:.*\n", "", body)
    failures = validate_price_visible_body(body, report=report)
    assert "VISIBLE_ACTION_BOARD_FIELD_MISSING=ABORT / REVERSAL" in failures


def test_i_legacy_short_fallback_never_human_facing_passes():
    report = _healthy_report()
    failures = validate_price_visible_body(
        "WAIT. No price-driven transfer this morning.\n",
        report=report,
    )
    assert failures
    assert any("SECTION" in failure or "ACTION" in failure for failure in failures)


def test_j_affordability_is_separate_from_ft_hit_economics():
    report = _healthy_report(
        routes=[
            {
                "out_element_id": 1,
                "in_element_id": 90,
                "football_action": "PREPARE",
            }
        ]
    )
    routes = report["sections"][7]["content"]["routes"]
    assert len(routes) == 1
    assert routes[0]["nominal_affordability"] in {True, False}
    assert routes[0]["ft_hit_economics"] == "UNKNOWN"


def test_k_newer_current_gw_authenticated_evidence_beats_previous_gw_last_good():
    bootstrap = _bootstrap(100)
    previous = {
        "players": _team_rows(list(range(1, 16))),
        "gw": 5,
        "generated_at": "2026-09-22T20:00:00+07:00",
    }
    current = {
        "players": _team_rows(list(range(41, 56))),
        "gw": 6,
        "generated_at": "2026-09-23T05:00:00+07:00",
        "auth_state": "AUTH_AVAILABLE",
        "squad_state": "AUTHENTICATED_CURRENT_TEAM",
    }
    resolved = resolve_current15(
        planning_gw=6,
        bootstrap=bootstrap,
        authenticated_current_team=current,
        last_good_evidence=previous,
    )
    assert resolved["state"] == "CURRENT"
    assert resolved["element_ids"] == list(range(41, 56))


def test_l_no_hardcoded_player_or_fixed_current15_production_rule():
    source = Path("src/engines/v12_price_delivery.py").read_text(encoding="utf-8")
    canonical = Path(
        "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
    ).read_text(encoding="utf-8")
    block = canonical.split("14L.", 1)[1].split("14M.", 1)[0]
    assert re.search(r"CURRENT15\s*=\s*\[", source) is None
    assert "owned_element_ids = [" not in source
    assert "mini_leagues/9477" not in source
    assert "/9477/" not in source
    for transient_name in ("Haaland", "Calafiori", "Sangaré", "Groß"):
        assert transient_name not in source
        assert transient_name not in block
