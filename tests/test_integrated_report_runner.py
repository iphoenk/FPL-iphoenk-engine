from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines import v12_integrated_report_runner as runner
from src.engines.visible_content_proof import canonical_mode_contract
from src.engines.v12_stage3_acceptance import _truthful_source_degraded_sections
from src.engines.v12_report_orchestration import (
    DEEP_HUMAN_SECTION_REQUIREMENTS,
    _human_summary,
    _render_deep_visible_contract_lines,
    _render_math_stack_lines,
    build_calendar_workload_context,
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
        "mini_league_status": "AVAILABLE",
        "public_personal_status": "AVAILABLE",
        "authenticated_personal_required_for_public_green": False,
        "public_control_failures": [],
        "live_requested": False,
        "public_core_complete": True,
        "fresh_for_target_report": True,
        "generated_at": "2026-09-21T05:30:00+00:00",
        "report_prefetch_run_id": "prefetch-test",
        "artifacts": [
            {
                "artifact_class": "REPORT_PREFETCH",
                "status": "PROVEN",
                "publication_run_id": "prefetch-test-publication",
                "published_at": "2026-09-21T05:30:01+00:00",
            }
        ],
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
            "logical_slot": report_slot,
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
            "scanner20": [],
            "actionable_watchlist": [],
            "actionable_count": 0,
            "position_formulae": {
                "GK": "V12_WATCH_GK_EVIDENCE_V1",
                "DEF": "V12_WATCH_DEF_EVIDENCE_V1",
                "MID": "V12_WATCH_MID_EVIDENCE_V1",
                "FWD": "V12_WATCH_FWD_EVIDENCE_V1",
            },
            "actionable_watchlist_is_unpadded_subset": True,
            "price_is_overlay_not_primary_authority": True,
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
    expected = canonical_mode_contract(
        canonical, "DEEP", s16b_due=False
    )["expected_section_ids"]
    actual = [row["section_id"] for row in out["report"]["sections"]]
    assert actual == expected
    assert len(actual) == 22
    assert {"S06B", "S14B", "S15B"} <= set(actual)
    assert "S16B" not in actual
    s11 = next(row for row in out["report"]["sections"] if row["section_id"] == "S11")
    assert "scanner20" in s11["content"]
    assert "actionable_watchlist" in s11["content"]
    assert s11["content"]["position_formulae"]["GK"] == "V12_WATCH_GK_EVIDENCE_V1"
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


def test_deep_contract_supports_base22_and_due23_without_renumbering():
    canonical = runner.CANONICAL_PATH.read_text(encoding="utf-8")
    base = canonical_mode_contract(
        canonical, "DEEP", s16b_due=False
    )["expected_section_ids"]
    due = canonical_mode_contract(
        canonical, "DEEP", s16b_due=True
    )["expected_section_ids"]
    assert base == [
        "S01", "S02", "S03", "S04", "S05", "S06", "S06B",
        "S07", "S08", "S09", "S10", "S11", "S12", "S13",
        "S14", "S14B", "S15", "S15B", "S16",
        "S17", "S18", "S19",
    ]
    assert due == base[:19] + ["S16B"] + base[19:]
    assert len(base) == 22
    assert len(due) == 23


def test_deep_human_manifest_does_not_require_s16b_when_not_materialized():
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
    assert "HUMAN_SECTION_MISSING=S16B" not in manifest["failures"]


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



def test_human_summary_never_emits_raw_mapping_repr_for_nested_lists():
    text = _human_summary(
        {
            "weather": [
                {"fixture": 51, "condition": "NORMAL"},
                {"fixture": 52, "condition": "NOTABLE"},
            ]
        }
    )
    assert "{'" not in text
    assert '"fixture"' not in text
    assert "fixture=51" in text
    assert "condition=NORMAL" in text


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



def test_stage1_deep_renderer_uses_locked_human_surface_not_legacy_raw_contract():
    canonical = runner.CANONICAL_PATH.read_text(encoding="utf-8")
    section_ids = canonical_mode_contract(canonical, "DEEP")["expected_section_ids"]
    sections = [
        {
            "section_id": section_id,
            "label": section_id,
            "state": "DEGRADED",
            "degradation_reason": "controlled fixture",
            "content": {},
        }
        for section_id in section_ids
    ]
    body = render_deep_text({"sections": sections})
    assert "| Axis | Status | Current call |" in body
    assert "## 14. S14" in body
    assert "## 14. S14" in body
    assert "RAW_PAYLOAD_HASH" not in body
    assert "DIRECT6" not in body
    assert "FULL ICON+ COMPOSITION" not in body

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
    }
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
    assert out["personal_runtime_files_required"] is False
    assert out["submitted_http_status"] == 200
    assert out["submitted_origin"] == "PUBLIC_MINI_LEAGUE_MANAGER_PICKS"
    assert not (tmp_path / "data/v6/personal").exists()


