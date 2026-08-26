from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    name: str
    source_class: str
    tier: int
    enabled: bool
    critical: bool
    adapter: str
    capabilities: tuple[str, ...]
    config: dict[str, Any]


@dataclass(frozen=True)
class SourceResult:
    source_id: str
    status: str
    reachable: bool
    latency_ms: float | None
    observation_count: int
    capabilities: dict[str, str]
    detail: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "reachable": self.reachable,
            "latency_ms": self.latency_ms,
            "observation_count": self.observation_count,
            "capabilities": self.capabilities,
            "detail": self.detail,
        }
