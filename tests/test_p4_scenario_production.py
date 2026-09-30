from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from src.engines.v12_p4_scenario_production import (
    P4ScenarioProductionError,
    _configured_workers,
    _decision_result,
    _evaluate_scenario_worker,
    _override_key,
    _owned_context,
    _safe_scenario_failure_diagnostic,
    _scenario_override_specs,
)


def test_decision_result_extracts_all_sections_and_stage3_from_canonical_report():
    bundle = {
        "report": {
            "sections": [
                {"section_id": sid, "content": {"sid": sid}}
                for sid in ("S02", "S06", "S08", "S09", "S14", "S19")
            ]
        },
        "execution_proof": {"stage3_action": "WAIT"},
    }
    out = _decision_result(bundle)
    assert set(out["decision_surfaces"]) == {
        "S02",
        "S06",
        "S08",
        "S09",
        "S14",
        "S19",
    }
    assert out["stage3_action"] == "WAIT"


def test_decision_result_fails_closed_when_surface_missing():
    with pytest.raises(P4ScenarioProductionError, match="missing P4 decision surfaces"):
        _decision_result({"report": {"sections": []}})


def test_owned_context_requires_exact_current15_and_reads_c_vc(tmp_path):
    root = tmp_path / "private"
    path = root / "personal/current_team.json"
    path.parent.mkdir(parents=True)
    players = []
    for element in range(1, 16):
        players.append(
            {
                "element_id": element,
                "captain": element == 1,
                "vice_captain": element == 2,
            }
        )
    path.write_text(json.dumps({"players": players}), encoding="utf-8")
    owned, captain, vice = _owned_context(root)
    assert owned == list(range(1, 16))
    assert captain == 1
    assert vice == 2


def test_parallel_p4_specs_are_complete_unique_and_worker_count_is_bounded(
    monkeypatch,
):
    owned = list(range(1, 16))
    specs = _scenario_override_specs(owned, 1, 2)
    assert len(specs) == 17
    assert [scenario_id for scenario_id, _ in specs[:2]] == [
        "UNAVAILABLE_1",
        "UNAVAILABLE_2",
    ]
    assert specs[-2][0] == "CAPTAIN_UNAVAILABLE"
    assert specs[-1][0] == "VICE_UNAVAILABLE"

    keys = [_override_key(overrides) for _, overrides in specs]
    assert len(keys) == len(set(keys))

    monkeypatch.setenv("V12_P4_MAX_WORKERS", "2")
    assert _configured_workers(len(specs)) == 2
    monkeypatch.setenv("V12_P4_MAX_WORKERS", "1")
    assert _configured_workers(len(specs)) == 1
    monkeypatch.setenv("V12_P4_MAX_WORKERS", "3")
    with pytest.raises(P4ScenarioProductionError, match="governed range"):
        _configured_workers(len(specs))


def test_p4_worker_uses_canonical_private_cache_environment(monkeypatch, tmp_path):
    observed = {}

    def fake_run_deep(**kwargs):
        warm_state_out = Path(kwargs["warm_state_out"])
        warm_state_out.parent.mkdir(parents=True, exist_ok=True)
        warm_state_out.write_text(
            json.dumps(
                {
                    "package_with_stage3": {
                        "model_owner": "V12_PACKAGE_UTILITY",
                        "selected_route_id": "HOLD",
                        "planning_gw": 7,
                        "decision": {"action": "WAIT"},
                        "model_evidence_binding": {"output_fingerprint": "pkg-fp"},
                        "mini_league_overlay": {"stale": True},
                        "routes": [
                            {
                                "route_id": "HOLD",
                                "classification": "HOLD",
                                "players_out": [],
                                "players_in": [],
                                "football_route_utility": {
                                    "per_gw": [
                                        {
                                            "starting_xi": list(range(1, 12)),
                                            "bench_gk": 12,
                                            "bench_order": [13, 14, 15],
                                            "captain": 1,
                                            "vice_captain": 2,
                                        }
                                    ]
                                },
                                "horizons": {
                                    "GW+1": {"net_delta_vs_hold": 0.0},
                                    "3GW": {"net_delta_vs_hold": 0.0},
                                    "5GW": {"net_delta_vs_hold": 0.0},
                                },
                                "robustness": {},
                                "expected_regret": 0.0,
                            }
                        ],
                    },
                    "monte_carlo": {
                        "model_owner": "V12_MONTE_CARLO",
                        "execution_state": "EXECUTED",
                    },
                }
            ),
            encoding="utf-8",
        )
        observed.update({
            "previous_visible_deep_dir": kwargs.get("previous_visible_deep_dir"),
            "stage2": __import__("os").environ.get("V12_STAGE2_DERIVED_CACHE_DIR"),
            "p17": __import__("os").environ.get("V12_P17_DECISION_CACHE_DIR"),
            "mc": __import__("os").environ.get("V12_MC_SIM_CACHE_DIR"),
            "legacy_p17": __import__("os").environ.get("V12_P17_CACHE_DIR"),
            "legacy_mc": __import__("os").environ.get("V12_MC_CACHE_DIR"),
        })
        return {
            "report": {
                "sections": [
                    {"section_id": sid, "content": {"sid": sid}}
                    for sid in ("S02", "S06", "S08", "S09", "S14", "S19")
                ]
            },
            "execution_proof": {
                "stage3_action": "WAIT",
                "p4_scenario_override": {
                    "applied": True,
                    "stage2_cache_bypassed": True,
                },
            },
            "runner_status": "PASS",
        }

    monkeypatch.setattr(
        "src.engines.v12_p4_scenario_production.run_deep",
        fake_run_deep,
    )
    monkeypatch.delenv("V12_P17_CACHE_DIR", raising=False)
    monkeypatch.delenv("V12_MC_CACHE_DIR", raising=False)
    cache_root = tmp_path / "cache"

    out = _evaluate_scenario_worker(
        str(tmp_path / "runtime"),
        str(tmp_path / "private"),
        "2026-09-29T12:30:00+07:00",
        str(tmp_path / "output"),
        str(cache_root),
        str(tmp_path / "previous-deep"),
        {"572": {"override_type": "OWNED_UNAVAILABLE", "p_available": 0.0}},
    )

    assert out["stage3_action"] == "WAIT"
    rebind = out["p1_8_rebind_inputs"]
    assert "mini_league_overlay" not in rebind["package_with_stage3"]
    assert "governance" not in rebind["package_with_stage3"]
    assert rebind["package_with_stage3"]["selected_route_id"] == "HOLD"
    assert rebind["monte_carlo"]["execution_state"] == "EXECUTED"
    assert observed["previous_visible_deep_dir"] == tmp_path / "previous-deep"
    assert observed["stage2"] == str(cache_root / "stage2")
    assert observed["p17"] == str(cache_root / "p17")
    assert observed["mc"] == str(cache_root / "mc")
    assert observed["legacy_p17"] is None
    assert observed["legacy_mc"] is None


