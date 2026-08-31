from src.engines.official_fact_publication_gate import _predictor_health


def test_healthy_price_model_health_maps_to_pass():
    latest = {"price_model_health": {"status": "HEALTHY"}}
    assert _predictor_health(latest) == "PASS"


def test_stale_price_model_health_maps_to_degraded():
    latest = {"price_model_health": {"status": "STALE"}}
    assert _predictor_health(latest) == "DEGRADED"


def test_unknown_price_model_health_fails_closed():
    latest = {"price_model_health": {"status": "SOMETHING_NEW"}}
    assert _predictor_health(latest) == "UNAVAILABLE"
