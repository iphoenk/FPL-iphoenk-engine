from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

from src.sources.base import SourceResult, SourceSpec
from src.sources.observations import ChallengerObservation
from src.sources.structured_web import FetchedDocument, fetch_public_document, visible_text

PARSER_VERSION = "livefpl-price-v2"
_NAME = r"[\w.'’ -]{2,60}?"
_PRICE_RE = re.compile(
    rf"(?P<name>{_NAME})\s+(?P<position>GKP|GK|DEF|MID|FWD|FW)\s+"
    r"£(?P<price>\d+(?:\.\d+)?)\s+"
    r"(?P<progress>[+-]?\d+(?:\.\d+)?)%\s+"
    r"(?P<predicted>[+-]?\d+(?:\.\d+)?)%"
    r"(?:\s*(?P<eta>Tonight|Tomorrow))?"
    r"(?:\s+(?P<per_hour>[+-]\d+(?:\.\d+)?)%)?",
    re.IGNORECASE,
)
_ROW_HEAD_RE = re.compile(
    rf"(?P<name>{_NAME})\s+(?P<position>GKP|GK|DEF|MID|FWD|FW)\s+£(?P<price>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"[+-]?\d+(?:\.\d+)?%")
_ETA_RE = re.compile(r"(?:Tonight|Tomorrow|>\s*\d+\s*days?|\d+\s*days?)", re.IGNORECASE)
_POSITION_MAP = {"GKP": "GK", "GK": "GK", "DEF": "DEF", "MID": "MID", "FW": "FWD", "FWD": "FWD"}


class _TableRowsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in {"script", "style", "noscript"}:
            self._ignored += 1
        elif not self._ignored and name == "tr":
            self._row, self._cell = [], None
        elif not self._ignored and name in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in {"script", "style", "noscript"}:
            self._ignored = max(0, self._ignored - 1)
            return
        if self._ignored:
            return
        if name in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join(" ".join(self._cell).split()))
            self._cell = None
        elif name == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row, self._cell = None, None

    def handle_data(self, data: str) -> None:
        if self._ignored or self._cell is None:
            return
        value = " ".join(data.split())
        if value:
            self._cell.append(value)


def _position(value: str) -> str:
    return _POSITION_MAP.get(str(value).upper(), str(value).upper())


def _direction(value: float) -> str:
    return "RISE" if value > 0 else "FALL" if value < 0 else "STABLE"


