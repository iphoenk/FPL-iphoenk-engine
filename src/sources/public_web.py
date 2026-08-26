from __future__ import annotations

import time
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.sources.base import SourceResult, SourceSpec


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data.strip())

    @property
    def title(self) -> str | None:
        text = " ".join(x for x in self.title_parts if x).strip()
        return text[:160] if text else None


def probe_public_web(spec: SourceSpec, timeout_seconds: float = 2.5) -> SourceResult:
    if not spec.enabled:
        return SourceResult(spec.source_id, "DISABLED", False, None, 0, {c: "DISABLED" for c in spec.capabilities}, {"reason": "disabled by registry"})
    url = str(spec.config.get("probe_url") or "").strip()
    if not url.startswith("https://"):
        return SourceResult(spec.source_id, "MISCONFIGURED", False, None, 0, {c: "UNAVAILABLE" for c in spec.capabilities}, {"reason": "https probe_url required"})
    req = Request(url, headers={"User-Agent": "FPL-iphoenk-engine-source-health/3.16 (+read-only public probe)", "Accept": "text/html,application/xhtml+xml"}, method="GET")
    started = time.perf_counter()
    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", 200))
            raw = response.read(65536)
            content_type = str(response.headers.get("Content-Type") or "")
        elapsed = round((time.perf_counter() - started) * 1000.0, 3)
        parser = _TitleParser()
        if "html" in content_type.lower():
            parser.feed(raw.decode("utf-8", errors="ignore"))
        reachable = 200 <= status_code < 400
        capability_state = "SOURCE_REACHABLE_NOT_INGESTED" if reachable else "UNAVAILABLE"
        return SourceResult(
            spec.source_id,
            "LIVE" if reachable else "UNAVAILABLE",
            reachable,
            elapsed,
            0,
            {c: capability_state for c in spec.capabilities},
            {
                "http_status": status_code,
                "content_type": content_type[:120],
                "page_title": parser.title,
                "probe_only": True,
                "data_values_ingested": False,
            },
        )
    except HTTPError as exc:
        elapsed = round((time.perf_counter() - started) * 1000.0, 3)
        return SourceResult(spec.source_id, "UNAVAILABLE", False, elapsed, 0, {c: "UNAVAILABLE" for c in spec.capabilities}, {"http_status": int(exc.code), "error": "HTTPError", "probe_only": True})
    except (URLError, TimeoutError, OSError) as exc:
        elapsed = round((time.perf_counter() - started) * 1000.0, 3)
        return SourceResult(spec.source_id, "UNAVAILABLE", False, elapsed, 0, {c: "UNAVAILABLE" for c in spec.capabilities}, {"error": type(exc).__name__, "probe_only": True})
