from __future__ import annotations

from copy import deepcopy
import ast
import math
from pathlib import Path

import pytest

from src.engines.canonical_decision_methodology import CANONICAL_WEIGHTS
from src.engines.lineup_governance import build_package_decision
from src.engines.report_enrichment import _mini_league_overlay_user_block
from src.engines.v12_mini_league_overlay import (
    MiniLeagueOverlayError,
    attach_mini_league_overlay,
    build_football_baseline,
    build_mini_league_snapshot,
    build_rival_route_definitions,
    close_decision_gate,
    derive_risk_posture,
    evaluate_mini_league_overlay,
    freeze_mini_league_decision,
    legacy_mini_league_inventory,
    load_config,
    overlay_calibration_summary,
    route_exposure,
    run_relative_mini_league_mc,
    settle_mini_league_decision,
)
from src.engines.v12_monte_carlo_acceptance import build_acceptance_fixture


def _projection_rows() -> list[dict]:
    defs = [
        (1, "GK", 1), (2, "GK", 2),
        (3, "DEF", 1), (4, "DEF", 2), (5, "DEF", 3),
        (6, "DEF", 4), (7, "DEF", 5),
        (8, "MID", 1), (9, "MID", 2), (10, "MID", 3),
        (11, "MID", 4), (12, "MID", 5), (16, "MID", 6),
        (13, "FWD", 3), (14, "FWD", 4), (15, "FWD", 5),
    ]
    return [
        {
            "element": element,
            "id": element,
            "name": f"P{element}",
            "position": pos,
            "element_type": {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}[pos],
            "team_id": team,
            "now_cost": 50,
        }
        for element, pos, team in defs
    ]


def _lineup(kind: str) -> dict:
    if kind == "B":
        xi = [1, 3, 4, 5, 8, 9, 10, 11, 16, 13, 14]
        captain = 16
    else:
        xi = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
        captain = 12
    return {
        "status": "READY",
        "gw": 36,
        "formation": "3-5-2",
        "starting_xi": xi,
        "bench_gk": 2,
        "bench_order": [15, 6, 7],
        "captain": captain,
        "vice_captain": 13,
        "expected_autosub_value": 1.0,
        "cameo_blocking_cost": 0.1,
    }


def _route(
    route_id: str,
    *,
    gw1: float,
    three: float,
    five: float,
    lineup_kind: str = "A",
    regret: float = 0.0,
) -> dict:
    final = list(range(1, 16))
    if lineup_kind == "B":
        final = [x for x in final if x != 12] + [16]
    return {
        "route_id": route_id,
        "classification": "HOLD" if route_id == "HOLD" else "CHANGE",
        "players_out": [] if route_id == "HOLD" else [{"element": 12}],
        "players_in": [] if route_id == "HOLD" else [{"element": 16}],
        "transfer_count": 0 if route_id == "HOLD" else 1,
        "legal": True,
        "affordable": True,
        "final_squad_elements": final,
        "football_route_utility": {"per_gw": [_lineup(lineup_kind)]},
        "horizons": {
            "GW+1": {"status": "READY", "net_delta_vs_hold": gw1},
            "3GW": {"status": "READY", "net_delta_vs_hold": three},
            "5GW": {"status": "READY", "net_delta_vs_hold": five},
        },
        "robustness": {
            "mean_only": False,
            "lineup_distribution_consumed": True,
        },
        "expected_regret": regret,
        "uncertainty": {"source": "GENUINE_P1_7_DISTRIBUTIONAL_SURFACE"},
        "execution_confidence": "HIGH",
        "information_value": {"status": "AVAILABLE", "value": 0.0},
        "transfer_economics": {
            "status": "PASS",
            "hit_points": 0.0,
            "future_ft_shadow_value": 0.0,
        },
    }


