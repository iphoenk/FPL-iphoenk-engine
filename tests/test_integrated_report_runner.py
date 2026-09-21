from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines import v12_integrated_report_runner as runner
from src.engines.visible_content_proof import canonical_mode_contract
from src.engines.v12_report_orchestration import _render_math_stack_lines


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
            "starting_xi": list(range(1, 12)),
            "bench": {"gk": 2, "order": [12, 13, 14, 15]},
            "captain": {"element": 10},
            "vice_captain": {"element": 8},
            "lineup_score": {"xpts_mean": 55.0},
            "main_starting_xi_battle": {"status": "AVAILABLE"},
            "formation_comparison": [],
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
    assert len(actual) == 20
    assert "S15B" in actual
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
