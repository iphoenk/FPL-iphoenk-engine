from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ServiceRequest:
    operation: str
    payload: dict[str, Any] = field(default_factory=dict)
    contract_version: str = "v1"
    correlation_id: str | None = None


@dataclass(frozen=True)
class ServiceResponse:
    service_id: str
    operation: str
    ok: bool
    data: Any = None
    error: str | None = None
    contract_version: str = "v1"
    correlation_id: str | None = None
    elapsed_ms: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
