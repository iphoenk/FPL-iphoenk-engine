from src.engines.v12_independent_counterpart import assess_counterpart


def test_missing_independent_data_is_not_green():
    x = assess_counterpart({"subject":"Palmer","metric":"xPts","value":2.63,
        "horizon":"GW7","as_of":"2026-10-16T21:30:00+07:00",
        "deadline":"2026-10-17T17:00:00+07:00"}, [])
    assert x["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_material_disagreement_is_contested():
    base = {"subject":"Palmer","metric":"xPts","value":2.63,
        "horizon":"GW7","as_of":"2026-10-16T21:30:00+07:00",
        "deadline":"2026-10-17T17:00:00+07:00"}
    ext = [{"source":"Independent","independence_group":"independent",
        "metric":"xPts","horizon":"GW7","value":4.7,
        "as_of":"2026-10-16T20:00:00+07:00"}]
    assert assess_counterpart(base,ext)["verdict"] == "CONTESTED"


def test_incompatible_metrics_are_not_equated():
    base = {"subject":"Palmer","metric":"xPts","value":2.63,
        "horizon":"GW7","as_of":"2026-10-16T21:30:00+07:00",
        "deadline":"2026-10-17T17:00:00+07:00"}
    ext = [{"source":"Understat","independence_group":"understat",
        "metric":"xGI_per90","horizon":"GW1-GW6","value":0.67,
        "as_of":"2026-10-16T20:00:00+07:00"}]
    assert assess_counterpart(base,ext)["verdict"] == "INSUFFICIENT_EVIDENCE"
