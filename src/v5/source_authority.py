from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.v5.config_cache import load_json_config

REGISTRY_CONFIG = "config/v5_source_authority_registry.json"


@dataclass(frozen=True)
class SourceSpec:
    name: str
    tier: int
    kind: str
    enabled: bool


def _registry() -> dict[str, Any]:
    data = load_json_config(REGISTRY_CONFIG)
    if not isinstance(data.get("sources"), dict) or not isinstance(data.get("domains"), dict):
        raise RuntimeError("invalid V5 source authority registry")
    return data


def source_spec(name: str) -> SourceSpec:
    raw = _registry()["sources"].get(name)
    if not isinstance(raw, dict):
        raise KeyError(f"unknown V5 source: {name}")
    return SourceSpec(
        name=name,
        tier=int(raw.get("tier", 999)),
        kind=str(raw.get("kind", "unknown")),
        enabled=bool(raw.get("enabled", False)),
    )


def authority_chain(domain: str, *, enabled_only: bool = True) -> tuple[SourceSpec, ...]:
    names = _registry()["domains"].get(domain)
    if not isinstance(names, list):
        raise KeyError(f"unknown V5 source domain: {domain}")
    specs = tuple(source_spec(str(name)) for name in names)
    if enabled_only:
        specs = tuple(spec for spec in specs if spec.enabled)
    return specs


def primary_authority(domain: str) -> SourceSpec:
    chain = authority_chain(domain)
    if not chain:
        raise RuntimeError(f"no enabled authority for V5 source domain: {domain}")
    return chain[0]


def may_override(domain: str, candidate: str, incumbent: str) -> bool:
    chain = [spec.name for spec in authority_chain(domain)]
    if candidate not in chain:
        return False
    if incumbent not in chain:
        return True
    return chain.index(candidate) < chain.index(incumbent)
