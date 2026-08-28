from __future__ import annotations

import argparse
import json
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.official_auth import expected_team_id
from src.v5.services.orchestrator_beta import handle as orchestrator_handle

RUNNER_CONFIG = "config/v5_runner_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(RUNNER_CONFIG)
    if not isinstance(data.get("pipeline"), list):
        raise RuntimeError("invalid V5 runner registry")
    return data


def run(mode: str | None = None, *, persist: bool = True, include_predictions: bool = True) -> dict[str, Any]:
    """Compatibility entrypoint for the canonical V5 orchestrator.

    This module must never become an alternate engine path. Official FPL data
    acquisition, truth assembly, prediction, decision, reporting and persistence
    remain owned by the bounded-context microservice workflow.
    """
    cfg = _cfg()
    selected_mode = str(mode or cfg["default_mode"])
    if selected_mode not in {str(value) for value in cfg["modes"]}:
        raise ValueError(f"unsupported V5 runner mode: {selected_mode}")
    if not include_predictions:
        raise ValueError("V5 canonical runner does not support bypassing native prediction")
    result = orchestrator_handle(
        "run",
        {
            "mode": selected_mode,
            "team_id": expected_team_id(),
            "persist": bool(persist),
        },
    )
    if not isinstance(result, dict):
        raise RuntimeError("V5 canonical orchestrator returned a non-object")
    return result


def cli() -> None:
    cfg = _cfg()
    parser = argparse.ArgumentParser(description="FPL iphoenk Engine V5 canonical runner")
    parser.add_argument("mode", choices=tuple(str(value) for value in cfg["modes"]), nargs="?", default=str(cfg["default_mode"]))
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.mode, persist=not args.no_persist), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