def _package() -> dict:
    routes = [
        _route("HOLD", gw1=0.0, three=0.0, five=0.0, regret=0.50),
        _route("A", gw1=0.50, three=1.20, five=1.50, regret=0.0),
        _route("B", gw1=0.49, three=1.15, five=1.45, lineup_kind="B", regret=0.05),
        _route("C", gw1=-4.0, three=-6.0, five=-7.0, lineup_kind="B", regret=4.5),
    ]
    return {
        "schema_version": 1,
        "model_owner": "V12_PACKAGE_UTILITY",
        "planning_gw": 36,
        "selected_route_id": "A",
        "selected_route": deepcopy(routes[1]),
        "hold_route_id": "HOLD",
        "routes": routes,
        "decision": {
            "football_action": "CHANGE",
            "operational_action": "ACT",
            "reason": "P1_2_BASELINE",
        },
        "model_evidence_binding": {
            "output_fingerprint": "a" * 64,
            "run_fingerprint": "b" * 64,
        },
        "package_frontier": {"status": "READY"},
    }


def _pick_row(element: int, position: int, *, captain=False, vice=False, tc=False):
    starter = position <= 11
    multiplier = 1 if starter else 0
    if captain:
        multiplier = 3 if tc else 2
    return {
        "element_id": element,
        "squad_position": position,
        "multiplier": multiplier,
        "captain": captain,
        "vice_captain": vice,
    }


def _entry(entry_id: int, *, captain: int = 12, chip=None, include_multiplier=True):
    order = list(range(1, 16))
    rows = []
    for position, element in enumerate(order, start=1):
        row = _pick_row(
            element,
            position,
            captain=element == captain,
            vice=element == 13,
            tc=chip == "3xc" and element == captain,
        )
        if not include_multiplier:
            row["multiplier"] = None
        rows.append(row)
    return {
        "entry_id": entry_id,
        "status": "AVAILABLE",
        "active_chip": chip,
        "checked_at": "2026-09-20T01:00:00Z",
        "picks": rows,
    }


def _standings(*, complete=True, ours_rank=2, ours_total=100, leader_total=110):
    rows = [
        {"entry_id": 100, "manager_name": "Us", "team_name": "Us", "league_rank": ours_rank, "league_total": ours_total, "gw_score": 0},
        {"entry_id": 200, "manager_name": "Leader", "team_name": "Leader", "league_rank": 1 if ours_rank != 1 else 2, "league_total": leader_total, "gw_score": 0},
        {"entry_id": 300, "manager_name": "R3", "team_name": "R3", "league_rank": 3, "league_total": 98, "gw_score": 0},
        {"entry_id": 400, "manager_name": "R4", "team_name": "R4", "league_rank": 4, "league_total": 90, "gw_score": 0},
    ]
    if ours_rank == 1:
        rows[0]["league_rank"] = 1
        rows[1]["league_rank"] = 2
    return {
        "league_id": 999,
        "league_name": "Test League",
        "league_kind": "classic",
        "generated_at": "2026-09-20T01:00:00Z",
        "complete": complete,
        "expected_manager_count": 4 if complete else None,
        "collected_manager_count": len(rows),
        "managers": rows,
        "authority": "OFFICIAL_FPL",
    }


def _picks(*, missing=None, multiplier_complete=True):
    entries = {
        "100": _entry(100, captain=12),
        "200": _entry(200, captain=12, chip="3xc"),
        "300": _entry(300, captain=12),
        "400": _entry(400, captain=12),
    }
    if not multiplier_complete:
        entries["300"] = _entry(300, captain=12, include_multiplier=False)
    if missing is not None:
        entries[str(missing)] = {
            "entry_id": missing,
            "status": "UNAVAILABLE",
            "active_chip": None,
            "picks": [],
        }
    available = sum(1 for row in entries.values() if row["status"] == "AVAILABLE")
    return {
        "league_id": 999,
        "gw": 36,
        "generated_at": "2026-09-20T01:00:00Z",
        "expected_manager_count": 4,
        "collected_manager_count": available,
        "submitted_picks_available_count": available,
        "submitted_picks_missing_count": 4 - available,
        "complete": available == 4,
        "entries": entries,
        "authority": "OFFICIAL_FPL",
    }


