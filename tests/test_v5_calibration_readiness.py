import ast
from pathlib import Path

from src.v5.evaluation.calibration import apply_calibration_readiness, build_calibration_readiness
from src.v5.services import evaluation as evaluation_service

ROOT = Path(__file__).resolve().parents[1]


def _accuracy(sample_size: int, settled_gameweeks: list[int], *, player_gate: bool) -> dict:
    return {
        "overall": {"sample_size": sample_size, "status": "SETTLED" if sample_size else "NO_SETTLED_SAMPLE"},
        "settled_gameweeks": settled_gameweeks,
        # This is the observation-count candidate gate owned by evaluation.core.
        "dynamic_weight_eligible": player_gate,
    }


def test_single_gameweek_cannot_enable_dynamic_weight_even_with_large_player_sample():
    readiness = build_calibration_readiness(_accuracy(500, [1], player_gate=True))
    assert readiness["player_observation_gate_pass"] is True
    assert readiness["temporal_gameweek_gate_pass"] is False
    assert readiness["dynamic_weight_eligible"] is False
    assert readiness["status"] == "COLLECTING_TEMPORAL_SAMPLE"


def test_five_gameweeks_still_require_player_observation_gate():
    readiness = build_calibration_readiness(_accuracy(49, [1, 2, 3, 4, 5], player_gate=False))
    assert readiness["settled_gameweek_count"] == 5
    assert readiness["temporal_gameweek_gate_pass"] is True
    assert readiness["player_observation_gate_pass"] is False
    assert readiness["dynamic_weight_eligible"] is False
    assert readiness["status"] == "TEMPORAL_SAMPLE_READY_OBSERVATION_COUNT_LOW"


def test_three_gameweeks_form_baseline_candidate_but_keep_dynamic_weight_locked():
    readiness = build_calibration_readiness(_accuracy(300, [1, 2, 3], player_gate=True))
    assert readiness["baseline_candidate_eligible"] is True
    assert readiness["dynamic_weight_eligible"] is False
    assert readiness["status"] == "BASELINE_CANDIDATE_DYNAMIC_WEIGHT_LOCKED"


def test_five_gameweeks_and_observation_gate_enable_dynamic_weight():
    accuracy = apply_calibration_readiness(_accuracy(300, [1, 2, 3, 4, 5], player_gate=True))
    assert accuracy["calibration_readiness"]["dynamic_weight_eligible"] is True
    assert accuracy["dynamic_weight_eligible"] is True
    assert accuracy["calibration_readiness"]["status"] == "DYNAMIC_WEIGHT_ELIGIBLE"


def test_zero_settlement_is_explicit_warmup_not_error():
    accuracy = apply_calibration_readiness(_accuracy(0, [], player_gate=False))
    readiness = accuracy["calibration_readiness"]
    assert readiness["status"] == "AWAITING_FIRST_SETTLEMENT"
    assert readiness["baseline_candidate_eligible"] is False
    assert readiness["dynamic_weight_eligible"] is False


def test_calibration_module_does_not_reimplement_prediction_accuracy_metrics():
    path = ROOT / "src/v5/evaluation/calibration.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    forbidden_metric_owners = {
        "mae", "_mae", "brier", "_brier", "spearman", "_spearman", "rmse", "_metrics"
    }
    assert not (names & forbidden_metric_owners)
    source = path.read_text(encoding="utf-8")
    assert 'accuracy.get("dynamic_weight_eligible")' in source
    assert "legacy_player_count_gate_reused_not_recomputed" in source


def test_evaluation_service_applies_readiness_before_scorecard_and_settlement(monkeypatch):
    observed = {}

    def fake_evaluate(*args, **kwargs):
        return {
            "ledger": {"records": {}},
            "accuracy": _accuracy(500, [1], player_gate=True),
        }

    def fake_scorecard(prediction, observations, accuracy):
        observed["scorecard_accuracy"] = accuracy
        return {"status": "OK"}

    def fake_settlement(ledger, accuracy):
        observed["settlement_accuracy"] = accuracy
        return {"status": "OK"}

    monkeypatch.setattr(evaluation_service, "evaluate", fake_evaluate)
    monkeypatch.setattr(evaluation_service, "challenger_scorecard", fake_scorecard)
    monkeypatch.setattr(evaluation_service, "build_settlement_artifact", fake_settlement)
    monkeypatch.setattr(evaluation_service, "evaluate_evidence_guard", lambda *args, **kwargs: {"capabilities": []})

    result = evaluation_service.handle("build", {})
    assert result["accuracy"]["dynamic_weight_eligible"] is False
    assert result["accuracy"]["calibration_readiness"]["settled_gameweek_count"] == 1
    assert observed["scorecard_accuracy"]["dynamic_weight_eligible"] is False
    assert observed["settlement_accuracy"]["dynamic_weight_eligible"] is False
