from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prediction_service_publishes_truthful_source_sweep_into_latest():
    source = (ROOT / "src/services/prediction_service.py").read_text()
    assert "build_source_sweep_status" in source
    assert '"source_sweep_status": source_sweep_status' in source
    assert '"source_governance_names_do_not_imply_runtime_adapters": True' in source


def test_source_sweep_resolver_never_promotes_unwired_source_without_evidence():
    source = (ROOT / "src/engines/source_sweep_status.py").read_text()
    assert 'status = "UNAVAILABLE"' in source
    assert "external_evidence" in source
    assert "runtime_wired" in source
