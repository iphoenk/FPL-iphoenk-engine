from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one replacement in {path}, got {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


owned = "src/services/owned_challenger_decision_service.py"
replace_once(
    owned,
    "def build() -> dict[str, Any]:\n",
    "def build(*, canonical_arbitration: dict[str, Any] | None = None) -> dict[str, Any]:\n",
)
replace_once(
    owned,
    '    decision_pipeline = read_json(DATA / "decision_pipeline_v4.json", {})\n    decision_arbitration = read_json(DATA / "decision_arbitration_v4.json", {})\n',
    '    decision_pipeline = read_json(DATA / "decision_pipeline_v4.json", {})\n    decision_arbitration = (\n        canonical_arbitration\n        if isinstance(canonical_arbitration, dict)\n        else read_json(DATA / "decision_arbitration_v4.json", {})\n    )\n',
)
replace_once(
    owned,
    "def run() -> dict[str, Any]:\n    out = build()\n",
    "def run(*, canonical_arbitration: dict[str, Any] | None = None) -> dict[str, Any]:\n    out = build(canonical_arbitration=canonical_arbitration)\n",
)

optimization = "src/services/optimization_slo_service.py"
replace_once(
    optimization,
    "    challenger = run_owned_challenger_decision()\n",
    '    challenger = run_owned_challenger_decision(canonical_arbitration=out.get("canonical_resolution"))\n',
)

housekeeping = "tests/test_v496_housekeeping_integrity.py"
replace_once(
    housekeeping,
    '        "decision_pipeline",\n    }\n',
    '        "decision_pipeline",\n        "owned_challenger_decision",\n    }\n',
)

weather_test = "tests/test_v4_weather_overlay_context_reuse.py"
replace_once(
    weather_test,
    '        return {"timings": {"total_pipeline_ms": 1.0}}\n',
    '        return {\n            "timings": {"total_pipeline_ms": 1.0},\n            "canonical_resolution": {\n                "contract": "CANONICAL_DECISION_ARBITRATION_V1",\n                "overall_action": "REVIEW",\n            },\n        }\n',
)

print("V4 red audit QA/QC fixes applied")