def test_stage2_public_first_acceptance_rejects_incomplete_public_identity(tmp_path):
    from src.engines.v12_stage2_acceptance import (
        _public_personal_and_mini_league_evidence,
    )

    entry_id = 3462711
    league_id = 9477
    _write(
        tmp_path / "data/v6/report_prefetch/latest.json",
        {
            "entry_id": entry_id,
            "gw": 5,
            "priority_league_id": league_id,
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
                    "picks": [
                        {"element_id": element}
                        for element in range(1, 15)
                    ],
                }
            },
        },
    )
    out = _public_personal_and_mini_league_evidence(
        tmp_path,
        current_team={
            "entry_id": entry_id,
            "gw": 5,
            "auth_state": "AUTH_EXPIRED",
        },
        owned=[{"element_id": element} for element in range(1, 16)],
    )
    assert out["current_public_squad_available"] is False
    assert out["mini_league_public_available"] is False
    assert out["personal_runtime_files_required"] is False


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
            "100": {
                "entry_id": 100,
                "status": "AVAILABLE",
                "active_chip": None,
                "picks": _ml_picks(
                    list(range(1, 16)),
                    captain=1,
                    vice=2,
                    bench={12, 13, 14, 15},
                ),
            },
            "201": {
                "entry_id": 201,
                "status": "AVAILABLE",
                "active_chip": "bboost",
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
            "starting_xi": list(range(1, 12)),
            "bench": {"gk": 12, "order": [13, 14, 15]},
            "captain": {"element": 1, "name": "P1"},
            "vice_captain": {"element": 2, "name": "P2"},
            "captain_safe_pool": [1, 2],
        },
        mini_overlay={"risk_posture": {"posture": "BALANCED"}},
        disclosed_gw=5,
        operational_action="WAIT",
    )
    return mini, detail, owned


def test_mini_league_deep_materializes_competitive_window_and_threats(monkeypatch):
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

    assert detail["denominator_scopes"]["LEAGUE"] == {
        "label": "LEAGUE3_INCL_US",
        "expected": 3,
        "collected": 3,
        "denominator": 3,
        "includes_us": True,
    }
    assert detail["denominator_scopes"]["RIVALS"]["denominator"] == 2
    assert detail["denominator_scopes"]["COMPETITIVE"]["label"] == "COMPETITIVE_WINDOW"
    assert detail["denominator_scopes"]["COMPETITIVE"]["expected"] == 2
    league_p1 = next(
        row for row in detail["league_our15_exposure"]
        if row["element_id"] == 1
    )
    assert league_p1["denominator"] == 3
    assert league_p1["eo_supported"] is True
    assert detail["competitive_window"]["denominator"] == 2
    assert detail["competitive_window"]["complete"] is True
    assert [row["rank"] for row in detail["competitive_rivals"]] == [1, 2]
    assert detail["competitive_rivals"][0]["overlap_count"] == 14
    assert detail["competitive_rivals"][0]["xi_overlap_count"] >= 1
    assert detail["competitive_rivals"][0]["bench_overlap_count"] >= 1
    assert detail["competitive_rivals"][0]["active_chip"] == "bboost"
    assert detail["competitive_rivals"][0]["shields"]
    assert detail["competitive_window_threats"]
    assert detail["captain_leverage"]
    assert all(
        row["element_id"] in set(range(1, 12))
        for row in detail["captain_leverage"]
    )
    assert all(
        "expected_rank_utility" not in row
        for row in detail["captain_leverage"]
    )
    assert all(
        row.get("exposure_leverage_class")
        for row in detail["captain_leverage"]
    )
    assert detail["disclosed_picks_label"] == "BEHAVIOURAL BASELINE"
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
    assert "DENOMINATOR SCOPES" in body
    assert "All managers including us" in body
    assert "All managers excluding us" in body
    assert "COMPETITIVE WINDOW" in body
    assert "OUR15 LEAGUE" in body
    assert "OUR15 RIVALS" in body
    assert "OUR15 COMPETITIVE WINDOW" in body
    assert "COMPETITIVE-WINDOW RIVAL-ONLY THREATS" in body
    assert "CAPTAIN LANDSCAPE" in body
    assert "Competitive C" in body
    assert "Competitive EO" in body
    assert "| Class |" in body
    assert "COMPETITIVE RIVALS" in body
    assert "Position vs us" in body
    for token in ("Owned", "Starter", "Captain", "EO"):
        assert token in body


