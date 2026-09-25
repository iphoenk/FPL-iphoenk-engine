from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines import v12_integrated_report_runner as runner
from src.engines.visible_content_proof import canonical_mode_contract
from src.engines.v12_report_orchestration import (
    DEEP_HUMAN_SECTION_REQUIREMENTS,
    _render_deep_visible_contract_lines,
    _render_math_stack_lines,
    build_deep_human_facing_manifest,
    render_deep_text,
)
from src.runtime_v6.domains.report_plane.visible_body_contract import (
    validate_visible_report_body,
)


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _bootstrap():
    positions = (
        [(1, "GK"), (2, "GK")]
        + [(x, "DEF") for x in range(3, 8)]
        + [(x, "MID") for x in range(8, 13)]
        + [(x, "FWD") for x in range(13, 16)]
    )
    elements = []
    position_id = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}
    for element, position in positions:
        elements.append(
            {
                "id": element,
                "web_name": f"P{element}",
                "team": ((element - 1) % 5) + 1,
                "element_type": position_id[position],
                "now_cost": 50,
                "status": "a",
            }
        )
    return {
        "events": [
            {"id": 5, "is_current": False, "is_next": False, "finished": True},
            {"id": 6, "is_current": False, "is_next": True, "finished": False},
        ],
        "elements": elements,
        "teams": [{"id": i, "name": f"T{i}"} for i in range(1, 6)],
    }


def _runtime_root(tmp_path: Path, report_slot: str) -> Path:
    runtime = tmp_path / "runtime"
    prefetch = {
        "report_kind": "full_master",
        "target_logical_report_slot": report_slot,
        "personal_requested": True,
        "mini_league_requested": True,
        "live_requested": False,
        "public_core_complete": True,
        "fresh_for_target_report": True,
        "generated_at": "2026-09-21T05:30:00+00:00",
        "report_prefetch_run_id": "prefetch-test",
    }
    _write(runtime / "data/v6/report_prefetch/latest.json", prefetch)
    _write(
        runtime / "data/v6/health/report_prefetch.json",
        {
            "prefetch_status": "GREEN",
            "fresh_for_target_report": True,
            "generated_at": "2026-09-21T05:30:00+00:00",
            "public_core_status": "GREEN",
        },
    )
    _write(
        runtime / "data/v6/health/publish_integrity.json",
        {
            "status": "PASS",
            "logical_slot": "2026-09-21T05:00:00+00:00",
            "identity": {
                "players": {"canonical_count": 15},
                "teams": {"canonical_count": 5},
                "fixtures": {"canonical_count": 1},
            },
        },
    )
    _write(
        runtime / "data/v6/personal/current_team.json",
        {
            "players": [
                {
                    "element_id": i,
                    "position": (
                        "GKP" if i <= 2 else
                        "DEF" if i <= 7 else
                        "MID" if i <= 12 else
                        "FWD"
                    ),
                    "current_price": 50,
                    "selling_price": 50,
                    "squad_position": i,
                }
                for i in range(1, 16)
            ]
        },
    )
    league = runtime / "data/v6/mini_leagues/9477"
    _write(league / "standings.json", {"managers": [], "complete": False})
    _write(league / "gw_5_manager_picks.json", {"entries": {}})
    return runtime


def _fake_projections():
    rows = []
    for i in range(1, 16):
        position = "GK" if i <= 2 else "DEF" if i <= 7 else "MID" if i <= 12 else "FWD"
        rows.append(
            {
                "element": i,
                "name": f"P{i}",
                "position": position,
                "team_id": ((i - 1) % 5) + 1,
                "now_cost": 50,
                "status": "a",
                "xmins": {
                    "availability": 1.0,
                    "start_probability": 0.9,
                    "cameo_probability": 0.05,
                    "dnp_probability": 0.05,
                    "expected_minutes": 78.0,
                },
                "horizons": {
                    "1": {"mean": 4.0, "std": 2.0, "point_distribution": {"2": 0.5, "6": 0.5}},
                    "3": {"mean": 12.0, "std": 4.0},
                    "5": {"mean": 20.0, "std": 6.0},
                },
                "xpts_by_gw": [{"gw": 6, "fixtures": [{"opponent": "X"}]}],
                "tactical_role_component": {"canonical_tactical_role_score": 60.0},
            }
        )
    return {"planning_gw": 6, "players": rows}


def test_prefetch_binding_rejects_stale_occurrence(tmp_path: Path):
    runtime = tmp_path / "runtime"
    _write(
        runtime / "data/v6/report_prefetch/latest.json",
        {
            "report_kind": "full_master",
            "target_logical_report_slot": "2026-09-21T12:30:00+07:00",
            "personal_requested": True,
            "mini_league_requested": True,
            "live_requested": False,
            "public_core_complete": True,
            "fresh_for_target_report": True,
            "generated_at": "2026-09-21T00:00:00+00:00",
        },
    )
    _write(
        runtime / "data/v6/health/report_prefetch.json",
        {
            "prefetch_status": "GREEN",
            "fresh_for_target_report": True,
            "generated_at": "2026-09-21T00:00:00+00:00",
        },
    )
    with pytest.raises(runner.IntegratedRunnerError, match="not same-occurrence"):
        runner._require_report_prefetch(
            runtime,
            report_slot="2026-09-21T12:30:00+07:00",
        )