def test_p4_executor_recycles_no_scenario_worker_state():
    from src.engines import v12_p4_scenario_production as module

    source = inspect.getsource(module.materialize_p4_package)
    assert 'max_workers=workers' in source
    assert 'mp_context=get_context("spawn")' in source
    assert 'max_tasks_per_child=1' in source


def test_p4_failure_diagnostic_is_bounded_and_private_payload_safe(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("P4_RUNTIME_DATA_SHA", "b" * 40)
    warm_state = tmp_path / "warm.json"
    warm_state.write_text(
        json.dumps(
            {
                "package_with_stage3": {
                    "model_evidence_binding": {"output_fingerprint": "c" * 64},
                    "governance": {
                        "p1_7_execution_proof": {
                            "p17_cache_hits": 4,
                            "p17_cache_misses": 2,
                        }
                    },
                    "PRIVATE_CURRENT15": "DO_NOT_LOG_PRIVATE_TEAM",
                },
                "monte_carlo": {
                    "execution_state": "EXECUTED",
                    "output_fingerprint": "d" * 64,
                    "performance": {"simulation_cache_hit": False},
                    "PRIVATE_REPORT_BODY": "DO_NOT_LOG_REPORT",
                },
            }
        ),
        encoding="utf-8",
    )
    bundle = {
        "runner_status": "FAIL",
        "PRIVATE_CURRENT15": "DO_NOT_LOG_PRIVATE_TEAM",
        "report": {"private_report_body": "DO_NOT_LOG_REPORT"},
        "pre_render_qa": {
            "status": "FAIL",
            "hard_failures": ["P1_7_LINEUP", "unsafe private text"],
        },
        "execution_proof": {
            "p4_scenario_override": {
                "applied": True,
                "stage2_cache_bypassed": True,
            },
            "stage3_guard_failures": [
                "WATCHLIST_COMPLETE",
                "MINI_COVERAGE_FULL",
            ],
            "stage2_derived_cache": {
                "status": "MISS",
                "cache_hit": False,
                "cache_miss": True,
                "cache_write": False,
                "input_fingerprint": "e" * 64,
                "private_payload": "DO_NOT_LOG_CACHE",
            },
            "stages": [
                {"stage": "P1_7_LINEUP", "status": "FAILED", "error": "secret"},
                {"stage": "P1_8_MINI_LEAGUE_OVERLAY", "status": "PASS"},
            ],
        },
    }
    diagnostic = _safe_scenario_failure_diagnostic(
        bundle=bundle,
        scenario_id="UNAVAILABLE_572",
        overrides={
            "572": {
                "override_type": "OWNED_UNAVAILABLE",
                "p_available": 0.0,
                "private": "DO_NOT_LOG_OVERRIDE",
            }
        },
        report_slot="2026-09-29T21:30:00+07:00",
        warm_state_path=warm_state,
    )
    encoded = json.dumps(diagnostic, sort_keys=True)
    assert diagnostic["scenario_id"] == "UNAVAILABLE_572"
    assert diagnostic["override_type"] == "OWNED_UNAVAILABLE"
    assert diagnostic["element_id"] == "572"
    assert diagnostic["failed_gates"] == ["P1_7_LINEUP"]
    assert diagnostic["failed_stages"] == ["P1_7_LINEUP"]
    assert diagnostic["stage3_guard_failures"] == [
        "WATCHLIST_COMPLETE",
        "MINI_COVERAGE_FULL",
    ]
    assert diagnostic["production_sha"] == "a" * 40
    assert diagnostic["runtime_data_sha"] == "b" * 40
    assert diagnostic["stage2_cache_bypassed"] is True
    assert diagnostic["cache_state"]["stage2_status"] == "MISS"
    assert diagnostic["cache_state"]["p17_cache_hits"] == 4
    assert diagnostic["cache_state"]["p17_cache_misses"] == 2
    assert diagnostic["semantic_fingerprints"]["mc_output"] == "d" * 64
    assert "DO_NOT_LOG" not in encoded
    assert "private_report_body" not in encoded
    assert "PRIVATE_CURRENT15" not in encoded


def test_p4_worker_failure_includes_safe_scenario_identity(monkeypatch, tmp_path):
    def fake_run_deep(**kwargs):
        warm_state_out = Path(kwargs["warm_state_out"])
        warm_state_out.parent.mkdir(parents=True, exist_ok=True)
        warm_state_out.write_text(
            json.dumps(
                {
                    "package_with_stage3": {
                        "model_evidence_binding": {"output_fingerprint": "c" * 64}
                    },
                    "monte_carlo": {
                        "execution_state": "EXECUTED",
                        "output_fingerprint": "d" * 64,
                    },
                }
            ),
            encoding="utf-8",
        )
        return {
            "runner_status": "FAIL",
            "pre_render_qa": {
                "status": "FAIL",
                "failures": ["P1_7_LINEUP"],
            },
            "execution_proof": {
                "p4_scenario_override": {
                    "applied": True,
                    "stage2_cache_bypassed": True,
                },
                "stages": [{"stage": "P1_7_LINEUP", "status": "FAILED"}],
            },
            "private_report_body": "DO_NOT_LOG_REPORT",
        }

    monkeypatch.setattr(
        "src.engines.v12_p4_scenario_production.run_deep",
        fake_run_deep,
    )
    with pytest.raises(P4ScenarioProductionError) as exc_info:
        _evaluate_scenario_worker(
            str(tmp_path / "runtime"),
            str(tmp_path / "private"),
            "2026-09-29T21:30:00+07:00",
            str(tmp_path / "output"),
            str(tmp_path / "cache"),
            str(tmp_path / "previous-deep"),
            {"572": {"override_type": "OWNED_UNAVAILABLE", "p_available": 0.0}},
            "UNAVAILABLE_572",
        )
    message = str(exc_info.value)
    assert message.startswith("P4_SCENARIO_FAIL ")
    assert '"scenario_id":"UNAVAILABLE_572"' in message
    assert '"failed_gates":["P1_7_LINEUP"]' in message
    assert "DO_NOT_LOG_REPORT" not in message


def test_parallel_wrapper_preserves_child_scenario_failure_identity(
    monkeypatch, tmp_path
):
    from concurrent.futures import Future
    from src.engines import v12_p4_scenario_production as module

    class FakeIdentity:
        def p4_dependencies(self):
            return {}

    class FakeExecutor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def submit(self, fn, *args):
            future = Future()
            future.set_exception(
                P4ScenarioProductionError(
                    'P4_SCENARIO_FAIL {"scenario_id":"UNAVAILABLE_572"}'
                )
            )
            return future

        def shutdown(self, wait=True, cancel_futures=True):
            return None

    monkeypatch.setattr(module, "_identity", lambda *args: FakeIdentity())
    monkeypatch.setattr(module, "_owned_context", lambda *_: ([572] * 15, 572, 572))
    monkeypatch.setattr(
        module,
        "_evaluate_scenario_worker",
        lambda *args, **kwargs: {"base": True},
    )
    monkeypatch.setattr(
        module,
        "_scenario_override_specs",
        lambda *args: [
            (
                "UNAVAILABLE_572",
                {"572": {"override_type": "OWNED_UNAVAILABLE", "p_available": 0.0}},
            )
        ],
    )
    monkeypatch.setattr(module, "ProcessPoolExecutor", FakeExecutor)

    with pytest.raises(P4ScenarioProductionError) as exc_info:
        module.materialize_p4_package(
            app_root=tmp_path,
            runtime_data_root=tmp_path / "runtime",
            private_root=tmp_path / "private",
            report_slot="2026-09-29T21:30:00+07:00",
            workspace=tmp_path / "workspace",
        )
    assert "UNAVAILABLE_572" in str(exc_info.value)