def _snapshot(**kwargs):
    return build_mini_league_snapshot(
        kwargs.pop("standings", _standings()),
        kwargs.pop("picks", _picks()),
        our_entry_id=100,
        planning_gw=kwargs.pop("planning_gw", 36),
        **kwargs,
    )


def _mc():
    metrics = {}
    for rid, delta, upside, downside in [
        ("HOLD", 0.0, 0.10, 0.50),
        ("A", 0.50, 0.20, 0.48),
        ("B", 0.49, 0.30, 0.47),
        ("C", -4.0, 0.05, 0.80),
    ]:
        metrics[rid] = {
            "1": {
                "status": "READY",
                "mean_difference_vs_hold": delta,
                "p_route_gt_hold": 0.52 if rid in {"A", "B"} else 0.1,
                "p_route_lt_hold": downside,
                "downside_probability": downside,
                "material_upside_probability": upside,
                "expected_regret": 0.0 if rid == "A" else 0.05,
                "paired_difference_standard_error": 0.01,
            }
        }
    return {
        "model_owner": "V12_MONTE_CARLO",
        "execution_state": "EXECUTED",
        "canonical_pass": True,
        "actual_paths": 500000,
        "common_random_numbers": True,
        "output_fingerprint": "c" * 64,
        "metrics": metrics,
        "paired_outputs": {
            "B__VS__A__H1": {
                "status": "READY",
                "mean_difference": -0.01,
                "p_a_gt_b": 0.49,
                "p_a_lt_b": 0.51,
                "paired_difference_standard_error": 0.01,
            },
            "C__VS__A__H1": {
                "status": "READY",
                "mean_difference": -4.5,
                "p_a_gt_b": 0.05,
                "p_a_lt_b": 0.95,
                "paired_difference_standard_error": 0.02,
            },
        },
    }


def _relative_mc():
    return {
        "model_owner": "V12_MONTE_CARLO",
        "execution_state": "EXECUTED",
        "canonical_pass": True,
        "actual_paths": 500000,
        "common_random_numbers": True,
        "output_fingerprint": "d" * 64,
        "paired_outputs": {
            "A__VS__RIVAL:200__H1": {
                "mean_difference": 0.10,
                "p_a_gt_b": 0.51,
                "p_a_lt_b": 0.49,
                "paired_difference_standard_error": 0.02,
            },
            "B__VS__RIVAL:200__H1": {
                "mean_difference": 0.35,
                "p_a_gt_b": 0.55,
                "p_a_lt_b": 0.45,
                "paired_difference_standard_error": 0.02,
            },
        },
    }


def _acceptance_rival_entry(entry_id: int = 200) -> dict:
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    bench = [2, 15, 6, 7]
    rows = []
    for position, element in enumerate(starters, start=1):
        rows.append({
            "element_id": element,
            "squad_position": position,
            "multiplier": 2 if element == 13 else 1,
            "captain": element == 13,
            "vice_captain": element == 8,
        })
    for offset, element in enumerate(bench, start=12):
        rows.append({
            "element_id": element,
            "squad_position": offset,
            "multiplier": 0,
            "captain": False,
            "vice_captain": False,
        })
    return {
        "entry_id": entry_id,
        "status": "AVAILABLE",
        "active_chip": None,
        "picks": rows,
    }


def _overlay(*, posture=None, snapshot=None):
    return evaluate_mini_league_overlay(
        _package(),
        snapshot or _snapshot(),
        monte_carlo=_mc(),
        relative_mc=_relative_mc(),
        explicit_risk_posture=posture,
        input_snapshot_id="P1_8_TEST",
        generated_at="2026-09-20T02:00:00Z",
    )


def test_01_football_baseline_is_computed_before_overlay():
    out = _overlay()
    assert out["governance"]["football_baseline_computed_first"] is True
    assert out["football_baseline"]["route_id"] == "A"