def test_prefetch_binding_accepts_public_first_amber_when_only_private_auth_is_expired(tmp_path: Path):
    slot = "2026-09-21T18:57:00+07:00"
    runtime = tmp_path / "runtime"
    _write(
        runtime / "data/v6/report_prefetch/latest.json",
        {
            "report_kind": "full_master",
            "target_logical_report_slot": slot,
            "personal_requested": True,
            "mini_league_requested": True,
            "public_core_complete": True,
            "fresh_for_target_report": True,
            "generated_at": "2026-09-21T11:57:20+00:00",
            "authenticated_personal_required_for_public_green": False,
            "public_personal_status": "AVAILABLE",
            "mini_league_status": "AVAILABLE",
            "public_control_failures": [],
            "auth_state": "AUTH_EXPIRED",
            "personal_status": "DEGRADED",
        },
    )
    _write(
        runtime / "data/v6/health/report_prefetch.json",
        {
            "prefetch_status": "AMBER",
            "public_core_status": "GREEN",
            "auth_state": "AUTH_EXPIRED",
        },
    )
    bound = runner._require_report_prefetch(runtime, report_slot=slot)
    assert bound["same_occurrence_bound"] is True
    assert bound["scope_checks"]["prefetch_health_acceptable"] is True


def test_prefetch_binding_rejects_amber_when_public_scope_is_incomplete(tmp_path: Path):
    slot = "2026-09-21T18:57:00+07:00"
    runtime = tmp_path / "runtime"
    _write(
        runtime / "data/v6/report_prefetch/latest.json",
        {
            "report_kind": "full_master",
            "target_logical_report_slot": slot,
            "personal_requested": True,
            "mini_league_requested": True,
            "public_core_complete": True,
            "fresh_for_target_report": True,
            "generated_at": "2026-09-21T11:57:20+00:00",
            "authenticated_personal_required_for_public_green": False,
            "public_personal_status": "AVAILABLE",
            "mini_league_status": "DEGRADED",
            "public_control_failures": [],
        },
    )
    _write(
        runtime / "data/v6/health/report_prefetch.json",
        {"prefetch_status": "AMBER", "public_core_status": "GREEN"},
    )
    with pytest.raises(runner.IntegratedRunnerError, match="prefetch_health_acceptable"):
        runner._require_report_prefetch(runtime, report_slot=slot)