def _make_observation(
    *,
    name: str,
    position: str,
    price: float,
    progress: float,
    predicted: float,
    eta: str | None,
    per_hour: float | None,
    source_url: str,
    fetched_at: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    normalized_position = _position(position)
    value = {
        "player": name,
        "position": normalized_position,
        "price": price,
        "progress_pct": progress,
        "predicted_pct": predicted,
        "direction": _direction(predicted),
        "eta_label": eta,
        "per_hour_pct": per_hour,
    }
    return ChallengerObservation(
        source_id="livefpl",
        capability="price_prediction",
        value=value,
        source_url=source_url,
        fetched_at=fetched_at,
        observed_at=fetched_at,
        ttl_seconds=ttl_seconds,
        parser_version=PARSER_VERSION,
        subject={"player": name, "position": normalized_position},
        confidence=None,
        provenance="public_page_observed_at_fetch_time",
    ).as_dict()


def _table_rows(html: str) -> list[str]:
    parser = _TableRowsParser()
    parser.feed(html or "")
    return [" ".join(cell for cell in row if cell) for row in parser.rows]


def _parse_table_row(text: str) -> dict[str, Any] | None:
    head = _ROW_HEAD_RE.search(text)
    if head is None:
        return None
    remainder = text[head.end():]
    percentages = list(_PERCENT_RE.finditer(remainder))
    if len(percentages) < 2:
        return None
    eta_end = percentages[2].start() if len(percentages) >= 3 else len(remainder)
    eta_match = _ETA_RE.search(remainder[percentages[1].end():eta_end])
    return {
        "name": " ".join(head.group("name").split()).strip(),
        "position": head.group("position"),
        "price": float(head.group("price")),
        "progress": float(percentages[0].group(0)[:-1]),
        "predicted": float(percentages[1].group(0)[:-1]),
        "eta": " ".join(eta_match.group(0).split()) if eta_match else None,
        "per_hour": float(percentages[2].group(0)[:-1]) if len(percentages) >= 3 else None,
    }


def parse_price_observations(html: str, *, source_url: str, fetched_at: str, ttl_seconds: int) -> list[dict]:
    parsed = [row for text in _table_rows(html) if (row := _parse_table_row(text))]
    if not parsed:
        parsed = [
            {
                "name": " ".join(match.group("name").split()).strip(),
                "position": match.group("position"),
                "price": float(match.group("price")),
                "progress": float(match.group("progress")),
                "predicted": float(match.group("predicted")),
                "eta": match.group("eta"),
                "per_hour": float(match.group("per_hour")) if match.group("per_hour") else None,
            }
            for match in _PRICE_RE.finditer(visible_text(html))
        ]

    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in parsed:
        if not row["name"]:
            continue
        obs = _make_observation(
            **row,
            source_url=source_url,
            fetched_at=fetched_at,
            ttl_seconds=ttl_seconds,
        )
        if obs["observation_key"] not in seen:
            seen.add(obs["observation_key"])
            observations.append(obs)
    return observations


def _candidate_urls(spec: SourceSpec) -> list[str]:
    configured = spec.config.get("structured_urls")
    if isinstance(configured, list) and configured:
        values = configured
    elif spec.config.get("structured_url"):
        values = [spec.config.get("structured_url")]
    else:
        values = [spec.config.get("probe_url")]
    out: list[str] = []
    for raw in values:
        url = str(raw or "").strip()
        if url and url not in out:
            out.append(url)
    return out


def _detail(document: FetchedDocument | None, attempts: list[dict[str, Any]], ingested: bool) -> dict[str, Any]:
    return {
        "http_status": document.status_code if document else None,
        "content_type": document.content_type if document else None,
        "structured_ingestion": True,
        "parser_version": PARSER_VERSION,
        "selected_url": document.url if document else None,
        "attempted_urls": attempts,
        "data_values_ingested": ingested,
        "no_fabrication": True,
    }


def probe(spec: SourceSpec, timeout_seconds: float = 2.5) -> SourceResult:
    ttl = int(spec.config["observation_ttl_seconds"])
    max_bytes = int(spec.config["max_fetch_bytes"])
    urls = _candidate_urls(spec)
    if not urls:
        return SourceResult(spec.source_id, "UNAVAILABLE", False, None, 0, {cap: "UNAVAILABLE" for cap in spec.capabilities}, {"error": "no_structured_url", "structured_ingestion": True, "parser_version": PARSER_VERSION})

    attempts: list[dict[str, Any]] = []
    first_reachable: FetchedDocument | None = None
    total_latency = 0.0
    for url in urls:
        document = fetch_public_document(url, timeout_seconds, max_bytes=max_bytes)
        total_latency += float(document.latency_ms or 0.0)
        observations = parse_price_observations(
            document.text,
            source_url=document.url,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            ttl_seconds=ttl,
        ) if document.reachable else []
        attempts.append({
            "url": url,
            "resolved_url": document.url,
            "reachable": document.reachable,
            "http_status": document.status_code,
            "observation_count": len(observations),
            "error": document.error,
        })
        if document.reachable and first_reachable is None:
            first_reachable = document
        if observations:
            capabilities = {
                cap: "AVAILABLE" if cap == "price_prediction" else "SOURCE_REACHABLE_NO_STRUCTURED_OBSERVATION"
                for cap in spec.capabilities
            }
            return SourceResult(spec.source_id, "LIVE", True, round(total_latency, 3), len(observations), capabilities, _detail(document, attempts, True), tuple(observations))

    if first_reachable is not None:
        capabilities = {cap: "SOURCE_REACHABLE_NO_STRUCTURED_OBSERVATION" for cap in spec.capabilities}
        return SourceResult(spec.source_id, "LIVE", True, round(total_latency, 3), 0, capabilities, _detail(first_reachable, attempts, False))

    return SourceResult(
        spec.source_id,
        "UNAVAILABLE",
        False,
        round(total_latency, 3) if total_latency else None,
        0,
        {cap: "UNAVAILABLE" for cap in spec.capabilities},
        {
            "http_status": attempts[-1].get("http_status") if attempts else None,
            "error": attempts[-1].get("error") if attempts else "unreachable",
            "structured_ingestion": True,
            "parser_version": PARSER_VERSION,
            "attempted_urls": attempts,
        },
    )
