from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from src.sources.base import SourceResult, SourceSpec
from src.sources.observations import ChallengerObservation
from src.sources.structured_web import embedded_json_documents, fetch_public_document, visible_text, walk_records

PARSER_VERSION = "onefpl-price-v1"

_TEXT_PRICE_RE = re.compile(
    r"(?P<name>[A-Za-zÀ-ÖØ-öø-ÿ0-9.'’ -]{2,45}?)(?P<position>GKP|GK|DEF|MID|FWD)\s+"
    r"(?P<team>[A-Z]{3})\s+(?:[A-Z]{3}\s*)?£(?P<price>\d+(?:\.\d+)?)m?\s+"
    r"(?P<pressure>[+-]?\d+(?:\.\d+)?)%\s*(?P<label>Drop risk|Fall risk|Rise risk|Ready to rise|Ready to fall|Riser|Faller)",
    re.IGNORECASE,
)


def _direction(label: str | None) -> str | None:
    text = str(label or "").strip().lower()
    if any(token in text for token in ("drop", "fall")):
        return "FALL"
    if any(token in text for token in ("rise", "riser")):
        return "RISE"
    return None


def _pick(record: dict[str, Any], *keys: str) -> Any:
    lower = {str(k).lower(): v for k, v in record.items()}
    for key in keys:
        if key.lower() in lower:
            return lower[key.lower()]
    return None


def _json_candidates(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for document in embedded_json_documents(html):
        for record in walk_records(document):
            name = _pick(record, "web_name", "player_name", "name")
            position = _pick(record, "position", "pos", "element_type_name")
            pressure = _pick(record, "pressure_percent", "pressure_pct", "prediction_percent", "progress_percent", "progress_pct")
            label = _pick(record, "risk_label", "prediction_label", "label", "direction")
            price = _pick(record, "price", "now_cost", "cost")
            if name is None or position is None or pressure is None or label is None:
                continue
            try:
                pressure_value = float(str(pressure).replace("%", ""))
            except (TypeError, ValueError):
                continue
            direction = _direction(str(label))
            if direction is None:
                continue
            price_value = None
            if price is not None:
                try:
                    price_value = float(str(price).replace("£", "").replace("m", ""))
                    if price_value > 30:
                        price_value /= 10.0
                except (TypeError, ValueError):
                    price_value = None
            out.append({"player": " ".join(str(name).split()), "position": str(position).upper(), "team": _pick(record, "team_short_name", "team", "club"), "price": price_value, "pressure_pct": pressure_value, "direction": direction, "source_label": str(label)})
    return out


def _text_candidates(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for match in _TEXT_PRICE_RE.finditer(visible_text(html)):
        label = match.group("label")
        direction = _direction(label)
        if direction is None:
            continue
        out.append({"player": " ".join(match.group("name").split()), "position": match.group("position").upper(), "team": match.group("team").upper(), "price": float(match.group("price")), "pressure_pct": float(match.group("pressure")), "direction": direction, "source_label": label})
    return out


def parse_price_observations(html: str, *, source_url: str, fetched_at: str, ttl_seconds: int) -> list[dict]:
    observations: list[dict] = []
    seen: set[str] = set()
    candidates = _json_candidates(html)
    candidates.extend(_text_candidates(html))
    for value in candidates:
        name = str(value.get("player") or "").strip()
        if not name:
            continue
        obs = ChallengerObservation(
            source_id="onefpl",
            capability="price_prediction",
            value=value,
            source_url=source_url,
            fetched_at=fetched_at,
            observed_at=fetched_at,
            ttl_seconds=ttl_seconds,
            parser_version=PARSER_VERSION,
            subject={"player": name, "position": value.get("position"), "team": value.get("team")},
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
