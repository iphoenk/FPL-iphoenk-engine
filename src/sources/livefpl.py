from __future__ import annotations

import re
from datetime import datetime, timezone

from src.sources.base import SourceResult, SourceSpec
from src.sources.observations import ChallengerObservation
from src.sources.structured_web import fetch_public_document, visible_text

PARSER_VERSION = "livefpl-price-v1"

_PRICE_RE = re.compile(
    r"(?P<name>[A-Za-zÀ-ÖØ-öø-ÿ0-9.'’ -]{2,45}?)\s+"
    r"(?P<position>GKP|GK|DEF|MID|FWD|FW)\s+"
    r"£(?P<price>\d+(?:\.\d+)?)\s+"
    r"(?P<progress>[+-]?\d+(?:\.\d+)?)%\s+"
    r"(?P<predicted>[+-]?\d+(?:\.\d+)?)%"
    r"(?:\s*(?P<eta>Tonight|Tomorrow))?"
    r"(?:\s+(?P<per_hour>[+-]\d+(?:\.\d+)?)%)?",
    re.IGNORECASE,
)


def _direction(value: float) -> str:
    if value > 0:
        return "RISE"
    if value < 0:
        return "FALL"
    return "STABLE"


def parse_price_observations(html: str, *, source_url: str, fetched_at: str, ttl_seconds: int) -> list[dict]:
    observations: list[dict] = []
    seen: set[str] = set()
    for match in _PRICE_RE.finditer(visible_text(html)):
        name = " ".join(match.group("name").split()).strip()
        if not name:
            continue
        predicted = float(match.group("predicted"))
        value = {
            "player": name,
            "position": match.group("position").upper().replace("FW", "FWD"),
            "price": float(match.group("price")),
            "progress_pct": float(match.group("progress")),
            "predicted_pct": predicted,
            "direction": _direction(predicted),
            "eta_label": match.group("eta"),
            "per_hour_pct": float(match.group("per_hour")) if match.group("per_hour") else None,
        }
        obs = ChallengerObservation(
            source_id="livefpl",
            capability="price_prediction",
            value=value,
            source_url=source_url,
            fetched_at=fetched_at,
            observed_at=fetched_at,
            ttl_seconds=ttl_seconds,
            parser_version=PARSER_VERSION,
            subject={"player": name, "position": value["position"]},
            confidence=None,
            provenance="public_page_observed_at_fetch_time",
        ).as_dict()
        if obs["observation_key"] in seen:
            continue
        seen.add(obs["observation_key"])
        observations.append(obs)
    return observations


def probe(spec: SourceSpec, timeout_seconds: float = 2.5) -> SourceResult:
    url = str(spec.config.get("structured_url") or spec.config.get("probe_url") or "").strip()
    ttl = int(spec.config["observation_ttl_seconds"])
    max_bytes = int(spec.config["max_fetch_bytes"])
    document = fetch_public_document(url, timeout_seconds, max_bytes=max_bytes)
    if not document.reachable:
        return SourceResult(spec.source_id, "UNAVAILABLE", False, document.latency_ms, 0, {cap: "UNAVAILABLE" for cap in spec.capabilities}, {"http_status": document.status_code, "error": document.error, "structured_ingestion": True, "parser_version": PARSER_VERSION})

    fetched_at = datetime.now(timezone.utc).isoformat()
    observations = parse_price_observations(document.text, source_url=document.url, fetched_at=fetched_at, ttl_seconds=ttl)
    capability_state = {
        cap: ("AVAILABLE" if cap == "price_prediction" and observations else "SOURCE_REACHABLE_NO_STRUCTURED_OBSERVATION")
        for cap in spec.capabilities
    }
    return SourceResult(
        spec.source_id,
        "LIVE",
        True,
        document.latency_ms,
        len(observations),
        capability_state,
        {"http_status": document.status_code, "content_type": document.content_type, "structured_ingestion": True, "parser_version": PARSER_VERSION, "data_values_ingested": bool(observations), "no_fabrication": True},
        tuple(observations),
    )
