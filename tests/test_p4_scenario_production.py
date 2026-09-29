from __future__ import annotations

import json

import pytest

from src.engines.v12_p4_scenario_production import (
    P4ScenarioProductionError,
    _configured_workers,
    _decision_result,
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