def test_stage_c_captain_surface_uses_final_xi_and_p1_7_safe_pool(monkeypatch):
    _, detail, owned = _ml_deep_fixture(monkeypatch)
    lineup = {
        "starting_xi": list(range(1, 12)),
        "bench": {"gk": 12, "order": [13, 14, 15]},
        "captain": {"element": 1, "name": "P1"},
        "vice_captain": {"element": 2, "name": "P2"},
        "captain_safe_pool": [1, 2],
        "formation": "3-5-2",
    }
    surface = runner._captain_decision_surface(
        owned=owned,
        lineup=lineup,
        lineup_state="COMPLETE",
        mini_detail=detail,
    )
    assert surface["decision_state"] == "PREPARE"
    assert surface["candidate_universe_proof"]["captain_in_current15"] is True
    assert surface["candidate_universe_proof"]["vice_in_current15"] is True
    assert surface["candidate_universe_proof"]["captain_in_final_xi"] is True
    assert surface["candidate_universe_proof"]["vice_in_final_xi"] is True
    assert surface["candidate_universe_proof"]["frontier_subset_of_final_xi"] is True
    assert surface["mini_league_override_applied"] is False
    assert surface["near_tie_authority"]["source"] == "V12_CAPTAIN_FRONTIER_P1_3B_PMF"
    assert surface["near_tie_authority"]["classification"] == "FRAGILE"
    assert surface["captain_safe_pool_semantics"] == "P1_7_COMPATIBILITY_ONLY_NOT_FRONTIER"


def test_stage_c_s19_explicitly_consumes_s08_and_s15b(monkeypatch):
    _, detail, owned = _ml_deep_fixture(monkeypatch)
    lineup = {
        "starting_xi": list(range(1, 12)),
        "bench": {"gk": 12, "order": [13, 14, 15]},
        "captain": {"element": 1, "name": "P1"},
        "vice_captain": {"element": 2, "name": "P2"},
        "captain_safe_pool": [1],
        "formation": "3-5-2",
    }
    captain_surface = runner._captain_decision_surface(
        owned=owned,
        lineup=lineup,
        lineup_state="COMPLETE",
        mini_detail=detail,
    )
    judgement = runner._final_judgement_surface(
        operational_action="WAIT",
        stage3_decision={
            "selected_route_id": "HOLD",
            "action_contract": "FRESH_DEADLINE_EVIDENCE",
        },
        stage3_visible={
            "package_routes": [
                {"route": "HOLD", "executable": True},
            ]
        },
        lineup=lineup,
        captain_surface=captain_surface,
        mini_detail=detail,
        staging={
            "contingency": "WATCH",
            "staging_rows": [{"timing": "GW+1"}],
        },
        chip_state=None,
    )
    assert judgement["consumed_sections"] == ["S08", "S15B"]
    assert judgement["decision"] == "WAIT"
    assert judgement["transfer_action"] == "NO TRANSFER NOW"
    assert judgement["selected_route_executable"] is True
    assert judgement["football_optimal_captain"]["element_id"] == 1
    assert judgement["final_captain"]["element_id"] == 1
    assert judgement["vice"]["element_id"] == 2
    assert judgement["captain_state"] == "PREPARE"
    assert judgement["football_baseline_preserved"] is True
    assert judgement["mini_league_captain_context"]["label"] == "BEHAVIOURAL BASELINE"