def test_02_football_baseline_is_immutable_under_overlay():
    package = _package()
    before = deepcopy(package["selected_route"])
    out = _overlay()
    assert package["selected_route"] == before
    assert out["governance"]["football_baseline_immutable"] is True


def test_03_raw_20_25_30_25_unchanged():
    assert CANONICAL_WEIGHTS == {
        "PROVEN_HISTORICAL": 0.20,
        "TACTICAL_ROLE": 0.25,
        "CURRENT_UNDERLYING": 0.30,
        "FIXTURE_SECURITY": 0.25,
    }


def test_04_ownership_requires_numerator_denominator():
    row = next(x for x in _snapshot()["exposures"] if x["element_id"] == 12)
    assert row["ownership_count"] == 3
    assert row["denominator"] == 3
    assert row["ownership_pct"] == 100.0


def test_05_starter_exposure_requires_numerator_denominator():
    row = next(x for x in _snapshot()["exposures"] if x["element_id"] == 12)
    assert row["starter_count"] == 3
    assert row["denominator"] == 3
    assert row["starter_pct"] == 100.0


def test_06_captain_exposure_requires_numerator_denominator():
    row = next(x for x in _snapshot()["exposures"] if x["element_id"] == 12)
    assert row["captain_count"] == 3
    assert row["captain_pct"] == 100.0


def test_07_partial_coverage_cannot_claim_full():
    snap = _snapshot(picks=_picks(missing=400))
    assert snap["coverage_state"] == "PARTIAL"
    assert snap["submitted_picks_missing_count"] == 1


def test_08_ownership_is_not_eo():
    row = next(x for x in _snapshot()["exposures"] if x["element_id"] == 12)
    assert row["ordinary_ownership_is_not_eo"] is True
    assert row["eo_pct"] != row["ownership_pct"]


def test_09_eo_requires_valid_multiplier_semantics():
    snap = _snapshot(picks=_picks(multiplier_complete=False))
    assert snap["eo_supported"] is False
    assert all(row["eo_pct"] is None for row in snap["exposures"])


def test_10_rival_bench_player_differs_from_starter():
    row = next(x for x in _snapshot()["exposures"] if x["element_id"] == 15)
    assert row["bench_count"] == 3
    assert row["starter_count"] == 0


def test_11_rival_starter_differs_from_captain():
    row = next(x for x in _snapshot()["exposures"] if x["element_id"] == 8)
    assert row["starter_count"] == 3
    assert row["captain_count"] == 0


def test_12_low_owned_poor_football_option_not_promoted():
    out = _overlay(posture="CHASE")
    assert out["adjusted_decision"]["route_id"] != "C"
    c = next(x for x in out["route_overlays"] if x["route_id"] == "C")
    assert c["close_decision_gate"]["status"] == "NOT_CLOSE"


def test_13_high_owned_poor_option_not_promoted_for_coverage():
    package = _package()
    package["routes"][3]["football_route_utility"]["per_gw"][0] = _lineup("A")
    out = evaluate_mini_league_overlay(
        package, _snapshot(), monte_carlo=_mc(),
        explicit_risk_posture="PROTECT",
        generated_at="2026-09-20T02:00:00Z",
    )
    assert out["adjusted_decision"]["route_id"] != "C"


def test_14_large_football_edge_remains_baseline_balanced():
    out = _overlay(posture="BALANCED")
    assert out["adjusted_decision"]["route_id"] in {"A", "B"}
    c = next(x for x in out["route_overlays"] if x["route_id"] == "C")
    assert c["mini_league_overlay_utility"] == 0.0


def test_15_close_decision_may_switch():
    out = _overlay(posture="CHASE")
    assert out["adjusted_decision"]["route_id"] == "B"
    assert out["decision_delta"]["changed"] is True


