from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.public_api import FetchSpec

RUNNER_CONFIG = "config/v5_runner_registry.json"


def _resolve_token(value: Any, tokens: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        key = value[1:]
        if key not in tokens:
            raise KeyError(f"missing V5 request-plan token: {key}")
        return tokens[key]
    return value


def request_specs(section: str, tokens: dict[str, Any]) -> dict[str, FetchSpec]:
    cfg = load_json_config(RUNNER_CONFIG)
    raw_section = cfg.get(section)
    if not isinstance(raw_section, dict):
        raise RuntimeError(f"invalid V5 runner request section: {section}")
    specs: dict[str, FetchSpec] = {}
    for name, raw in raw_section.items():
        if not isinstance(raw, dict):
            continue
        when = raw.get("when")
        if when and not tokens.get(str(when)):
            continue
        params = {
            str(key): _resolve_token(value, tokens)
            for key, value in (raw.get("params") or {}).items()
        }
        specs[str(name)] = FetchSpec(route=str(raw["route"]), params=params)
    return specs