def test_integrated_deep_runner_executes_owner_stages_and_materializes_full_catalog(
    monkeypatch,
    tmp_path: Path,
):
    slot = "2026-09-21T12:30:00+07:00"
    runtime = _runtime_root(tmp_path, slot)
    bootstrap = _bootstrap()
    monkeypatch.setattr(
        runner,
        "_official_payload",
        lambda _: {"payload": {"health": "GREEN"}, "bootstrap": bootstrap, "fixtures": [{"id": 1}]},
    )
    monkeypatch.setattr(runner, "build_team_strength", lambda *a, **k: {"teams": [], "matchups": []})
    monkeypatch.setattr(
        runner,
        "load_v6_analytics_foundation",
        lambda *a, **k: {
            "status": "MATCH_FOUNDATION_READY",
            "stage1_full_foundation_ready": True,
            "historical_prior": {"players": {}},
            "player_features_payload": {},
            "player_match_rows": [{"element": 1, "gw": 5, "minutes": 90}],
            "opponent_history_rows": [],
            "opponent_history_scope": "CURRENT-SEASON ONLY",
        },
    )
    projections = _fake_projections()
    monkeypatch.setattr(runner, "build_player_projections", lambda *a, **k: projections)
    monkeypatch.setattr(runner, "attach_official_role_evidence", lambda *a, **k: {"status": "PASS"})
    monkeypatch.setattr(runner, "attach_tactical_role_scores", lambda *a, **k: {"status": "PASS"})
    monkeypatch.setattr(
        runner,
        "optimize_lineup",
        lambda *a, **k: {
            "formation": "3-5-2",
            "starting_xi": [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14],
            "bench": {"gk": 2, "order": [6, 7, 15]},
            "captain": {"element": 10},
            "vice_captain": {"element": 8},
            "lineup_score": {"xpts_mean": 55.0},
            "main_starting_xi_battle": {"status": "NO_CLOSE_BATTLE"},
            "formation_comparison": [
                {
                    "formation": "3-5-2",
                    "expected_fpl_points_with_captain_vice": 60.0,
                    "route_utility": 59.5,
                    "distributional_downside": 40.0,
                    "supportable_upside": 80.0,
                    "selected": True,
                },
                {
                    "formation": "4-4-2",
                    "expected_fpl_points_with_captain_vice": 60.2,
                    "route_utility": 59.2,
                    "distributional_downside": 39.0,
                    "supportable_upside": 81.0,
                    "selected": False,
                },
            ],
        },
    )
    monkeypatch.setattr(
        runner,
        "build_price20",
        lambda **kwargs: {
            "state": "COMPLETE",
            "available_count": 20,
            "expected_count": 20,
            "rows": [{"element_id": 100 + i} for i in range(20)],
            "predictor_health": "GREEN",
            "degradation_reason": None,
        },
    )
    monkeypatch.setattr(
        runner,
        "build_actionable_price_radar",
        lambda **kwargs: {"state": "COMPLETE", "rows": [{"element_id": i} for i in range(1, 16)]},
    )
    monkeypatch.setattr(
        runner,
        "build_watchlist20",
        lambda **kwargs: {
            "state": "DEGRADED",
            "available_count": 0,
            "expected_count": 20,
            "rows": [],
            "degradation_reason": "canonical evaluator intentionally incomplete",
        },
    )
    monkeypatch.setattr(
        runner,
        "build_mini_league_snapshot",
        lambda *a, **k: {"coverage_state": "FULL", "current_context": {"our_rank": 7}},
    )

    out = runner.run_deep(
        runtime_data_root=runtime,
        report_slot=slot,
        output_dir=tmp_path / "out",
        checkpoint_time="12:30",
    )

    canonical = runner.CANONICAL_PATH.read_text(encoding="utf-8")
    expected = canonical_mode_contract(canonical, "DEEP")["expected_section_ids"]
    actual = [row["section_id"] for row in out["report"]["sections"]]
    assert actual == expected
    assert len(actual) == 23
    assert {"S06B", "S14B", "S15B", "S16B"} <= set(actual)
    assert out["human_facing_manifest"]["status"] in {"PASS", "FAIL"}
    assert out["planning_gw"] == 6
    stages = {row["stage"]: row["status"] for row in out["stage_ledger"]}
    assert stages["V6_REPORT_PREFETCH_BINDING"] == "PASS"
    assert stages["P1_1_P1_3_FULL_UNIVERSE"] == "PASS"
    assert stages["P1_6_TACTICAL_ROLE"] == "PASS"
    assert stages["P1_7_LINEUP"] == "PASS"
    assert stages["OFFICIAL_FPL_PREDICTOR_RISE20"] == "PASS"
    assert stages["P1_8_MINI_LEAGUE_SNAPSHOT"] == "PASS"
    assert stages["CANONICAL_UNIVERSE_20_25_30_25"] == "PARTIAL"
    assert stages["CORE_SLOT_BINDING"] == "PASS"
    assert "PRE_RENDER_QA" in stages
    assert "POST_RENDER_QA" in stages
    assert "HUMAN_FACING_QA" in stages
    assert out["execution_proof"]["canonical_catalog_complete"] is True
    assert out["runner_status"] in {"PASS", "PARTIAL"}
    assert (tmp_path / "out/report_bundle.json").exists()
    assert (tmp_path / "out/report_body.md").exists()
    assert (tmp_path / "out/execution_proof.json").exists()


def test_deep_contract_includes_expanded_human_backbone():
    canonical = runner.CANONICAL_PATH.read_text(encoding="utf-8")
    section_ids = canonical_mode_contract(canonical, "DEEP")["expected_section_ids"]
    assert section_ids == [
        "S01", "S02", "S03", "S04", "S05", "S06", "S06B",
        "S07", "S08", "S09", "S10", "S11", "S12", "S13",
        "S14", "S14B", "S15", "S15B", "S16", "S16B",
        "S17", "S18", "S19",
    ]


def test_deep_human_manifest_fails_closed_when_new_section_is_missing():
    sections = []
    for section_id in (
        "S01", "S02", "S03", "S04", "S05", "S06", "S06B",
        "S07", "S08", "S09", "S10", "S11", "S12", "S13",
        "S14", "S14B", "S15", "S15B", "S16",
        "S17", "S18", "S19",
    ):
        sections.append({
            "section_id": section_id,
            "state": "DEGRADED",
            "content": {},
        })
    manifest = build_deep_human_facing_manifest({"sections": sections})
    assert manifest["status"] == "FAIL"
    assert "HUMAN_SECTION_MISSING=S16B" in manifest["failures"]


