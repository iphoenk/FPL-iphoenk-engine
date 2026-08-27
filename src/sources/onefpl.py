from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from src.sources.base import SourceResult, SourceSpec
from src.sources.observations import ChallengerObservation
from src.sources.structured_web import FetchedDocument, embedded_json_documents, fetch_public_document, visible_text, walk_records

PARSER_VERSION = "onefpl-price-v2"

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


def _allowed_url(url: str, allowed_hosts: set[str]) -> bool:
    parsed = urlparse(str(url))
    return parsed.scheme == "https" and bool(parsed.hostname) and parsed.hostname.lower() in allowed_hosts


def _structured_urls(spec: SourceSpec) -> tuple[str, ...]:
    values = [spec.config.get("structured_url")]
    fallbacks = spec.config.get("fallback_structured_urls") or []
    if isinstance(fallbacks, (list, tuple)):
        values.extend(fallbacks)
    allowed_hosts = {str(host).strip().lower() for host in (spec.config.get("allowed_hosts") or []) if str(host).strip()}
    urls: list[str] = []
    for raw in values:
        url = str(raw or "").strip()
        if not url or url in urls:
            continue
        if allowed_hosts and not _allowed_url(url, allowed_hosts):
            continue
        urls.append(url)
    return tuple(urls)


def _attempt_detail(document: FetchedDocument, *, role: str) -> dict[str, Any]:
    return {
        "url": document.url,
        "role": role,
        "reachable": document.reachable,
        "http_status": document.status_code,
        "content_type": document.content_type,
        "latency_ms": document.latency_ms,
        "error": document.error,
    }


def probe(spec: SourceSpec, timeout_seconds: float = 2.5) -> SourceResult:
    ttl = int(spec.config["observation_ttl_seconds"])
    max_bytes = int(spec.config["max_fetch_bytes"])
    probe_url = str(spec.config.get("probe_url") or "").strip()
    allowed_hosts = {str(host).strip().lower() for host in (spec.config.get("allowed_hosts") or []) if str(host).strip()}

    reachability_document: FetchedDocument | None = None
    attempts: list[dict[str, Any]] = []
    if probe_url and (not allowed_hosts or _allowed_url(probe_url, allowed_hosts)):
        reachability_document = fetch_public_document(probe_url, timeout_seconds, max_bytes=max_bytes)
        attempts.append(_attempt_detail(reachability_document, role="reachability_probe"))

    selected_document: FetchedDocument | None = None
    observations: list[dict] = []
    structured_urls = _structured_urls(spec)
    for index, url in enumerate(structured_urls):
        document = fetch_public_document(url, timeout_seconds, max_bytes=max_bytes)
        attempts.append(_attempt_detail(document, role="structured_primary" if index == 0 else "structured_fallback"))
        if not document.reachable:
            continue
        selected_document = document
        fetched_at = datetime.now(timezone.utc).isoformat()
        observations = parse_price_observations(document.text, source_url=document.url, fetched_at=fetched_at, ttl_seconds=ttl)
        if observations:
            break

    source_reachable = bool((reachability_document and reachability_document.reachable) or (selected_document and selected_document.reachable))
    structured_reachable = bool(selected_document and selected_document.reachable)
    structured_attempts = [attempt for attempt in attempts if str(attempt.get("role", "")).startswith("structured_")]
    restricted_statuses = {401, 402, 403, 429}
    structured_access_restricted = any(attempt.get("http_status") in restricted_statuses for attempt in structured_attempts) and not structured_reachable
    primary_structured_http_status = structured_attempts[0].get("http_status") if structured_attempts else None
    structured_http_status = selected_document.status_code if selected_document else (structured_attempts[-1].get("http_status") if structured_attempts else None)

    if observations:
        price_state = "AVAILABLE"
    elif structured_access_restricted and source_reachable:
        price_state = "SOURCE_REACHABLE_STRUCTURED_ACCESS_RESTRICTED"
    elif source_reachable:
        price_state = "SOURCE_REACHABLE_NO_STRUCTURED_OBSERVATION"
    else:
        price_state = "UNAVAILABLE"

    capability_state = {
        cap: (price_state if cap == "price_prediction" else ("SOURCE_REACHABLE_NO_STRUCTURED_OBSERVATION" if source_reachable else "UNAVAILABLE"))
        for cap in spec.capabilities
    }
    status = "LIVE" if source_reachable else "UNAVAILABLE"
    latency_candidates = [doc.latency_ms for doc in (selected_document, reachability_document) if doc and doc.latency_ms is not None]
    latency_ms = min(latency_candidates) if latency_candidates else None

    return SourceResult(
        spec.source_id,
        status,
        source_reachable,
        latency_ms,
        len(observations),
        capability_state,
        {
            "http_status": selected_document.status_code if selected_document else (reachability_document.status_code if reachability_document else None),
            "structured_http_status": structured_http_status,
            "primary_structured_http_status": primary_structured_http_status,
            "content_type": selected_document.content_type if selected_document else None,
            "structured_ingestion": True,
            "parser_version": PARSER_VERSION,
            "data_values_ingested": bool(observations),
            "no_fabrication": True,
            "source_reachability_separate": True,
            "selected_structured_url": selected_document.url if selected_document else None,
            "structured_fallback_used": bool(selected_document and structured_urls and selected_document.url != structured_urls[0]),
            "structured_access_restricted": structured_access_restricted,
            "attempts": attempts,
        },
        tuple(observations),
    )
