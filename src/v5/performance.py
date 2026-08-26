from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Any

ROOT = Path(__file__).resolve().parents[2]
BUDGET_PATH = ROOT / "config" / "v5_performance_budgets.json"


def load_performance_budgets() -> dict:
    return json.loads(BUDGET_PATH.read_text(encoding="utf-8"))


def timed(label: str, fn: Callable[..., Any], *args, **kwargs) -> dict:
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return {"label": label, "elapsed_ms": round(elapsed_ms, 3), "result": result}


def within_budget(metric: str, elapsed_ms: float) -> bool:
    budget = load_performance_budgets()["budgets"].get(metric)
    if budget is None:
        raise KeyError(f"Unknown V5 performance budget: {metric}")
    return float(elapsed_ms) <= float(budget)
