from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "profile-output" / "v4-hotspot-probe.json"


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def main() -> None:
    for path in (DATA / "predictions_base_hot_cache_v4.json", DATA / "decision_hot_cache_v4.json"):
        path.unlink(missing_ok=True)
    started = perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "src.services.orchestrator", "daily", "--stats", "--deep-stats"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    wall_ms = round((perf_counter() - started) * 1000.0, 3)
    if proc.returncode:
        raise SystemExit(proc.stderr[-4000:] or proc.stdout[-4000:])
    orchestration = load(DATA / "service_orchestration_v4.json")
    latest = load(DATA / "latest.json")
    decision = load(DATA / "decision_pipeline_v4.json")
    health = load(DATA / "framework_health_v4.json")
    rows = {row.get("id"): row for row in orchestration.get("services") or []}
    payload = {
        "wall_ms": wall_ms,
        "orchestrator_internal_ms": orchestration.get("duration_ms"),
        "prediction_service_ms": (rows.get("prediction") or {}).get("duration_ms"),
        "optimization_service_ms": (rows.get("optimization") or {}).get("duration_ms"),
        "governance_service_ms": (rows.get("governance") or {}).get("duration_ms"),
        "prediction_performance": latest.get("performance") or {},
        "decision_timings": decision.get("timings") or {},
        "postflight_performance": health.get("postflight_service_performance") or {},
        "service_stdout_tail": {
            key: (rows.get(key) or {}).get("stdout_tail")
            for key in ("prediction", "validation", "optimization", "governance")
        },
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
