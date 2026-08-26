from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

OBSERVATION_SCHEMA_VERSION = 2
OBSERVATION_CONTRACT = "challenger_observation_v2"
ALLOWED_STATUS = {"AVAILABLE", "CACHED_LAST_KNOWN_GOOD", "STALE", "ERROR"}


def normalize_subject_key(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


@dataclass(frozen=True)
class ChallengerObservation:
    source_id: str
    capability: str
    value: Any
    source_url: str
    fetched_at: str
    observed_at: str
    ttl_seconds: int
    parser_version: str
    subject: dict[str, Any]
    confidence: str | None = None
    provenance: str = "public_read_only"
    status: str = "AVAILABLE"
    stale: bool = False
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in ALLOWED_STATUS:
            raise ValueError(f"invalid observation status: {self.status}")
        if not self.source_id or not self.capability:
            raise ValueError("source_id and capability are required")
        if not str(self.source_url).startswith("https://"):
            raise ValueError("challenger observation source_url must be https")
        if int(self.ttl_seconds) <= 0:
            raise ValueError("ttl_seconds must be positive")
        if self.status == "AVAILABLE" and self.value is None:
            raise ValueError("AVAILABLE observation requires a value")

    @property
    def subject_key(self) -> str:
        return normalize_subject_key(self.subject.get("player") or self.subject.get("name") or self.subject.get("key"))

    @property
    def observation_key(self) -> str:
        return f"{self.source_id}:{self.capability}:{self.subject_key}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": OBSERVATION_CONTRACT,
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "provider": self.source_id,
            "source_id": self.source_id,
            "capability": self.capability,
            "status": self.status,
            "value": self.value,
            "subject": self.subject,
            "subject_key": self.subject_key,
            "observation_key": self.observation_key,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "observed_at": self.observed_at,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "stale": bool(self.stale),
            "ttl_seconds": int(self.ttl_seconds),
            "parser_version": self.parser_version,
            "error": self.error,
        }
