from __future__ import annotations


def test_optimization_reuses_decision_prediction_context(monkeypatch):
    from src.services import optimization_slo_service as service

    predictions = {"players": [{"element": 1}]}
    universe = {"players": [{"element": 1}]}
    seen = {}

    def fake_pipeline(*, runtime_context=None):
        assert runtime_context is not None
        runtime_context["predictions"] = predictions
        runtime_context["universe"] = universe
        return {
            "timings": {"total_pipeline_ms": 1.0},
            "canonical_resolution": {
                "contract": "CANONICAL_DECISION_ARBITRATION_V1",
                "overall_action": "REVIEW",
            },
        }

    def fake_overlay(*, predictions=None, universe=None, **kwargs):
        seen["predictions"] = predictions
        seen["universe"] = universe
        return {"weather_context": {"status": "NORMAL"}}

    def fake_load_price_context():
        prices = {
            "health": {"status": "PASS"},
            "source": "OFFICIAL_FPL",
            "contract": "OFFICIAL_FPL_PRICE_PREDICTOR_V1",
            "all15_actionable_price_radar": [{} for _ in range(15)],
        }
        return prices, [{} for _ in range(20)]

    monkeypatch.setattr(service, "run_decision_pipeline", fake_pipeline)
    monkeypatch.setattr(service, "apply_weather_overlay", fake_overlay)
    monkeypatch.setattr(service, "_load_price_context", fake_load_price_context)
    monkeypatch.setattr(service, "atomic_json", lambda *args, **kwargs: None)

    out = service.run()
    assert seen["predictions"] is predictions
    assert seen["universe"] is universe
    assert out["price_context"]["source"] == "OFFICIAL_FPL"
    assert out["price_context"]["all15_count"] == 15
    assert out["price_context"]["all20_count"] == 20
    assert out["price_context"]["optimization_access"] == "READ_ONLY_JOIN"
    assert out["performance_slo"]["status"] == "PASS"


def test_weather_overlay_keeps_file_fallback_when_context_absent(monkeypatch):
    from src.engines import v4_weather_tactical_overlay as overlay

    calls = []

    def fake_read(path, default):
        calls.append(path)
        if path == overlay.TACTICAL_OUT:
            return {"owned": [], "watchlist": []}
        if path == overlay.PREDICTIONS:
            return {"players": []}
        if path == overlay.UNIVERSE:
            return {"players": []}
        if path == overlay.WEATHER_OUT:
            return {"health": {"status": "NORMAL"}}
        return {}

    monkeypatch.setattr(overlay, "read_json", fake_read)
    monkeypatch.setattr(overlay, "atomic_json", lambda *args, **kwargs: None)
    overlay.apply_weather_overlay(write=False)
    assert overlay.PREDICTIONS in calls
    assert overlay.UNIVERSE in calls
