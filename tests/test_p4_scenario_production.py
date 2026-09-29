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
                        "mini_league_overlay": {"stale": True},
                        "governance": {
                            "mini_league_overlay_owner": "P1_8",
                            "mini_league_overlay_downstream_only": True,
                        },
                        "routes": [{"route_id": "HOLD"}],
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
        {"572": {"override_type": "OWNED_UNAVAILABLE", "p_available": 0.0}},
    )

    assert out["stage3_action"] == "WAIT"
    rebind = out["p1_8_rebind_inputs"]
    assert "mini_league_overlay" not in rebind["package_with_stage3"]
    assert "mini_league_overlay_owner" not in rebind["package_with_stage3"]["governance"]
    assert rebind["monte_carlo"]["execution_state"] == "EXECUTED"
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
