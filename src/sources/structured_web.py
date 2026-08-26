from __future__ import annotations

import json
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class FetchedDocument:
    url: str
    status_code: int | None
    content_type: str | None
    text: str
    reachable: bool
    latency_ms: float | None
    error: str | None = None


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


class _JSONScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self._parts: list[str] = []
        self.documents: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        meta = {str(k).lower(): str(v or "") for k, v in attrs}
        typ = meta.get("type", "").lower()
        ident = meta.get("id", "")
        if typ in {"application/json", "application/ld+json"} or ident == "__NEXT_DATA__":
            self._capture = True
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or not self._capture:
            return
        raw = "".join(self._parts).strip()
        self._capture = False
        self._parts = []
        if not raw:
            return
        try:
            self.documents.append(json.loads(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)


def visible_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html or "")
    return " ".join(parser.parts)


def embedded_json_documents(html: str) -> list[Any]:
    parser = _JSONScriptParser()
    parser.feed(html or "")
    return parser.documents


def walk_records(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_records(child)


def fetch_public_document(url: str, timeout_seconds: float, *, max_bytes: int, user_agent: str = "FPL-iphoenk-engine structured-public-readonly") -> FetchedDocument:
    if not str(url).startswith("https://"):
        return FetchedDocument(str(url), None, None, "", False, None, "https_required")
    request = Request(str(url), headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml,application/json"}, method="GET")
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=float(timeout_seconds)) as response:
            status_code = int(getattr(response, "status", 200))
            content_type = str(response.headers.get("Content-Type") or "")
            raw = response.read(max(1, int(max_bytes)))
            final_url = str(getattr(response, "geturl", lambda: url)())
        latency = round((time.perf_counter() - started) * 1000.0, 3)
        return FetchedDocument(final_url, status_code, content_type[:160], raw.decode("utf-8", errors="ignore"), 200 <= status_code < 400, latency, None)
    except HTTPError as exc:
        latency = round((time.perf_counter() - started) * 1000.0, 3)
        return FetchedDocument(str(url), int(exc.code), None, "", False, latency, "HTTPError")
    except (URLError, TimeoutError, OSError) as exc:
        latency = round((time.perf_counter() - started) * 1000.0, 3)
        return FetchedDocument(str(url), None, None, "", False, latency, type(exc).__name__)