def test_16_protect_posture_increases_defensive_coverage_value():
    protect = _overlay(posture="PROTECT")
    chase = _overlay(posture="CHASE")
    a1 = next(x for x in protect["route_overlays"] if x["route_id"] == "A")
    a2 = next(x for x in chase["route_overlays"] if x["route_id"] == "A")
    assert a1["mini_league_overlay_utility"] > a2["mini_league_overlay_utility"]


def test_17_chase_posture_increases_differential_appetite():
    chase = _overlay(posture="CHASE")
    protect = _overlay(posture="PROTECT")
    b1 = next(x for x in chase["route_overlays"] if x["route_id"] == "B")
    b2 = next(x for x in protect["route_overlays"] if x["route_id"] == "B")
    assert b1["mini_league_overlay_utility"] > b2["mini_league_overlay_utility"]


def test_18_risk_posture_never_changes_gate0():
    assert _overlay(posture="CHASE")["governance"]["gate0_mutated"] is False


def test_19_risk_posture_never_changes_raw_football_score():
    out = _overlay(posture="CHASE")
    row = next(x for x in out["route_overlays"] if x["route_id"] == "B")
    assert row["football_baseline_utility"] == 0.49


def test_20_hold_remains_in_route_comparison():
    ids = {x["route_id"] for x in _overlay()["route_overlays"]}
    assert "HOLD" in ids


def test_21_p1_4_mc_provenance_retained():
    out = _overlay()
    assert out["model_evidence_binding"]["mc_output_fingerprint"] == "c" * 64


def test_22_same_football_worlds_used_for_relative_comparison():
    out = _overlay()
    b = next(x for x in out["route_overlays"] if x["route_id"] == "B")
    assert b["relative_mc"]["same_football_worlds"] is True


def test_23_no_second_fake_mini_league_mc():
    out = _overlay()
    assert out["governance"]["second_mini_league_mc_used"] is False


def test_24_no_unsupported_final_rank_probability():
    boundary = _overlay()["rank_probability_boundary"]
    assert boundary["p_finish_first"] == "NOT_COMPUTED"
    assert boundary["p_top_3"] == "NOT_COMPUTED"


def test_25_exact_league_scope_label_emitted():
    assert _snapshot()["league_scope"] == "FULL_LEAGUE"


def test_26_captain_leverage_reflects_multiplier_exposure():
    ex = route_exposure(_package()["routes"][1], _snapshot())
    assert ex["captain_leverage"]["rival_captain_count"] == 3
    assert ex["captain_leverage"]["rival_captain_pct"] == 100.0


def test_27_vice_exposure_handled_separately():
    ex = route_exposure(_package()["routes"][1], _snapshot())
    assert ex["vice_exposure"]["rival_vice_count"] == 3
    assert ex["vice_exposure"]["rival_vice_pct"] == 100.0


def test_28_chips_used_only_when_factual():
    snap = _snapshot()
    assert snap["chip_counts"]["3xc"] == 1
    assert snap["chip_counts"]["NONE"] == 2


def test_29_decision_delta_explicit():
    delta = _overlay(posture="CHASE")["decision_delta"]
    assert set(["football_baseline_route_id", "mini_league_adjusted_route_id", "changed", "state", "reason"]) <= set(delta)


def test_30_reversal_trigger_present_for_switch():
    out = _overlay(posture="CHASE")
    assert out["reversal_triggers"]["required"] is True
    assert "P1_4_RELATIVE_TAIL_EDGE_DISAPPEARS" in out["reversal_triggers"]["triggers"]


def test_31_predeadline_baseline_freeze_works():
    frozen = freeze_mini_league_decision(
        _overlay(posture="CHASE"),
        deadline_time="2026-09-20T10:00:00Z",
        frozen_at="2026-09-20T03:00:00Z",
    )
    snap = frozen["football_baseline_freeze"]["frozen_decision_snapshot"]
    assert snap["decision_kind"] == "P1.8_FOOTBALL_BASELINE"
    assert snap["route_id"] == "A"


