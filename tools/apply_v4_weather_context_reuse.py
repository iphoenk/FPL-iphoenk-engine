from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"patch seam not found: {label}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_decision_pipeline() -> None:
    path = ROOT / "src/engines/v4_decision_pipeline.py"
    replace_once(
        path,
        "def run():\n    t0 = perf_counter()",
        "def run(*, runtime_context: dict | None = None):\n    t0 = perf_counter()",
        "decision runtime context parameter",
    )
    replace_once(
        path,
        "    atomic_json(OUTFILE, out)\n    print(json.dumps({",
        "    if runtime_context is not None:\n"
        "        # Same-process immutable reuse only. These objects were parsed from\n"
        "        # the governed prediction/universe artifacts above; the weather\n"
        "        # overlay would otherwise parse the identical files again.\n"
        "        runtime_context[\"predictions\"] = predictions\n"
        "        runtime_context[\"universe\"] = universe\n"
        "    atomic_json(OUTFILE, out)\n"
        "    print(json.dumps({",
        "decision runtime context export",
    )


def patch_optimization_service() -> None:
    path = ROOT / "src/services/optimization_slo_service.py"
    replace_once(
        path,
        "    out = run_decision_pipeline()\n\n    weather_started = perf_counter()\n    tactical = apply_weather_overlay()",
        "    runtime_context: dict = {}\n"
        "    out = run_decision_pipeline(runtime_context=runtime_context)\n\n"
        "    weather_started = perf_counter()\n"
        "    tactical = apply_weather_overlay(\n"
        "        predictions=runtime_context.get(\"predictions\"),\n"
        "        universe=runtime_context.get(\"universe\"),\n"
        "    )",
        "optimization weather same-process reuse",
    )


def write_regression_test() -> None:
    path = ROOT / "tests/test_v4_weather_overlay_context_reuse.py"
    path.write_text(
        '''from __future__ import annotations\n\n\ndef test_optimization_reuses_decision_prediction_context(monkeypatch):\n    from src.services import optimization_slo_service as service\n\n    predictions = {"players": [{"element": 1}]}\n    universe = {"players": [{"element": 1}]}\n    seen = {}\n\n    def fake_pipeline(*, runtime_context=None):\n        assert runtime_context is not None\n        runtime_context["predictions"] = predictions\n        runtime_context["universe"] = universe\n        return {"timings": {"total_pipeline_ms": 1.0}}\n\n    def fake_overlay(*, predictions=None, universe=None, **kwargs):\n        seen["predictions"] = predictions\n        seen["universe"] = universe\n        return {"weather_context": {"status": "NORMAL"}}\n\n    monkeypatch.setattr(service, "run_decision_pipeline", fake_pipeline)\n    monkeypatch.setattr(service, "apply_weather_overlay", fake_overlay)\n    monkeypatch.setattr(service, "atomic_json", lambda *args, **kwargs: None)\n\n    out = service.run()\n    assert seen["predictions"] is predictions\n    assert seen["universe"] is universe\n    assert out["performance_slo"]["status"] == "PASS"\n\n\ndef test_weather_overlay_keeps_file_fallback_when_context_absent(monkeypatch):\n    from src.engines import v4_weather_tactical_overlay as overlay\n\n    calls = []\n\n    def fake_read(path, default):\n        calls.append(path)\n        if path == overlay.TACTICAL_OUT:\n            return {"owned": [], "watchlist": []}\n        if path == overlay.PREDICTIONS:\n            return {"players": []}\n        if path == overlay.UNIVERSE:\n            return {"players": []}\n        if path == overlay.WEATHER_OUT:\n            return {"health": {"status": "NORMAL"}}\n        return {}\n\n    monkeypatch.setattr(overlay, "read_json", fake_read)\n    monkeypatch.setattr(overlay, "atomic_json", lambda *args, **kwargs: None)\n    overlay.apply_weather_overlay(write=False)\n    assert overlay.PREDICTIONS in calls\n    assert overlay.UNIVERSE in calls\n''',
        encoding="utf-8",
    )


def main() -> None:
    patch_decision_pipeline()
    patch_optimization_service()
    write_regression_test()


if __name__ == "__main__":
    main()
