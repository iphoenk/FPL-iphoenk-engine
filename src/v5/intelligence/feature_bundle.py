from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

VALID_STATES = {"UNAVAILABLE", "AVAILABLE", "ACTIVE"}

@dataclass
class FeatureState:
    name: str
    state: str
    evidence: Any = None
    reason: str | None = None
    consumed_by: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.state not in VALID_STATES:
            raise ValueError(f"invalid feature state {self.state}")
        if self.state == "ACTIVE" and not self.consumed_by:
            raise ValueError(f"ACTIVE feature {self.name} has no consumption evidence")
        if self.state == "UNAVAILABLE" and self.evidence is not None:
            raise ValueError(f"UNAVAILABLE feature {self.name} cannot carry evidence")

class FeatureBundle:
    def __init__(self) -> None:
        self._items: dict[str, FeatureState] = {}

    def declare(self, name: str, evidence: Any = None, *, reason: str | None = None) -> FeatureState:
        state = "AVAILABLE" if evidence is not None else "UNAVAILABLE"
        row = FeatureState(name=name, state=state, evidence=evidence, reason=reason)
        row.validate(); self._items[name] = row; return row

    def consume(self, name: str, consumer: str) -> FeatureState:
        row = self._items.get(name)
        if row is None or row.state == "UNAVAILABLE":
            raise KeyError(f"cannot consume unavailable feature {name}")
        consumers = tuple(sorted({*row.consumed_by, str(consumer)}))
        row = FeatureState(name=row.name, state="ACTIVE", evidence=row.evidence, reason=row.reason, consumed_by=consumers)
        row.validate(); self._items[name] = row; return row

    def get(self, name: str) -> FeatureState | None:
        return self._items.get(name)

    def snapshot(self) -> dict[str, Any]:
        rows = {}
        counts = {state: 0 for state in sorted(VALID_STATES)}
        for name, row in sorted(self._items.items()):
            row.validate(); raw = asdict(row); raw["consumed_by"] = list(row.consumed_by); rows[name] = raw; counts[row.state] += 1
        return {"schema_version": 1, "states": rows, "counts": counts, "truthful_active_requires_consumption": True}