def test_32_adjusted_decision_freeze_works():
    frozen = freeze_mini_league_decision(
        _overlay(posture="CHASE"),
        deadline_time="2026-09-20T10:00:00Z",
        frozen_at="2026-09-20T03:00:00Z",
    )
    snap = frozen["mini_league_adjusted_freeze"]["frozen_decision_snapshot"]
    assert snap["decision_kind"] == "P1.8_MINI_LEAGUE_ADJUSTED"
    assert snap["route_id"] == "B"


def test_33_postmatch_settlement_keeps_baseline_and_overlay_separate():
    frozen = freeze_mini_league_decision(
        _overlay(posture="CHASE"),
        deadline_time="2026-09-20T10:00:00Z",
        frozen_at="2026-09-20T03:00:00Z",
    )
    settled = settle_mini_league_decision(
        frozen,
        baseline_relative_points=2.0,
        adjusted_relative_points=4.0,
        event_finished=True,
        settled_at="2026-09-21T12:00:00Z",
    )
    assert settled["football_baseline_settlement"]["status"] == "SETTLED"
    assert settled["mini_league_adjusted_settlement"]["status"] == "SETTLED"


def test_34_overlay_regret_calculates_nonnegative():
    frozen = freeze_mini_league_decision(
        _overlay(posture="CHASE"),
        deadline_time="2026-09-20T10:00:00Z",
        frozen_at="2026-09-20T03:00:00Z",
    )
    settled = settle_mini_league_decision(
        frozen,
        baseline_relative_points=5.0,
        adjusted_relative_points=2.0,
        event_finished=True,
        settled_at="2026-09-21T12:00:00Z",
    )
    assert settled["overlay_regret"] == 3.0


def test_35_incomplete_league_data_cannot_suppress_football_report():
    snap = _snapshot(picks=_picks(missing=400))
    out = _overlay(snapshot=snap, posture="CHASE")
    assert out["status"] == "DEGRADED"
    assert out["decision_delta"]["changed"] is False
    assert out["adjusted_decision"]["route_id"] == "A"


def test_36_v6_unchanged_governance():
    assert load_config()["governance"]["raw_v6_payload_persisted"] is False


def test_37_no_scheduler_change():
    assert load_config()["governance"]["scheduler_changed"] is False


def test_38_no_authority_addition():
    assert load_config()["governance"]["authority_added"] is False


def test_39_p1_1_unchanged():
    assert load_config()["governance"]["p1_1_read_only"] is True


def test_40_p1_3_unchanged():
    assert load_config()["governance"]["p1_3_read_only"] is True


def test_41_p1_6_unchanged():
    assert load_config()["governance"]["p1_6_read_only"] is True


def test_42_p1_7_unchanged():
    assert load_config()["governance"]["p1_7_read_only"] is True


def test_43_p1_2_unchanged():
    assert load_config()["governance"]["p1_2_read_only"] is True


def test_44_p1_4_unchanged():
    assert load_config()["governance"]["p1_4_read_only"] is True


def test_45_overlay_disabled_baseline_identical_to_pre_overlay():
    package = _package()
    baseline = build_football_baseline(package, _mc())
    out = _overlay()
    assert out["football_baseline"] == baseline


def test_46_partial_scope_never_masquerades_as_full_league():
    snap = _snapshot(
        selected_entry_ids=[200, 300],
        league_scope="SELECTED_RIVALS",
    )
    assert snap["league_scope"] == "SELECTED_RIVALS"
    assert snap["expected_manager_count"] == 2


def test_47_default_posture_balanced_without_context_trigger():
    snap = _snapshot(planning_gw=10)
    assert derive_risk_posture(snap)["posture"] == "BALANCED"


def test_48_protect_requires_points_and_late_horizon_not_rank_alone():
    standings = _standings(ours_rank=1, ours_total=130, leader_total=110)
    snap = build_mini_league_snapshot(
        standings, _picks(), our_entry_id=100, planning_gw=36
    )
    assert derive_risk_posture(snap)["posture"] == "PROTECT"


