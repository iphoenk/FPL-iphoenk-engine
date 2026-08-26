from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Plane(str, Enum):
    TRUTH = "truth"
    INTELLIGENCE = "intelligence"
    GOVERNANCE = "governance"
    DECISION = "decision"


class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM_LOW = "MEDIUM-LOW"
    MEDIUM = "MEDIUM"
    MEDIUM_HIGH = "MEDIUM-HIGH"
    HIGH = "HIGH"


@dataclass(frozen=True)
class EvidenceRef:
    source: str
    field: str
    authority: str
    freshness: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TruthState:
    gameweek: int
    phase: str
    squad_ids: tuple[int, ...]
    bank_tenths: int | None
    team_value_tenths: int | None
    ruleset_id: str
    snapshot_id: str | None = None
    evidence: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class PlayerProjection:
    element_id: int
    expected_minutes: float
    projected_points: float
    horizon_gameweeks: tuple[int, ...]
    components: dict[str, float]
    model_version: str
    ruleset_id: str
    confidence: Confidence
    evidence: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class DecisionTrace:
    decision_type: str
    action: str
    subject_element_ids: tuple[int, ...]
    score: float | None
    confidence: Confidence
    reasons_for: tuple[str, ...]
    reasons_against: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]
    constraints_checked: tuple[str, ...]
    projection_model: str | None = None
    ruleset_id: str | None = None

    def validate(self) -> None:
        if not self.decision_type:
            raise ValueError("decision_type is required")
        if not self.action:
            raise ValueError("action is required")
        if not self.evidence:
            raise ValueError("V5 decisions must carry evidence provenance")
        if not self.constraints_checked:
            raise ValueError("V5 decisions must record checked constraints")


@dataclass(frozen=True)
class AcceptanceCheck:
    name: str
    passed: bool
    plane: Plane
    detail: str


@dataclass(frozen=True)
class AcceptanceReport:
    version: str
    checks: tuple[AcceptanceCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "passed": self.passed,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "plane": c.plane.value,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }
