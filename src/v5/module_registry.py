from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.v5.config_cache import load_json_cached

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "config" / "v5_module_registry.json"


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    plane: str
    entrypoint: str
    config: str
    adjustment_surface: tuple[str, ...]
    status: str


def load_module_registry() -> dict[str, Any]:
    data = load_json_cached(REGISTRY_PATH)
    if not isinstance(data, dict) or not isinstance(data.get("modules"), dict):
        raise RuntimeError("invalid V5 module registry")
    return data


def module_specs() -> tuple[ModuleSpec, ...]:
    modules = load_module_registry()["modules"]
    specs = []
    for name, raw in modules.items():
        specs.append(
            ModuleSpec(
                name=str(name),
                plane=str(raw.get("plane", "unknown")),
                entrypoint=str(raw.get("entrypoint", "")),
                config=str(raw.get("config", "")),
                adjustment_surface=tuple(str(x) for x in raw.get("adjustment_surface", [])),
                status=str(raw.get("status", "UNKNOWN")),
            )
        )
    return tuple(specs)


def get_module(name: str) -> ModuleSpec:
    for spec in module_specs():
        if spec.name == name:
            return spec
    raise KeyError(f"unknown V5 module: {name}")


def adjustment_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for spec in module_specs():
        for item in spec.adjustment_surface:
            index[item] = spec.name
    return index