def test_captain_review_exposes_distributional_and_mini_league_evidence():
    projections = {
        "players": [
            {
                "element": 10,
                "name": "Captain A",
                "position": "FWD",
                "xmins": {
                    "expected_minutes": 88.0,
                    "start_probability": 0.98,
                },
                "horizons": {
                    "1": {
                        "point_distribution": {
                            "status": "AVAILABLE",
                            "mean": 7.4,
                            "quantiles": {"Q90": 13.0},
                            "p_haul_10_plus": 0.31,
                            "p_fpl_blank": 0.34,
                        }
                    }
                },
                "xpts_by_gw": [
                    {
                        "gw": 6,
                        "fixtures": [
                            {
                                "opponent": "OPP",
                                "home": True,
                                "complete_player_distribution": {
                                    "P_goal": 0.48,
                                    "P_assist": 0.22,
                                    "P_return": 0.60,
                                    "P_start": 0.98,
                                },
                                "position_engine": {
                                    "goal_process": {"status": "AVAILABLE"},
                                    "creation_process": {"status": "AVAILABLE"},
                                    "penalty_process": {"role": "TAKER"},
                                    "set_piece_process": {"role": "NONE"},
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }
    review = runner._captain_candidate_review(
        candidate={"element": 10, "name": "Captain A"},
        projections=projections,
        mini={
            "exposures": [
                {
                    "element_id": 10,
                    "captain_count": 30,
                    "captain_pct": 51.7,
                    "eo_pct": 140.0,
                }
            ]
        },
        mini_league_stance="BALANCED",
    )
    assert review["expected_points"] == pytest.approx(7.4)
    assert review["ceiling_q90"] == pytest.approx(13.0)
    assert review["xmins"] == pytest.approx(88.0)
    assert review["goal_involvement"]["p_return"] == pytest.approx(0.60)
    assert review["captain_pct"] == pytest.approx(51.7)
    assert review["eo_pct"] == pytest.approx(140.0)
    assert review["raw_mean_is_not_sole_authority"] is True


def test_formation_strategy_separates_raw_ev_from_distributional_choice():
    lineup = {
        "formation": "3-5-2",
        "starting_xi": [{"element": i} for i in range(1, 12)],
        "formation_comparison": [
            {
                "formation": "3-5-2",
                "expected_fpl_points_with_captain_vice": 59.8,
                "route_utility": 59.6,
                "selected": True,
            },
            {
                "formation": "4-4-2",
                "expected_fpl_points_with_captain_vice": 60.2,
                "route_utility": 59.1,
                "selected": False,
            },
        ],
    }
    strategy = runner._formation_mini_league_strategy(
        lineup=lineup,
        mini={"exposures": []},
        mini_overlay={"risk_posture": {"posture": "BALANCED"}},
        projections={"players": []},
    )
    assert strategy["raw_ev_formation"] == "4-4-2"
    assert strategy["football_optimal_formation"] == "3-5-2"
    assert strategy["mini_league_objective_formation"] == "3-5-2"
    assert strategy["objectives_same"] is False
    assert strategy["projected_points_difference"] == pytest.approx(-0.4)


def test_integrated_deep_runner_keeps_bundle_when_projection_stage_fails(
    monkeypatch,
    tmp_path: Path,
):
    slot = "2026-09-21T12:30:00+07:00"
    runtime = _runtime_root(tmp_path, slot)
    bootstrap = _bootstrap()
    monkeypatch.setattr(
        runner,
        "_official_payload",
        lambda _: {
            "payload": {"health": "GREEN"},
            "bootstrap": bootstrap,
            "fixtures": [{"id": 1}],
        },
    )
    monkeypatch.setattr(
        runner,
        "build_team_strength",
        lambda *a, **k: {"teams": [], "matchups": []},
    )
    monkeypatch.setattr(
        runner,
        "load_v6_analytics_foundation",
        lambda *a, **k: {
            "status": "MATCH_FOUNDATION_READY",
            "stage1_full_foundation_ready": True,
            "historical_prior": {"players": {}},
            "player_features_payload": {},
            "player_match_rows": [{"element": 1, "gw": 5, "minutes": 90}],
            "opponent_history_rows": [],
            "opponent_history_scope": "CURRENT-SEASON ONLY",
        },
    )

    def projection_failure(*args, **kwargs):
        raise RuntimeError("projection boom")

    monkeypatch.setattr(runner, "build_player_projections", projection_failure)
    monkeypatch.setattr(
        runner,
        "build_price20",
        lambda **kwargs: {
            "state": "DEGRADED",
            "available_count": 0,
            "expected_count": 20,
            "rows": [],
            "predictor_health": "GREEN",
            "degradation_reason": "synthetic fixture",
        },
    )
    monkeypatch.setattr(
        runner,
        "build_actionable_price_radar",
        lambda **kwargs: {"state": "COMPLETE", "rows": []},
    )
    monkeypatch.setattr(
        runner,
        "build_watchlist20",
        lambda **kwargs: {
            "state": "DEGRADED",
            "available_count": 0,
            "expected_count": 20,
            "rows": [],
            "degradation_reason": "projection prerequisite unavailable",
        },
    )
    monkeypatch.setattr(
        runner,
        "build_mini_league_snapshot",
        lambda *a, **k: {
            "coverage_state": "FULL",
            "current_context": {"our_rank": 7},
        },
    )

    out = runner.run_deep(
        runtime_data_root=runtime,
        report_slot=slot,
        output_dir=tmp_path / "out-failed-projection",
        checkpoint_time="12:30",
    )

    stages = {row["stage"]: row for row in out["stage_ledger"]}
    assert stages["P1_1_P1_3_FULL_UNIVERSE"]["status"] == "FAILED"
    assert "projection boom" in stages["P1_1_P1_3_FULL_UNIVERSE"]["error"]
    assert stages["P1_6_TACTICAL_ROLE"]["status"] == "NOT_RUN"
    assert stages["P1_7_LINEUP"]["status"] == "NOT_RUN"
    assert stages["P1_2_PACKAGE_UTILITY"]["status"] == "NOT_RUN"
    assert stages["P1_4_MONTE_CARLO"]["status"] == "NOT_RUN"
    assert out["runner_status"] == "PARTIAL"
    section16 = next(
        row for row in out["report"]["sections"] if row["section_id"] == "S16"
    )
    assert section16["state"] == "DEGRADED"
    assert "projection boom" in section16["degradation_reason"]
    assert out["execution_proof"]["canonical_catalog_complete"] is True
    assert (tmp_path / "out-failed-projection/report_bundle.json").exists()
    assert (tmp_path / "out-failed-projection/report_body.md").exists()
    assert (tmp_path / "out-failed-projection/execution_proof.json").exists()



def test_math_stack_renderer_is_type_safe_for_degraded_scalar_placeholders():
    lines = _render_math_stack_lines(
        {
            "availability_mixture": "UNAVAILABLE",
            "event_probabilities": "UNAVAILABLE",
            "point_distribution": "UNAVAILABLE",
            "monte_carlo": "NOT_RUN",
        }
    )
    body = "\n".join(lines)
    assert "MATHEMATICAL DECISION STACK" in body
    assert "E[xPts]=UNAVAILABLE" in body
    assert "P(START)=UNAVAILABLE" in body
    assert "state=UNAVAILABLE" in body


def test_runner_source_has_no_legacy_runtime_imports():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    forbidden_imports = (
        "from src.runtime_v3",
        "import src.runtime_v3",
        "from src.runtime_v4",
        "import src.runtime_v4",
        "from src.runtime_v5",
        "import src.runtime_v5",
        "from src.models.package_optimizer_v2",
        "from src.engines.decision_intelligence",
    )
    assert not [token for token in forbidden_imports if token in source]


def test_integrated_runner_does_not_hardcode_short_projection_horizon():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "horizon=5" not in source
    assert "published_horizons" not in source
    assert "build_player_projections(" in source


def test_integrated_runner_requires_match_level_foundation_before_projection():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "V12_ANALYTICS_FOUNDATION" in source
    assert "require_match_foundation" in source
    assert "player_match_rows=[]" not in source
    assert 'opponent_history_rows=[]' not in source


def test_integrated_runner_source_compiles():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    compile(source, str(runner.__file__), "exec")



def test_stage3_s14_consumes_real_package_mc_and_decision_producers():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "P1_2A_PACKAGE_SEARCH" in source
    assert "P1_2_PACKAGE_UTILITY" in source
    assert "P1_4_MONTE_CARLO" in source
    assert "P1_2_STAGE3_DECISION_CLOSURE" in source
    assert "P1_8_MINI_LEAGUE_OVERLAY" in source
    assert "_stage3_visible_package_surface(" in source
    assert "Stage3 internal producer/wiring failure" in source
    assert "STAGE_2_PACKAGE_FRONTIER_AND_MATERIAL_MONTE_CARLO_NOT_STARTED" not in source
    assert '"S14": _section(' in source



def test_stage1_deep_renderer_passes_actual_visible_body_contract():
    canonical = runner.CANONICAL_PATH.read_text(encoding="utf-8")
    section_ids = canonical_mode_contract(
        canonical,
        "DEEP",
    )["expected_section_ids"]

    owned = [
        {
            "element_id": element,
            "player": f"P{element}",
            "opponent": 20,
            "p_available": 1.0,
            "p_start": 0.8,
            "p_cameo": 0.1,
            "p_dnp": 0.1,
            "xmins": 70.0,
            "tactical_role": 60.0,
            "gw_plus_1": 4.0,
            "three_gw": 12.0,
            "five_gw": 20.0,
            "action": "HOLD",
        }
        for element in range(1, 16)
    ]
    positions = (
        ["GK"] * 5
        + ["DEF"] * 5
        + ["MID"] * 5
        + ["FWD"] * 5
    )
    watchlist = [
        {
            "element_id": 100 + rank,
            "name": f"W{rank}",
            "position": position,
            "football_score": 80.0 - rank,
        }
        for rank, position in enumerate(positions, start=1)
    ]

    def price_rows(direction: str):
        return [
            {
                "rank": rank,
                "element_id": 200 + rank,
                "player_name": f"{direction}{rank}",
                "current_price": 5.0,
                "ownership_percent": 1.0,
                "ownership_tag": "NON_OWNED",
                "direction": direction,
                "current_progress_percent": 110.0,
                "projection_offset_0_percent": 120.0,
                "predicted_change_cycle": "NEXT CYCLE",
                "predicted_change_at": "2026-09-22T06:00:00+07:00",
                "eta_human": "22 Sep 2026 06:00 WIB",
                "model_urgency": "WATCH",
                "confidence": "HIGH",
                "source": "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR",
                "observed_at": "2026-09-21T21:00:00+00:00",
                "raw_payload_hash": "a" * 64,
            }
            for rank in range(1, 21)
        ]

    payloads = {
        "S02": {"rows": owned},
        "S05": {"note": "weather evidence isolated"},
        "S06": {
            "formation": "3-5-2",
            "starting_xi": [
                {"element": i, "name": f"P{i}"}
                for i in range(1, 12)
            ],
            "bench": {
                "gk": {"element": 12, "name": "P12"},
                "order": [
                    {"element": i, "name": f"P{i}"}
                    for i in range(13, 16)
                ],
            },
        },
        "S11": {"rows": watchlist},
        "S12": {"rows": price_rows("RISE")},
        "S13": {"rows": price_rows("FALL")},
        "S15B": {
            "coverage_state": "FULL",
            "note": "full league denominator",
        },
        "S16": {"rows": owned},
        "S17": {"note": "lineage visible"},
    }
    sections = []
    for section_id in section_ids:
        sections.append(
            {
                "section_id": section_id,
                "label": section_id,
                "state": (
                    "DEGRADED"
                    if section_id in {"S09", "S14"}
                    else "COMPLETE"
                ),
                "degradation_reason": (
                    "bounded Stage 2 or source degradation"
                    if section_id in {"S09", "S14"}
                    else None
                ),
                "content": payloads.get(
                    section_id,
                    {"note": f"{section_id} visible"},
                ),
            }
        )

    body = render_deep_text({"sections": sections})
    visible = validate_visible_report_body(
        rendered_body=body,
        expected_section_ids=section_ids,
        expected_counts={
            "OUR15": 15,
            "XI": 11,
            "BENCH": 4,
            "WATCHLIST20": 20,
            "RISE20": 20,
            "FALL20": 20,
        },
        expected_fact_keys=["OFFICIAL_FPL_OCCURRENCE_FACTS"],
        expected_model_keys=["V12_OCCURRENCE_MODEL_OUTPUTS"],
        expected_inference_keys=["V12_DECISION_INFERENCE"],
        expected_weather_state="SOURCE_DEGRADED",
        mini_league_denominator_complete_required=True,
        expected_mini_league_state="COMPLETE",
    )

    assert visible["status"] == "PASS", visible["failures"]
    assert visible["counts"]["OUR15"] == 15
    assert visible["counts"]["XI"] == 11
    assert visible["counts"]["BENCH"] == 4
    assert visible["counts"]["WATCHLIST20"] == 20
    assert visible["counts"]["RISE20"] == 20
    assert visible["counts"]["FALL20"] == 20
    assert visible["counts"]["ALL15_TACTICAL"] == 15
    assert visible["weather_contract_state"] == "SOURCE_DEGRADED"
    assert visible["mini_league_contract_state"] == "COMPLETE"


def test_stage1_visible_renderer_source_compiles():
    import src.engines.v12_report_orchestration as orchestration

    source = Path(orchestration.__file__).read_text(encoding="utf-8")
    compile(source, str(orchestration.__file__), "exec")


def test_stage2_public_first_acceptance_does_not_require_private_auth(tmp_path):
    from src.engines.v12_stage2_acceptance import (
        _public_personal_and_mini_league_evidence,
    )

    entry_id = 3462711
    league_id = 9477
    picks = [
        {
            "element_id": element,
            "squad_position": element,
            "multiplier": 1 if element <= 11 else 0,
        }
        for element in range(1, 16)
    ]
    owned = [{"element_id": element} for element in range(1, 16)]
    current_team = {
        "entry_id": entry_id,
        "gw": 5,
        "auth_state": "AUTH_EXPIRED",
        "squad_state": "SUBMITTED_PICKS_ONLY",
        "lineage": {
            "authenticated": [{"http_status": 401}],
            "submitted_picks": {
                "http_status": 200,
                "origin": "LIVE_FETCHED_CURRENT_GW",
            },
        },
    }
    _write(
        tmp_path / "data/v6/personal/submitted_picks.json",
        {
            "status": "AVAILABLE",
            "entry_id": entry_id,
            "gw": 5,
            "picks": picks,
            "lineage": {
                "http_status": 200,
                "origin": "LIVE_FETCHED_CURRENT_GW",
            },
        },
    )
    _write(
        tmp_path / "data/v6/personal/memberships.json",
        {
            "status": "AVAILABLE",
            "priority_resolution": [
                {
                    "league_id": league_id,
                    "league_name": "ICON+ League",
                    "resolution_status": "RESOLVED",
                }
            ],
        },
    )
    _write(
        tmp_path / "data/v6/report_prefetch/latest.json",
        {
            "entry_id": entry_id,
            "gw": 5,
            "priority_league_id": league_id,
            "priority_league_name": "ICON+ League",
            "public_core_complete": True,
            "public_personal_status": "AVAILABLE",
            "mini_league_status": "AVAILABLE",
            "public_control_failures": [],
            "expected_manager_count": 58,
            "collected_manager_count": 58,
        },
    )
    _write(
        tmp_path / f"data/v6/mini_leagues/{league_id}/standings.json",
        {
            "complete": True,
            "expected_manager_count": 58,
            "collected_manager_count": 58,
        },
    )
    _write(
        tmp_path / f"data/v6/mini_leagues/{league_id}/gw_5_manager_picks.json",
        {
            "complete": True,
            "coverage_percent": 100.0,
            "entries": {
                str(entry_id): {
                    "entry_id": entry_id,
                    "gw": 5,
                    "http_status": 200,
                    "picks": picks,
                }
            },
        },
    )

    out = _public_personal_and_mini_league_evidence(
        tmp_path,
        current_team=current_team,
        owned=owned,
    )
    assert out["current_public_squad_available"] is True
    assert out["mini_league_public_available"] is True
    assert out["authenticated_session_required"] is False
    assert out["submitted_http_status"] == 200
    assert out["manager_entry_http_status"] == 200


def test_stage2_public_first_acceptance_rejects_incomplete_public_identity(tmp_path):
    from src.engines.v12_stage2_acceptance import (
        _public_personal_and_mini_league_evidence,
    )

    _write(
        tmp_path / "data/v6/personal/submitted_picks.json",
        {
            "status": "AVAILABLE",
            "entry_id": 3462711,
            "gw": 5,
            "picks": [{"element_id": element} for element in range(1, 15)],
            "lineage": {
                "http_status": 200,
                "origin": "LIVE_FETCHED_CURRENT_GW",
            },
        },
    )
    out = _public_personal_and_mini_league_evidence(
        tmp_path,
        current_team={
            "entry_id": 3462711,
            "gw": 5,
            "auth_state": "AUTH_EXPIRED",
            "squad_state": "SUBMITTED_PICKS_ONLY",
            "lineage": {"submitted_picks": {"http_status": 200}},
        },
        owned=[{"element_id": element} for element in range(1, 16)],
    )
    assert out["current_public_squad_available"] is False
    assert out["mini_league_public_available"] is False


def _ml_picks(elements, *, captain=None, vice=None, bench=None):
    bench = set(bench or [])
    rows = []
    for position, element in enumerate(elements, start=1):
        is_bench = element in bench
        rows.append(
            {
                "element_id": element,
                "squad_position": 12 if is_bench else min(position, 11),
                "multiplier": (
                    2 if element == captain and not is_bench
                    else 0 if is_bench
                    else 1
                ),
                "captain": element == captain,
                "vice_captain": element == vice,
            }
        )
    return rows


def _ml_deep_fixture(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_captain_candidate_review",
        lambda *, candidate, **kwargs: {
            "element_id": int(candidate["element"]),
            "player": candidate["name"],
            "expected_points": 6.0 - (int(candidate["element"]) / 100.0),
            "haul_probability": 0.12,
            "blank_probability": 0.40,
        },
    )

    our_entry = 100
    owned = [
        {"element_id": element, "name": f"P{element}"}
        for element in range(1, 16)
    ]
    standings = {
        "managers": [
            {
                "entry_id": 201,
                "league_rank": 1,
                "league_total": 110,
                "manager_name": "Leader One",
                "team_name": "Leader FC",
                "gw_score": 60,
            },
            {
                "entry_id": 202,
                "league_rank": 2,
                "league_total": 105,
                "manager_name": "Leader Two",
                "team_name": "Second FC",
                "gw_score": 50,
            },
            {
                "entry_id": our_entry,
                "league_rank": 3,
                "league_total": 100,
                "manager_name": "Us",
                "team_name": "Our FC",
                "gw_score": 45,
            },
        ],
        "complete": True,
    }
    manager_picks = {
        "entries": {
            "201": {
                "entry_id": 201,
                "status": "AVAILABLE",
                "picks": _ml_picks(
                    list(range(1, 15)) + [16],
                    captain=1,
                    vice=2,
                    bench={12, 13, 14, 16},
                ),
            },
            "202": {
                "entry_id": 202,
                "status": "AVAILABLE",
                "picks": _ml_picks(
                    list(range(1, 14)) + [17, 18],
                    captain=2,
                    vice=1,
                    bench={10, 11, 12, 17},
                ),
            },
        }
    }
    exposures = []
    for element in range(1, 16):
        own = 2 if element <= 13 else 1 if element == 14 else 0
        starter = (
            2 if element <= 9
            else 1 if element in {10, 11, 13, 14}
            else 0
        )
        bench = own - starter
        captain = 1 if element in {1, 2} else 0
        vice = 1 if element in {1, 2} else 0
        effective = starter + captain
        exposures.append(
            {
                "element_id": element,
                "ownership_count": own,
                "starter_count": starter,
                "bench_count": bench,
                "captain_count": captain,
                "vice_count": vice,
                "effective_multiplier_sum": effective,
                "denominator": 2,
                "ownership_pct": own * 50.0,
                "starter_pct": starter * 50.0,
                "bench_pct": bench * 50.0,
                "captain_pct": captain * 50.0,
                "vice_pct": vice * 50.0,
                "eo_pct": effective * 50.0,
                "eo_supported": True,
            }
        )
    mini = {
        "coverage_state": "FULL",
        "expected_manager_count": 3,
        "submitted_picks_available_count": 3,
        "rival_exposure_denominator": 2,
        "exposures": exposures,
        "current_league_context": {
            "our_entry_id": our_entry,
            "our_rank": 3,
            "our_total_points": 100,
            "leader_points": 110,
            "points_to_leader": 10,
            "points_to_top_3": 0,
            "points_to_top_5": 0,
            "points_to_nearest_above": 5,
            "points_ahead_nearest_below": None,
            "manager_count": 3,
        },
    }
    detail = runner._mini_league_deep_detail(
        mini=mini,
        standings=standings,
        manager_picks=manager_picks,
        owned=owned,
        projections={"players": []},
        lineup={
            "captain": {"element": 1, "name": "P1"},
            "vice_captain": {"element": 2, "name": "P2"},
        },
        mini_overlay={"risk_posture": {"posture": "BALANCED"}},
        disclosed_gw=5,
        operational_action="WAIT",
    )
    return mini, detail, owned


def test_mini_league_deep_materializes_raw_counts_direct_rivals_and_threats(monkeypatch):
    mini, detail, _ = _ml_deep_fixture(monkeypatch)

    p1 = next(
        row for row in detail["our15_rival_exposure"]
        if row["element_id"] == 1
    )
    assert p1["ownership_count"] == 2
    assert p1["denominator"] == 2
    assert p1["ownership_pct"] == 100.0
    assert p1["captain_count"] == 1
    assert p1["eo_pct"] == 150.0

    assert detail["direct_rival_scope"]["denominator"] == 2
    assert detail["direct_rival_scope"]["complete"] is True
    assert [row["rank"] for row in detail["direct_rivals"]] == [1, 2]
    assert detail["direct_rivals"][0]["overlap_count"] == 14
    assert detail["rival_threats"]
    assert detail["report_contract"]["raw_count_denominator_percentage_required"] is True
    assert detail["strategy_implication"]["human_posture"] == "BALANCED"
    assert mini["coverage_state"] == "FULL"


def test_mini_league_s15b_visible_renderer_keeps_comprehensive_contract(monkeypatch):
    mini, detail, owned = _ml_deep_fixture(monkeypatch)
    payload = {**mini, **detail}
    owned_names = {
        row["element_id"]: row["name"]
        for row in owned
    }
    lines, _ = _render_deep_visible_contract_lines(
        section_id="S15B",
        content=payload,
        owned_ids=set(owned_names),
        owned_names=owned_names,
    )
    body = "\n".join(lines)
    assert "OUR15 VS ALL RIVALS" in body
    assert "OUR15 VS DIRECT RIVALS" in body
    assert "RIVAL THREATS NOT IN OUR15" in body
    assert "CAPTAIN LEVERAGE" in body
    assert "CHASE / BALANCED / DEFEND IMPLICATION" in body
    assert "| Player | OWN | START | BENCH | C | VC | EO |" in body
    assert "**P1**" in body
    assert "2/2 (100.0%)" in body
    assert "3/2 (150.0%)" in body
    assert "DIRECT RIVAL DIFFERENCE DETAIL" in body


def test_mini_league_s15b_manifest_cannot_regress_to_compact_summary():
    required = set(DEEP_HUMAN_SECTION_REQUIREMENTS["S15B"])
    assert {
        "rank_battle",
        "our15_rival_exposure",
        "direct_rival_scope",
        "direct_rivals",
        "direct_rival_our15_exposure",
        "rival_threats",
        "captain_leverage",
        "strategy_implication",
        "report_contract",
    }.issubset(required)


def test_stagec_evidence_is_wired_into_visible_transfer_comparator_without_math_mutation():
    surface = runner._stage3_visible_package_surface(
        projections={
            "players": [
                {
                    "element": 9901,
                    "name": "Scanner Candidate",
                    "position": "MID",
                    "team": "TEST",
                    "now_cost": 55,
                    "xmins": {
                        "expected_minutes": 82,
                        "start_probability": 0.9,
                    },
                    "horizons": {},
                    "xpts_by_gw": [],
                }
            ]
        },
        canonical_bundle={
            "players": [
                {
                    "element_id": 9901,
                    "canonical_rank": 7,
                    "football_score": 1.2,
                    "canonical_components": {},
                }
            ]
        },
        package_search_result={},
        package_utility={
            "routes": [
                {
                    "route_id": "R1",
                    "players_in": [{"element": 9901, "buy_price": 55}],
                    "players_out": [],
                    "horizons": {},
                    "transfer_economics": {},
                }
            ]
        },
        material_mc_routes={"route_ids": ["R1"]},
        monte_carlo={},
        stage3_decision={
            "operational_action": "WAIT",
            "routes": [{"route_id": "R1"}],
        },
        mini_overlay=None,
        finance={},
        stagec_scan={
            "evaluation_feed": [
                {
                    "element": 9901,
                    "signals": ["BREAKOUT"],
                    "horizons": [1, 2, 3, 5],
                }
            ],
            "material_candidates": [
                {
                    "element": 9901,
                    "active_signals": ["BREAKOUT"],
                    "positive_signals": ["BREAKOUT"],
                    "negative_signals": [],
                    "hidden_gem": True,
                    "sample_confidence": 0.9,
                    "why_flagged": ["recent underlying improved"],
                }
            ],
        },
    )
    assert surface["stagec_evaluation_bridge"] == {
        "candidate_feed_count": 1,
        "material_candidate_count": 1,
        "visible_route_context_only": True,
        "full_universe_package_search_preserved": True,
        "decision_math_mutated": False,
    }
    challenger = surface["challengers"][0]
    assert challenger["stagec_evidence"]["active_signals"] == ["BREAKOUT"]
    assert challenger["stagec_evidence"]["decision_math_adjustment"] == 0.0
    move = surface["package_routes"][0]["moves"]["in"][0]
    assert move["stagec_evidence"]["hidden_gem"] is True
