from __future__ import annotations

import json

import pytest

from src.engines.v12_p4_scenario_production import (
    P4ScenarioProductionError,
    _decision_result,
    _owned_context,
)


def test_decision_result_extracts_required_sections_from_canonical_report():
    bundle = {
        "report": {
            "sections": [
                {"section_id": sid, "content": {"sid": sid}}
                for sid in ("S06", "S08", "S09", "S11", "S12", "S13", "S14", "S15B", "S19")
            ]
        }
    }
    out = _decision_result(bundle)
    assert set(out["decision_surfaces"]) == {"S06", "S08", "S09", "S11", "S12", "S13", "S14", "S15B", "S19"}


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