def test_mini_league_s15b_manifest_cannot_regress_to_compact_summary():
    required = set(DEEP_HUMAN_SECTION_REQUIREMENTS["S15B"])
    assert {
        "rank_battle",
        "denominator_scopes",
        "league_our15_exposure",
        "rivals_our15_exposure",
        "competitive_window",
        "competitive_rivals",
        "competitive_our15_exposure",
        "competitive_window_threats",
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
    challenger = surface["package_universe_challengers"][0]
    assert challenger["stagec_evidence"]["active_signals"] == ["BREAKOUT"]
    assert challenger["stagec_evidence"]["decision_math_adjustment"] == 0.0
    move = surface["package_routes"][0]["moves"]["in"][0]
    assert move["stagec_evidence"]["hidden_gem"] is True


def test_stage_b_workload_ignores_out_of_window_schedule_events():
    fixtures = [
        {
            "id": 601,
            "event": 6,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-09-27T14:00:00+00:00",
        }
    ]
    schedule = [
        {
            "team_id": 1,
            "player_id": 101,
            "kickoff": "2026-06-01T18:00:00+00:00",
            "competition": "Old international",
            "competition_category": "INTERNATIONAL",
            "cross_border": True,
            "long_haul": True,
            "timezone_shift_hours": 8,
            "confirmed_call_up": True,
        },
        {
            "team_id": 1,
            "player_id": 101,
            "kickoff": "2026-12-01T18:00:00+00:00",
            "competition": "Future international",
            "competition_category": "INTERNATIONAL",
            "cross_border": True,
            "long_haul": True,
            "timezone_shift_hours": 9,
            "confirmed_call_up": True,
        },
    ]
    context = build_calendar_workload_context(
        planning_gw=6,
        pl_fixtures=fixtures,
        team_ids=[1, 2],
        relevant_players=[{"element_id": 101, "name": "P101", "team_id": 1}],
        verified_schedule_events=schedule,
        non_pl_schedule_authority=True,
        report_timestamp="2026-09-26T00:00:00+00:00",
    )
    player = context["player_workload"][0]
    assert context["gw_topology"] == "NORMAL_GW"
    assert context["period_flags"]["international_schedule_present"] is False
    assert player["load_state"] == "NORMAL LOAD"
    assert player["long_haul"] is False
    assert player["cross_border_travel"] is False
    assert player["timezone_shift_hours"] == 0.0
    assert player["confirmed_call_up"] is False



def _compact_previous_sections_fixture() -> dict:
    ids = [section_id for section_id, _ in runner.CANONICAL_DEEP_SECTIONS]
    sections = {
        section_id: {
            "label": section_id,
            "state": "COMPLETE",
            "source_state": "CURRENT",
            "degradation_reason": None,
            "content": {
                "presentation_status": "CURRENT",
                "authoritative_binding": {"occurrence_bound": True},
            },
        }
        for section_id in ids
    }
    sections["S01"]["content"].update({
        "decision_dashboard": {"TRANSFER": "WAIT"},
        "operational_state": "WAIT",
        "primary_decision": "HOLD",
    })
    sections["S02"]["content"]["rows"] = [{
        "element_id": 101,
        "player": "P101",
        "p_start": 0.91,
        "xmins": 82,
        "projection_1gw": 5.4,
        "availability": 1.0,
        "tactical_role_label": "STARTER",
        "price_relevance": "WATCH",
    }]
    sections["S06"]["content"].update({
        "formation": "4-4-2",
        "starting_xi": [{"element_id": 101}],
        "bench": {"gk": 102, "order": [103, 104, 105]},
        "captain": 101,
        "vice_captain": 106,
    })
    sections["S09"]["content"]["chip"] = "NO CHIP"
    sections["S15B"]["content"]["rank_battle"] = [
        {"is_us": False, "rank": 1, "total_points": 360, "manager": "Leader"},
        {"is_us": True, "rank": 7, "total_points": 344, "manager": "Us"},
        {"is_us": False, "rank": 8, "total_points": 341, "manager": "Below"},
    ]
    sections["S17"]["content"]["source_health"] = {"finance": "AVAILABLE"}
    sections["S19"]["content"]["final_judgement"] = {
        "decision": "WAIT",
        "transfer_action": "WAIT",
        "selected_route_id": "HOLD",
        "xi": [101],
        "bench_gk": 102,
        "bench_order": [103, 104, 105],
        "formation": "4-4-2",
        "final_captain": 101,
        "vice": 106,
    }
    return sections


def test_compact_previous_deep_lkg_preserves_decision_delta_inputs(tmp_path: Path):
    previous = tmp_path / "previous"
    sections = _compact_previous_sections_fixture()
    payload = {
        "schema_version": 1,
        "artifact_kind": "V12_PREVIOUS_DEEP_BASELINE",
        "report_mode": "DEEP",
        "report_slot": "2026-10-01T04:30:00+07:00",
        "occurrence_id": "DEEP|2026-10-01T04:30:00+07:00",
        "planning_gw": 6,
        "delivery_status": "READY_FULL",
        "runner_status": "PASS",
        "pre_render_status": "PASS",
        "post_render_status": "PASS",
        "human_facing_status": "PASS",
        "decision": "WAIT",
        "section_ids": list(sections),
        "canonical_section_ids": list(sections),
        "sections": sections,
        "canonical_bundle_sha256": "a" * 64,
        "canonical_body_sha256": "b" * 64,
        "math_recomputed": False,
    }
    _write(previous / "previous_deep_baseline.json", payload)

    loaded = runner._load_previous_visible_deep_baseline(
        previous,
        current_report_slot="2026-10-01T12:30:00+07:00",
    )
    assert loaded["state"] == "AVAILABLE"
    assert loaded["source"] == "COMPACT_PREVIOUS_DEEP_LKG_CANONICAL_PROJECTION"
    assert loaded["report_slot"] == "2026-10-01T04:30:00+07:00"
    assert loaded["math_recomputed"] is False

    snapshot = runner._decision_snapshot_from_report(loaded["report"])
    assert snapshot == {
        "operational_transfer_action": "WAIT",
        "selected_transfer_route": "HOLD",
        "xi": [101],
        "bench_gk": 102,
        "bench_order": [103, 104, 105],
        "formation": "4-4-2",
        "captain": 101,
        "vice": 106,
        "player_state": {
            "101": {
                "player": "P101",
                "p_start": 0.91,
                "xmins": 82,
                "projection_1gw": 5.4,
                "availability": 1.0,
                "role": "STARTER",
                "price_urgency": "WATCH",
            }
        },
        "mini_league": {
            "our_rank": 7,
            "our_points": 344,
            "leader_gap": 16,
            "top3_gap": None,
            "top5_gap": None,
            "nearest_above": None,
            "nearest_below": {"manager": "Below", "gap": -3},
        },
        "finance_state": "AVAILABLE",
        "chip_state": "NO CHIP",
    }


def test_latest_serving_compat_is_strictly_transitional_canonical_copy(tmp_path: Path):
    previous = tmp_path / "previous"
    sections = _compact_previous_sections_fixture()
    _write(previous / "serving_report.json", {
        "schema_version": 2,
        "occurrence_id": "DEEP|2026-10-01T04:30:00+07:00",
        "report_mode": "DEEP",
        "report_slot": "2026-10-01T04:30:00+07:00",
        "delivery_status": "READY_FULL",
        "sections": sections,
    })
    _write(previous / "deep.json", {
        "report_mode": "DEEP",
        "report_slot": "2026-10-01T04:30:00+07:00",
        "runner_status": "PASS",
        "pre_render_status": "PASS",
        "post_render_status": "PASS",
        "human_facing_status": "PASS",
        "canonical_bundle_sha256": "c" * 64,
        "canonical_body_sha256": "d" * 64,
        "math_recomputed": False,
    })
    loaded = runner._load_previous_visible_deep_baseline(
        previous,
        current_report_slot="2026-10-01T12:30:00+07:00",
    )
    assert loaded["state"] == "AVAILABLE"
    assert loaded["source"] == "LATEST_SERVING_COMPAT_CANONICAL_COPY"
    assert loaded["math_recomputed"] is False



def test_natural_regression_truthful_s03_s05_degradation_is_not_internal_failure():
    sections = {
        "S03": {
            "state": "DEGRADED",
            "degradation_reason": (
                "previous valid visible DEEP baseline is unavailable under "
                "the current semantic contract"
            ),
            "content": {
                "decision_delta": {
                    "baseline_state": "UNAVAILABLE",
                    "baseline_requirement": "PREVIOUS_VALID_VISIBLE_DEEP",
                    "rows": [],
                }
            },
        },
        "S05": {
            "state": "DEGRADED",
            "degradation_reason": (
                "verified non-PL first-team schedule source is not bound for "
                "this occurrence; PL topology remains authoritative"
            ),
            "content": {
                "competition_coverage": {
                    "official_pl": True,
                    "verified_non_pl_schedule_bound": False,
                    "verified_non_pl_event_count": 0,
                }
            },
        },
    }
    allowed, failures = _truthful_source_degraded_sections(sections)
    assert allowed == {"S03", "S05"}
    assert failures == []


def test_natural_regression_s03_s05_degradation_does_not_get_blanket_whitelist():
    sections = {
        "S03": {
            "state": "DEGRADED",
            "degradation_reason": "internal renderer error",
            "content": {
                "decision_delta": {
                    "baseline_state": "UNAVAILABLE",
                    "baseline_requirement": "PREVIOUS_VALID_VISIBLE_DEEP",
                    "rows": [],
                }
            },
        },
        "S05": {
            "state": "DEGRADED",
            "degradation_reason": "internal schedule model error",
            "content": {
                "competition_coverage": {
                    "official_pl": True,
                    "verified_non_pl_schedule_bound": False,
                    "verified_non_pl_event_count": 0,
                }
            },
        },
    }
    allowed, failures = _truthful_source_degraded_sections(sections)
    assert allowed == set()
    assert "S03_DEGRADED_NOT_TRUTHFUL_BASELINE_UNAVAILABILITY" in failures
    assert "S05_DEGRADED_NOT_TRUTHFUL_NON_PL_SOURCE_GAP" in failures


def test_core_slot_binding_preserves_exact_half_hour_governed_slot():
    result = runner._core_slot_binding(
        report_slot="2026-09-29T21:30:00+07:00",
        publish_integrity={
            "status": "PASS",
            "logical_slot": "2026-09-29T21:30:00+07:00",
        },
    )
    assert result["status"] == "PASS"
    assert result["reason"] is None
    assert result["expected_core_slot"] == "2026-09-29T21:30:00+07:00"
    assert result["actual_core_slot"] == "2026-09-29T21:30:00+07:00"


def test_core_slot_binding_fails_closed_on_nearby_but_wrong_slot():
    result = runner._core_slot_binding(
        report_slot="2026-09-29T21:30:00+07:00",
        publish_integrity={
            "status": "PASS",
            "logical_slot": "2026-09-29T21:00:00+07:00",
        },
    )
    assert result["status"] == "PARTIAL"
    assert result["reason"] == "CORE_SLOT_MISMATCH"


def test_s04_report_time_evidence_binding_is_live_in_core_regression():
    from src.engines.v12_material_news import build_report_time_material_news

    rows = build_report_time_material_news(
        {
            "contract": "report_time_evidence_v1",
            "signals": [
                {
                    "source_id": "premier_league_official_news",
                    "source_class": "VERIFIED_NEWS",
                    "topic": "AVAILABILITY",
                    "subject": "P7",
                    "stance": "HOLD",
                    "observed_at": "2026-10-03T04:00:00Z",
                    "source_url": "https://www.premierleague.com/example",
                    "summary": "Manager confirms P7 trained.",
                },
                {
                    "source_id": "rotowire",
                    "source_class": "SECONDARY_AVAILABILITY",
                    "topic": "PREDICTED_LINEUP",
                    "subject": "P8",
                    "stance": "START",
                    "observed_at": "2026-10-03T04:10:00Z",
                    "source_url": "https://www.rotowire.com/example",
                    "summary": "P8 projected to start.",
                },
                {
                    "source_id": "reddit_fantasypl",
                    "source_class": "COMMUNITY_SIGNAL",
                    "topic": "ROTATION_OBSERVATION",
                    "subject": "P7",
                    "stance": "BENCH",
                    "observed_at": "2026-10-03T04:20:00Z",
                    "source_url": "https://www.reddit.com/r/FantasyPL/example",
                    "summary": "Possible P7 benching is circulating.",
                },
            ],
        },
        {
            "teams": [{"id": 1, "name": "Test FC"}],
            "elements": [
                {"id": 7, "web_name": "P7", "team": 1},
                {"id": 8, "web_name": "P8", "team": 1},
            ],
        },
        our_element_ids=[7],
        watchlist_element_ids=[8],
        report_timestamp="2026-10-03T12:30:00+07:00",
    )
    assert [row["source_class"] for row in rows] == [
        "OFFICIAL",
        "RELIABLE_REPORT",
        "RUMOR / UNVERIFIED",
    ]
    assert rows[0]["audience"] == "OUR15"
    assert rows[1]["audience"] == "WATCHLIST / TARGETS"
    assert rows[2]["evidence_status"] == "UNVERIFIED"
    assert all(row["act_authority"] is False for row in rows)
