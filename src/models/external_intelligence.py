from __future__ import annotations

"""Shared, non-authoritative external evidence contract.

This module deliberately contains no score, weighting, optimizer, or decision
authority. It normalizes lineage and classifies evidence relative to a
canonical value so callers can explain disagreement without creating a vote.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable


CURRENT_STATES = {"AVAILABLE_CURRENT"}
STALE_STATES = {"AVAILABLE_STALE", "STALE"}
UNAVAILABLE_STATES = {
    "UNAVAILABLE",
    "SOURCE_UNAVAILABLE",
    "HTTP_FAILURE",
    "PARSER_DRIFT",
    "NO_RELEVANT_DATA",
    "NOT_MATURE",
    "IDENTITY_UNRESOLVED",
}


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamps must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return parsed


@dataclass(frozen=True)
class ExternalObservation:
    provider: str
    source_class: str
    subject: str
    metric: str
    value: Any
    observed_at: str
    fetched_at: str
    freshness_state: str
    provenance_url: str
    root_family: str
    independence_state: str
    identity_state: str
    parser_version: str
    confidence: str | None = None
    failure_state: str | None = None

    def __post_init__(self) -> None:
        if not self.provider or not self.source_class or not self.subject or not self.metric:
            raise ValueError("provider, source_class, subject, and metric are required")
        _timestamp(self.observed_at)
        _timestamp(self.fetched_at)
        if not str(self.provenance_url).startswith("https://"):
            raise ValueError("provenance_url must be https")
        if self.identity_state != "IDENTITY_RESOLVED":
            raise ValueError("current evidence requires resolved identity")
        if self.freshness_state in CURRENT_STATES and self.value is None:
            raise ValueError("current evidence requires a value")
        if self.independence_state not in {"INDEPENDENT_MODEL", "INDEPENDENT_FACT", "NOT_INDEPENDENT", "UNRESOLVED"}:
            raise ValueError("invalid independence state")

    @property
    def is_independent(self) -> bool:
        return self.independence_state in {"INDEPENDENT_MODEL", "INDEPENDENT_FACT"}

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconcile_observations(
    observations: Iterable[ExternalObservation],
    *,
    canonical_value: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return categorical evidence only; never modifies the canonical value."""
    rows = list(observations)
    current = [
        row
        for row in rows
        if row.freshness_state in CURRENT_STATES
        and row.identity_state == "IDENTITY_RESOLVED"
        and row.value is not None
    ]
    independent = [row for row in current if row.is_independent]
    root_families = sorted({row.root_family for row in independent})
    if not independent:
        if current:
            state = "NOT_INDEPENDENT"
        elif any(row.freshness_state in STALE_STATES for row in rows):
            state = "STALE"
        else:
            state = "UNRESOLVED"
        return {
            "state": state,
            "canonical_value": canonical_value,
            "eligible_count": 0,
            "independent_root_families": [],
            "observations": [row.as_dict() for row in rows],
        }

    comparable = []
    for row in independent:
        try:
            comparable.append(float(row.value))
        except (TypeError, ValueError):
            continue
    if not comparable:
        state = "UNRESOLVED"
    else:
        try:
            canonical = float(canonical_value)
            deltas = [value - canonical for value in comparable]
        except (TypeError, ValueError):
            state = "UNRESOLVED"
        else:
            if all(abs(delta) < 1e-9 for delta in deltas):
                state = "NEUTRAL"
            elif any(delta < -1e-9 for delta in deltas):
                state = "CHALLENGING"
            else:
                state = "SUPPORTING"
    return {
        "state": state,
        "canonical_value": canonical_value,
        "eligible_count": len(independent),
        "independent_root_families": root_families,
        "observations": [row.as_dict() for row in rows],
    }
