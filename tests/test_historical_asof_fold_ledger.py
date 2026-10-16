from src.engines.v12_historical_asof_fold_ledger import assess_fold, build_ledger

def test_missing_witnesses_fail_closed():
    result = build_ledger()
    assert result["historical_asof"] == "NOT_ESTABLISHED"
    assert all(f["admission"] == "NOT_ESTABLISHED" for f in result["folds"])

def test_gw6_training_rows_alone_cannot_promote():
    e = {"source_integrity": "PASS", "prior_training_rows_asof": "PASS",
         "official_deadline": "2026-10-10T10:00:00Z",
         "last_original_source_at": "2026-09-22T12:29:19Z", "leakage": "ZERO"}
    result = assess_fold(6, e)
    assert result["prior_training_rows_asof"] == "PASS"
    assert result["admission"] == "NOT_ESTABLISHED"
    assert "model_parameters_asof" in result["missing_witnesses"]

def test_postdeadline_source_fails_closed():
    e = {k: "PASS" for k in ("source_integrity", "prior_training_rows_asof",
                            "model_parameters_asof", "prediction_frozen_asof")}
    e.update(official_deadline="2026-10-10T10:00:00Z",
             last_original_source_at="2026-10-11T10:00:00Z", leakage="ZERO")
    assert assess_fold(6, e)["admission"] == "NOT_ESTABLISHED"

def test_complete_witness_shape():
    e = {k: "PASS" for k in ("source_integrity", "prior_training_rows_asof",
                            "model_parameters_asof", "prediction_frozen_asof")}
    e.update(official_deadline="2026-10-10T10:00:00Z",
             last_original_source_at="2026-09-22T12:29:19Z", leakage="ZERO")
    assert assess_fold(6, e)["admission"] == "PASS"
