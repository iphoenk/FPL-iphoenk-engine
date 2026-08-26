from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from src.v5.config_cache import load_json_config

BUDGET_CONFIG = "config/v5_performance_budgets.json"


def load_performance_budgets() -> dict:
    return load_json_config(BUDGET_CONFIG)


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


class PipelineTimer:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.stages: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = round((time.perf_counter() - start) * 1000, 3)

    def report(self) -> dict[str, Any]:
        total_ms = round((time.perf_counter() - self.started) * 1000, 3)
        return {
            "total_ms": total_ms,
            "stages_ms": dict(self.stages),
            "measured_stage_ms": round(sum(self.stages.values()), 3),
        }