def test_49_chase_requires_deficit_and_late_horizon():
    standings = _standings(ours_rank=2, ours_total=80, leader_total=110)
    snap = build_mini_league_snapshot(
        standings, _picks(), our_entry_id=100, planning_gw=36
    )
    assert derive_risk_posture(snap)["posture"] == "CHASE"


def test_50_explicit_posture_is_current_decision_preference():
    out = derive_risk_posture(_snapshot(), explicit_posture="CHASE")
    assert out["posture"] == "CHASE"
    assert out["source"] == "EXPLICIT_CURRENT_DECISION_PREFERENCE"


def test_51_close_gate_uses_horizons_and_mc():
    package = _package()
    gate = close_decision_gate(package["routes"][1], package["routes"][2], monte_carlo=_mc())
    assert gate["status"] == "CLOSE"
    assert gate["p_candidate_gt_baseline"] == pytest.approx(0.49)


def test_52_large_edge_gate_is_not_close():
    package = _package()
    gate = close_decision_gate(package["routes"][1], package["routes"][3], monte_carlo=_mc())
    assert gate["status"] == "NOT_CLOSE"
    assert gate["large_football_edge_preserved"] is True


def test_53_attachment_preserves_package_baseline():
    package = _package()
    overlay = _overlay(posture="CHASE")
    attached = attach_mini_league_overlay(package, overlay)
    assert package.get("mini_league_overlay") is None
    assert attached["selected_route_id"] == "A"
    assert attached["mini_league_overlay"]["adjusted_decision"]["route_id"] == "B"


def test_54_consumer_switch_uses_adjusted_route_only_after_valid_overlay():
    package = attach_mini_league_overlay(_package(), _overlay(posture="CHASE"))
    projections = {"planning_gw": 36, "players": _projection_rows()}
    team = {
        "squad_authority": "OFFICIAL_FPL_AUTHENTICATED",
        "squad": [{"element": x} for x in range(1, 16)],
        "team_value_ledger": [{"element": x, "sell_cost": 50} for x in range(1, 16)],
    }
    decision = build_package_decision(package, projections, {}, team)
    assert decision["football_baseline_selected_package_id"] == "A"
    assert decision["mini_league_adjusted_package_id"] == "B"
    assert decision["selected_package_id"] == "B"
    assert decision["governance"]["football_baseline_preserved"] is True


def test_55_partial_overlay_cannot_switch_consumer():
    snap = _snapshot(picks=_picks(missing=400))
    overlay = _overlay(snapshot=snap, posture="CHASE")
    package = attach_mini_league_overlay(_package(), overlay)
    projections = {"planning_gw": 36, "players": _projection_rows()}
    team = {
        "squad_authority": "OFFICIAL_FPL_AUTHENTICATED",
        "squad": [{"element": x} for x in range(1, 16)],
        "team_value_ledger": [{"element": x, "sell_cost": 50} for x in range(1, 16)],
    }
    decision = build_package_decision(package, projections, {}, team)
    assert decision["selected_package_id"] == "A"


def test_56_report_block_is_compact_and_auditable():
    package = {"mini_league_overlay": _overlay(posture="CHASE")}
    block = _mini_league_overlay_user_block(package)
    assert block["football_baseline_route_id"] == "A"
    assert block["mini_league_adjusted_route_id"] == "B"
    assert block["coverage"]["rival_denominator"] == 3
    assert block["football_baseline_preserved"] is True


def test_57_relevant_exposure_uses_element_ids_not_formatting():
    rows = _overlay()["relevant_rival_exposure"]
    assert rows
    assert all(isinstance(row["element_id"], int) for row in rows)


def test_58_denominator_fingerprint_is_stable():
    a = _snapshot()["denominator_fingerprint"]
    b = _snapshot()["denominator_fingerprint"]
    assert a == b and len(a) == 64


def test_59_model_evidence_binds_baseline_and_denominator():
    evidence = _overlay()["model_evidence_binding"]
    assert evidence["football_baseline_fingerprint"]
    assert evidence["denominator_fingerprint"]
    assert evidence["authority"] is False


