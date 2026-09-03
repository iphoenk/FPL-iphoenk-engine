from pathlib import Path


def test_exhaustive_finalizer_does_not_define_second_prediction_or_package_governance_owner():
    text = Path("src/engines/package_optimizer_exhaustive_finalize.py").read_text(encoding="utf-8")
    assert "def score_package" not in text
    assert "def build_package_decision" not in text
    assert "from src.models.package_optimizer_v2 import" in text
    assert "from src.engines.lineup_governance import build_package_decision" in text
