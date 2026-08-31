from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

from src.sources.base import SourceResult, SourceSpec
from src.sources.observations import ChallengerObservation
from src.sources.structured_web import FetchedDocument, fetch_public_document, visible_text

PARSER_VERSION = "livefpl-price-v2"

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
_ROW_HEAD_RE = re.compile(
    r"(?P<name>[A-Za-zÀ-ÖØ-öø-ÿ0-9.'’ -]{2,45}?)\s+"
    r"(?P<position>GKP|GK|DEF|MID|FWD|FW)\s+"
    r"£(?P<price>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"[+-]?\d+(?:\.\d+)?%")
_ETA_RE = re.compile(r"(?:Tonight|Tomorrow|>\s*\d+\s*days?|\d+\s*days?)", re.IGNORECASE)


class _TableRowsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in {"script", "style", "noscript"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if name == "tr":
            self._row = []
            self._cell = None
        elif name in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in {"script", "style", "noscript"}:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if name in {"td", "th"} and self._row is not None and self._cell is not None:
            value = " ".join(" ".join(self._cell).split())
            self._row.append(value)
            self._cell = None
        elif name == "tr" and self._row is not None:
            if any(value for value in self._row):
                self.rows.append(self._row)
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._ignored_depth or self._cell is None:
            return
        value = " ".join(data.split())
        if value:
            self._cell.append(value)


def _direction(value: float) -> str:
    if value > 0:
        return "RISE"
    if value < 0:
        return "FALL"
    return "STABLE"


def _position(value: str) -> str:
    return str(value).upper().replace("FW", "FWD").replace("GKP", "GK")


def _eta_label(text: str) -> str | None:
    match = _ETA_RE.search(text)
    return " ".join(match.group(0).split()) if match else None


def _observation(
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


def _table_price_observations(
    html: str,
    *,
    source_url: str,
    fetched_at: str,
    ttl_seconds: int,
) -> list[dict[str, Any]]:
    parser = _TableRowsParser()
    parser.feed(html or "")
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cells in parser.rows:
        row_text = " ".join(value for value in cells if value)
        head = _ROW_HEAD_RE.search(row_text)
        if head is None:
            continue
        remainder = row_text[head.end():]
        percentages = list(_PERCENT_RE.finditer(remainder))
        if len(percentages) < 2:
            continue
        name = " ".join(head.group("name").split()).strip()
        if not name:
            continue
        progress = float(percentages[0].group(0)[:-1])
        predicted = float(percentages[1].group(0)[:-1])
        per_hour = float(percentages[2].group(0)[:-1]) if len(percentages) >= 3 else None
        eta_window_end = percentages[2].start() if len(percentages) >= 3 else len(remainder)
        eta = _eta_label(remainder[percentages[1].end():eta_window_end])
        obs = _observation(
            name=name,
            position=head.group("position"),
            price=float(head.group("price")),
            progress=progress,
            predicted=predicted,
            eta=eta,
            per_hour=per_hour,
            source_url=source_url,
            fetched_at=fetched_at,
            ttl_seconds=ttl_seconds,
        )
        if obs["observation_key"] in seen:
            continue
        seen.add(obs["observation_key"])
        observations.append(obs)
    return observations


def _legacy_price_observations(
    html: str,
    *,
    source_url: str,
    fetched_at: str,
    ttl_seconds: int,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _PRICE_RE.finditer(visible_text(html)):
        name = " ".join(match.group("name").split()).strip()
        if not name:
            continue
        predicted = float(match.group("predicted"))
        obs = _observation(
            name=name,
            position=match.group("position"),
            price=float(match.group("price")),
            progress=float(match.group("progress")),
            predicted=predicted,
            eta=match.group("eta"),
            per_hour=float(match.group("per_hour")) if match.group("per_hour") else None,
            source_url=source_url,
            fetched_at=fetched_at,
            ttl_seconds=ttl_seconds,
        )
        if obs["observation_key"] in seen:
            continue
        seen.add(obs["observation_key"])
        observations.append(obs)
    return observations


def parse_price_observations(html: str, *, source_url: str, fetched_at: str, ttl_seconds: int) -> list[dict]:
    table_rows = _table_price_observations(
        html,
        source_url=source_url,
        fetched_at=fetched_at,
        ttl_seconds=ttl_seconds,
    )
    if table_rows:
        return table_rows
    return _legacy_price_observations(
        html,
        source_url=source_url,
        fetched_at=fetched_at,
        ttl_seconds=ttl_seconds,
    )


def _candidate_urls(spec: SourceSpec) -> list[str]:
    configured = spec.config.get("structured_urls")
    values: list[Any] = list(configured) if isinstance(configured, list) else []
    values.extend([spec.config.get("structured_url"), spec.config.get("probe_url")])
    out: list[str] = []
    for raw in values:
        url = str(raw or "").strip()
        if url and url not in out:
            out.append(url)
    return out


def _result_detail(document: FetchedDocument | None, attempts: list[dict[str, Any]], observations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "http_status": document.status_code if document else None,
        "content_type": document.content_type if document else None,
        "structured_ingestion": True,
        "parser_version": PARSER_VERSION,
        "selected_url": document.url if document else None,
        "attempted_urls": attempts,
        "data_values_ingested": bool(observations),
        "no_fabrication": True,
    }


def probe(spec: SourceSpec, timeout_seconds: float = 2.5) -> SourceResult:
    ttl = int(spec.config["observation_ttl_seconds"])
    max_bytes = int(spec.config["max_fetch_bytes"])
    urls = _candidate_urls(spec)
    if not urls:
        return SourceResult(
            spec.source_id,
            "UNAVAILABLE",
            False,
            None,
            0,
            {cap: "UNAVAILABLE" for cap in spec.capabilities},
            {"error": "no_structured_url", "structured_ingestion": True, "parser_version": PARSER_VERSION},
        )

    attempts: list[dict[str, Any]] = []
    reachable_document: FetchedDocument | None = None
    total_latency = 0.0
    for url in urls:
        document = fetch_public_document(url, timeout_seconds, max_bytes=max_bytes)
        if document.latency_ms is not None:
            total_latency += float(document.latency_ms)
        fetched_at = datetime.now(timezone.utc).isoformat()
        observations = (
            parse_price_observations(document.text, source_url=document.url, fetched_at=fetched_at, ttl_seconds=ttl)
            if document.reachable
            else []
        )
        attempts.append(
            {
                "url": url,
                "resolved_url": document.url,
                "reachable": document.reachable,
                "http_status": document.status_code,
                "observation_count": len(observations),
                "error": document.error,
            }
        )
        if document.reachable and reachable_document is None:
            reachable_document = document
        if not observations:
            continue
        capability_state = {
            cap: ("AVAILABLE" if cap == "price_prediction" else "SOURCE_REACHABLE_NO_STRUCTURED_OBSERVATION")
            for cap in spec.capabilities
        }
        return SourceResult(
            spec.source_id,
            "LIVE",
            True,
            round(total_latency, 3),
            len(observations),
            capability_state,
            _result_detail(document, attempts, observations),
            tuple(observations),
        )

    if reachable_document is None:
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

    capability_state = {cap: "SOURCE_REACHABLE_NO_STRUCTURED_OBSERVATION" for cap in spec.capabilities}
    return SourceResult(
        spec.source_id,
        "LIVE",
        True,
        round(total_latency, 3),
        0,
        capability_state,
        _result_detail(reachable_document, attempts, []),
    )
