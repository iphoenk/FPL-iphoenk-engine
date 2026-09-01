from __future__ import annotations

import json
from pathlib import Path

from src.engines import dss_watchlist


ROOT = Path(__file__).resolve().parents[1]


def test_orphan_challenger_schema_is_retired_but_runtime_contract_remains() -> None:
    assert not (ROOT / "config" / "intelligence" / "challenger_observation_schema.json").exists()

    contracts = json.loads((ROOT / "config" / "runtime" / "artifact_contracts.json").read_text(encoding="utf-8"))
    challenger = contracts["contracts"]["challenger_observations.json"]
    assert challenger["equals"] == {
        "schema_version": 2,
        "contract": "challenger_observation_v2",
    }


def test_dnp_warning_and_admission_thresholds_have_one_policy_authority() -> None:
    policy = json.loads((ROOT / "config" / "intelligence" / "dss_watchlist.json").read_text(encoding="utf-8"))
    admission = policy["admission"]

    assert admission["warning_dnp_probability"] == 0.20
    assert admission["maximum_dnp_probability"] == 0.35
    assert 0.0 <= admission["warning_dnp_probability"] < admission["maximum_dnp_probability"] <= 1.0

    source = (ROOT / "src" / "engines" / "dss_watchlist.py").read_text(encoding="utf-8")
    assert ">= 0.20" not in source
    assert "warning_dnp_probability" in source


def test_dnp_warning_behavior_follows_policy(monkeypatch) -> None:
    policy = {
        "ranking_weights": {},
        "admission": {"warning_dnp_probability": 0.25},
    }
    monkeypatch.setattr(dss_watchlist, "load_policy", lambda: policy)

    def row(dnp_probability: float) -> dict:
        return {
            "normalised_metrics": {},
            "dimensions": {
                "set_piece_penalty": {"status": "SUPPORTED"},
                "role": {"status": "SUPPORTED"},
                "competition": {"status": "SUPPORTED"},
            },
            "projection_confidence": "HIGH",
            "xmins": {"dnp_probability": dnp_probability},
        }

    _, below_risks = dss_watchlist._reasons(row(0.24))
    _, at_risks = dss_watchlist._reasons(row(0.25))

    assert "DNP/rotation risk masih material" not in below_risks
    assert "DNP/rotation risk masih material" in at_risks