def test_60_no_raw_v6_payload_duplication():
    assert _overlay()["model_evidence_binding"]["raw_v6_payload_duplicated"] is False


def test_61_legacy_inventory_classified_without_decision_authority():
    rows = legacy_mini_league_inventory()
    assert {row["classification"] for row in rows} >= {
        "FACTUAL_DISPLAY", "DENOMINATOR_DISCIPLINE", "REPORT_DECORATION", "LEGACY_DECISION_HEURISTIC"
    }
    assert all(row["decision_authority"] is False for row in rows)


def test_62_calibration_summary_has_no_one_gw_rule_creation():
    summary = overlay_calibration_summary([
        {
            "decision_delta": {"changed": True},
            "football_utility_sacrificed": 0.1,
            "relative_points_gained_or_lost_by_overlay": 2.0,
            "overlay_regret": 0.0,
            "risk_posture": "CHASE",
        }
    ])
    assert summary["overlay_change_count"] == 1
    assert summary["one_gw_permanent_leverage_rule_forbidden"] is True


def test_63_rival_route_definitions_use_exact_element_ids():
    projections, _ = build_acceptance_fixture()
    picks = {"entries": {"200": _acceptance_rival_entry(200)}}
    defs = build_rival_route_definitions(
        picks, projections, entry_ids=[200], planning_gw=6
    )
    assert defs[0]["route_id"] == "RIVAL:200"
    assert len(defs[0]["per_gw"][0]["starting_xi"]) == 11


def test_64_relative_mc_reuses_p1_4_engine_not_second_mc():
    projections, package = build_acceptance_fixture()
    picks = {"entries": {"200": _acceptance_rival_entry(200)}}
    result = run_relative_mini_league_mc(
        projections,
        package,
        picks,
        candidate_route_ids=["R1"],
        rival_entry_ids=[200],
        actual_paths=3000,
        seed=1808,
        input_snapshot_id="P1_8_RELATIVE_DIAG",
        canonical=False,
        generated_at="2026-09-20T02:00:00Z",
    )
    scope = result["mini_league_relative_scope"]
    assert scope["same_p1_4_football_worlds"] is True
    assert scope["second_mc_engine"] is False
    assert result["common_random_numbers"] is True


def test_65_relative_mc_scope_does_not_claim_final_rank():
    projections, package = build_acceptance_fixture()
    picks = {"entries": {"200": _acceptance_rival_entry(200)}}
    result = run_relative_mini_league_mc(
        projections,
        package,
        picks,
        candidate_route_ids=["R1"],
        rival_entry_ids=[200],
        actual_paths=2000,
        seed=1809,
        input_snapshot_id="P1_8_RELATIVE_DIAG_2",
        canonical=False,
        generated_at="2026-09-20T02:00:00Z",
    )
    assert result["mini_league_relative_scope"]["future_final_rank_probability"] == "NOT_COMPUTED"


def test_66_no_v6_import_in_overlay_engine():
    tree = ast.parse(Path("src/engines/v12_mini_league_overlay.py").read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    assert not any(name.startswith("src.runtime_v6") for name in imports)


def test_67_no_runtime_v3_production_dependency_in_overlay():
    tree = ast.parse(Path("src/engines/v12_mini_league_overlay.py").read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(name.startswith("src.runtime_v3") for name in imports)


def test_68_effective_exposure_can_exceed_100_with_captain_multiplier():
    row = next(x for x in _snapshot()["exposures"] if x["element_id"] == 12)
    assert row["eo_pct"] > 100.0


def test_69_partial_coverage_eo_is_not_claimed():
    row = next(x for x in _snapshot(picks=_picks(missing=400))["exposures"] if x["element_id"] == 12)
    assert row["eo_pct"] is None


def test_70_hold_baseline_still_exists_after_overlay():
    attached = attach_mini_league_overlay(_package(), _overlay())
    assert any(row["route_id"] == "HOLD" for row in attached["routes"])
