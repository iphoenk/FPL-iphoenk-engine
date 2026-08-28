from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

VALID_STATES = {"UNAVAILABLE", "AVAILABLE", "ACTIVE"}
VALID_EFFECT_SCOPES = {
    "OBSERVABILITY_ONLY",
    "SHADOW_OVERLAY",
    "AUTHORITATIVE_XMINS",
    "AUTHORITATIVE_XPTS",
    "DECISION_INPUT",
    "REPORT_ONLY",
}
AUTHORITATIVE_EFFECT_SCOPES = {"AUTHORITATIVE_XMINS", "AUTHORITATIVE_XPTS", "DECISION_INPUT"}


@dataclass(frozen=True)
class ConsumptionEvidence:
    consumer: str
    effect_scope: str
    authoritative_effect: bool
    contribution: Any = None

    def validate(self) -> None:
        if not self.consumer:
            raise ValueError("feature consumption requires a consumer")
        if self.effect_scope not in VALID_EFFECT_SCOPES:
            raise ValueError(f"invalid feature effect scope {self.effect_scope}")
        expected_authoritative = self.effect_scope in AUTHORITATIVE_EFFECT_SCOPES
        if bool(self.authoritative_effect) != expected_authoritative:
            raise ValueError(
                f"feature consumption authoritative flag contradicts scope {self.effect_scope}"
            )


@dataclass
class FeatureState:
    name: str
    state: str
    evidence: Any = None
    reason: str | None = None
    consumed_by: tuple[str, ...] = ()
    consumption_evidence: tuple[ConsumptionEvidence, ...] = ()
    provenance: Any = None
    freshness: Any = None

    def validate(self) -> None:
        if self.state not in VALID_STATES:
            raise ValueError(f"invalid feature state {self.state}")
        if self.state == "ACTIVE" and not self.consumed_by:
            raise ValueError(f"ACTIVE feature {self.name} has no consumption evidence")
        if self.state == "ACTIVE" and not self.consumption_evidence:
            raise ValueError(f"ACTIVE feature {self.name} has no effect-scope evidence")
        if self.state != "ACTIVE" and (self.consumed_by or self.consumption_evidence):
            raise ValueError(f"non-ACTIVE feature {self.name} cannot claim consumption")
        if self.state == "UNAVAILABLE" and self.evidence is not None:
            raise ValueError(f"UNAVAILABLE feature {self.name} cannot carry evidence")
        for row in self.consumption_evidence:
            row.validate()
        evidence_consumers = tuple(sorted({row.consumer for row in self.consumption_evidence}))
        if evidence_consumers != tuple(sorted(self.consumed_by)):
            raise ValueError(f"feature {self.name} consumed_by does not match consumption evidence")

    @property
    def effect_scopes(self) -> tuple[str, ...]:
        return tuple(sorted({row.effect_scope for row in self.consumption_evidence}))

    @property
    def authoritative_effect(self) -> bool:
        return any(row.authoritative_effect for row in self.consumption_evidence)


class FeatureBundle:
    def __init__(self) -> None:
        self._items: dict[str, FeatureState] = {}

    def declare(
        self,
        name: str,
        evidence: Any = None,
        *,
        reason: str | None = None,
        provenance: Any = None,
        freshness: Any = None,
    ) -> FeatureState:
        state = "AVAILABLE" if evidence is not None else "UNAVAILABLE"
        row = FeatureState(
            name=name,
            state=state,
            evidence=evidence,
            reason=reason,
            provenance=provenance,
            freshness=freshness,
        )
        row.validate()
        self._items[name] = row
        return row

    def consume(
        self,
        name: str,
        consumer: str,
        *,
        effect_scope: str = "OBSERVABILITY_ONLY",
        contribution: Any = None,
    ) -> FeatureState:
        row = self._items.get(name)
        if row is None or row.state == "UNAVAILABLE":
            raise KeyError(f"cannot consume unavailable feature {name}")
        scope = str(effect_scope)
        evidence = ConsumptionEvidence(
            consumer=str(consumer),
            effect_scope=scope,
            authoritative_effect=scope in AUTHORITATIVE_EFFECT_SCOPES,
            contribution=contribution,
        )
        evidence.validate()
        consumption = {
            (item.consumer, item.effect_scope): item
            for item in row.consumption_evidence
        }
        consumption[(evidence.consumer, evidence.effect_scope)] = evidence
        evidence_rows = tuple(
            sorted(consumption.values(), key=lambda item: (item.consumer, item.effect_scope))
        )
        consumers = tuple(sorted({item.consumer for item in evidence_rows}))
        updated = FeatureState(
            name=row.name,
            state="ACTIVE",
            evidence=row.evidence,
            reason=row.reason,
            consumed_by=consumers,
            consumption_evidence=evidence_rows,
            provenance=row.provenance,
            freshness=row.freshness,
        )
        updated.validate()
        self._items[name] = updated
        return updated

    def get(self, name: str) -> FeatureState | None:
        return self._items.get(name)

    def snapshot(self) -> dict[str, Any]:
        rows = {}
        counts = {state: 0 for state in sorted(VALID_STATES)}
        authoritative_active = 0
        for name, row in sorted(self._items.items()):
            row.validate()
            raw = asdict(row)
            raw["consumed_by"] = list(row.consumed_by)
            raw["consumption_evidence"] = [asdict(item) for item in row.consumption_evidence]
            raw["effect_scopes"] = list(row.effect_scopes)
            raw["authoritative_effect"] = row.authoritative_effect
            rows[name] = raw
            counts[row.state] += 1
            authoritative_active += int(row.state == "ACTIVE" and row.authoritative_effect)
        return {
            "schema_version": 2,
            "states": rows,
            "counts": counts,
            "authoritative_active_count": authoritative_active,
            "truthful_active_requires_consumption": True,
            "truthful_authoritative_effect_requires_explicit_scope": True,
        }
