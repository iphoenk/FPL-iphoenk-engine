from __future__ import annotations

from pathlib import Path

from src.services import architecture_guard_service as guard
from src.services import governance_service as governance


def test_architecture_guard_single_walk_analysis_preserves_facts(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text(
        "import os\nfrom pathlib import Path\nVALUE = 1\n"
        "def alpha():\n    return Path(os.getcwd())\n",
        encoding="utf-8",
    )
    guard._analysis.cache_clear()
    guard._tree.cache_clear()
    guard._text.cache_clear()
    assert guard._assignment_names(source) == {"VALUE"}
    assert guard._top_level_functions(source) == {"alpha"}
    assert {"Path", "getcwd"}.issubset(guard._called_names(source))
    assert guard._imports(source) == {"os", "pathlib"}
    assert guard._analysis.cache_info().misses == 1


def test_governance_reuses_one_immutable_prediction_context(monkeypatch):
    predictions = {"players": [{"element": 1}]}
    latest = {"phase": {"planning_gw": 2}}
    universe = {"players": [{"element": 1}]}
    objects = {
        "predictions_v4.json": predictions,
        "latest.json": latest,
        "universe.json": universe,
        "publication_integrity_v4.json": {},
    }
    reads = []

    def fake_read(path: Path, default=None):
        reads.append(path.name)
        return objects[path.name]

    seen = {}

    def fake_postflight(**kwargs):
        seen["postflight"] = kwargs
        return {"critical_failed": [], "overall": "GREEN"}

    def fake_reconcile(health, **kwargs):
        seen["maturity"] = kwargs
        return {"critical_failed": [], "overall": "GREEN", "capability_health": "GREEN"}

    monkeypatch.setattr(governance, "read_json", fake_read)
    monkeypatch.setattr(governance.framework_postflight_truth_service, "run", fake_postflight)
    monkeypatch.setattr(governance.v4_maturity_reconciler, "reconcile", fake_reconcile)
    monkeypatch.setattr(governance.v4_checkpoint_governance, "run", lambda: {"action_state": "HOLD"})

    out = governance.run()
    assert out["status"] == "PASS"
    assert reads[:3] == ["predictions_v4.json", "latest.json", "universe.json"]
    assert reads.count("predictions_v4.json") == 1
    assert reads.count("latest.json") == 1
    assert reads.count("universe.json") == 1
    assert reads.count("publication_integrity_v4.json") == 1
    for phase in ("postflight", "maturity"):
        assert seen[phase]["predictions"] is predictions
        assert seen[phase]["latest"] is latest
        assert seen[phase]["universe"] is universe
