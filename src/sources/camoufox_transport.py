from __future__ import annotations

import hashlib
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit


_BLOCK_MARKERS = (
    "verify that you're not a robot",
    "attention required! | cloudflare",
    "just a moment...",
    "captcha",
)
_AUTH_PATH_MARKERS = ("/login", "/signin", "/sign-in", "/members", "/account")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_public_https(url: str) -> bool:
    parts = urlsplit(str(url or "").strip())
    return parts.scheme == "https" and bool(parts.netloc) and not parts.username and not parts.password


def _default_browser_factory() -> AbstractContextManager[Any]:
    try:
        from camoufox.sync_api import Camoufox
    except ImportError as exc:  # optional dependency by design
        raise RuntimeError("camoufox_not_installed") from exc
    return Camoufox(
        headless=True,
        os="linux",
        block_images=True,
        block_webrtc=True,
        enable_cache=False,
    )


@dataclass(frozen=True)
class CaptureTarget:
    source_id: str
    source_class: str
    url: str
    purpose: tuple[str, ...] = ()


def _bounded_text(value: str, max_chars: int) -> tuple[str, bool]:
    text = str(value or "").replace("\x00", "").strip()
    limit = max(1, int(max_chars))
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def capture_targets(
    targets: Iterable[CaptureTarget],
    *,
    navigation_timeout_seconds: float = 18,
    settle_milliseconds: int = 750,
    max_visible_text_chars: int = 120000,
    browser_factory: Callable[[], AbstractContextManager[Any]] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    factory = browser_factory or _default_browser_factory
    started_all = time.perf_counter()

    try:
        manager = factory()
        with manager as browser:
            for target in targets:
                requested_url = str(target.url or "").strip()
                if not _safe_public_https(requested_url):
                    rows.append(
                        {
                            "source_id": target.source_id,
                            "source_class": target.source_class,
                            "purpose": list(target.purpose),
                            "requested_url": requested_url,
                            "status": "INVALID_URL",
                            "transport": "CAMOUFOX",
                            "observed_at": utc_now(),
                            "error": "public_https_required",
                        }
                    )
                    continue

                page = None
                started = time.perf_counter()
                try:
                    page = browser.new_page()
                    page.set_default_navigation_timeout(
                        max(1000, int(float(navigation_timeout_seconds) * 1000))
                    )
                    response = page.goto(
                        requested_url,
                        wait_until="domcontentloaded",
                        timeout=max(1000, int(float(navigation_timeout_seconds) * 1000)),
                    )
                    if settle_milliseconds > 0:
                        page.wait_for_timeout(max(0, int(settle_milliseconds)))

                    final_url = str(page.url or requested_url)
                    title = str(page.title() or "").strip()[:300]
                    body = page.locator("body").inner_text(timeout=5000)
                    visible_text, truncated = _bounded_text(
                        body,
                        max_visible_text_chars,
                    )
                    lower_text = visible_text.casefold()
                    requested_path = urlsplit(requested_url).path.casefold()
                    final_path = urlsplit(final_url).path.casefold()
                    auth_redirect = any(
                        marker in final_path and marker not in requested_path
                        for marker in _AUTH_PATH_MARKERS
                    )
                    blocked = any(marker in lower_text for marker in _BLOCK_MARKERS)
                    http_status = int(response.status) if response is not None else None
                    if auth_redirect:
                        status = "AUTH_REQUIRED"
                    elif blocked:
                        status = "ACCESS_RESTRICTED"
                    elif http_status is not None and not 200 <= http_status < 400:
                        status = "HTTP_ERROR"
                    elif not visible_text:
                        status = "EMPTY"
                    else:
                        status = "AVAILABLE"

                    rows.append(
                        {
                            "source_id": target.source_id,
                            "source_class": target.source_class,
                            "purpose": list(target.purpose),
                            "requested_url": requested_url,
                            "final_url": final_url,
                            "http_status": http_status,
                            "title": title,
                            "status": status,
                            "transport": "CAMOUFOX",
                            "observed_at": utc_now(),
                            "latency_ms": round(
                                (time.perf_counter() - started) * 1000.0,
                                3,
                            ),
                            "visible_text": visible_text if status == "AVAILABLE" else "",
                            "visible_text_chars": len(visible_text),
                            "visible_text_truncated": truncated,
                            "content_sha256": (
                                hashlib.sha256(visible_text.encode("utf-8")).hexdigest()
                                if visible_text
                                else None
                            ),
                            "semantic_inference_performed": False,
                            "fact_promotion_performed": False,
                        }
                    )
                except Exception as exc:
                    rows.append(
                        {
                            "source_id": target.source_id,
                            "source_class": target.source_class,
                            "purpose": list(target.purpose),
                            "requested_url": requested_url,
                            "status": "UNAVAILABLE",
                            "transport": "CAMOUFOX",
                            "observed_at": utc_now(),
                            "latency_ms": round(
                                (time.perf_counter() - started) * 1000.0,
                                3,
                            ),
                            "error": type(exc).__name__,
                            "semantic_inference_performed": False,
                            "fact_promotion_performed": False,
                        }
                    )
                finally:
                    if page is not None:
                        try:
                            page.close()
                        except Exception:
                            pass
    except Exception as exc:
        return {
            "schema_version": 1,
            "contract": "report_time_web_capture_v1",
            "generated_at": utc_now(),
            "status": "UNAVAILABLE",
            "transport": "CAMOUFOX",
            "capture_count": 0,
            "available_count": 0,
            "captures": [],
            "elapsed_ms": round((time.perf_counter() - started_all) * 1000.0, 3),
            "error": type(exc).__name__,
            "policy": {
                "public_read_only": True,
                "semantic_inference_performed": False,
                "fact_promotion_performed": False,
                "source_failure_is_non_blocking": True,
            },
        }

    available = sum(1 for row in rows if row.get("status") == "AVAILABLE")
    return {
        "schema_version": 1,
        "contract": "report_time_web_capture_v1",
        "generated_at": utc_now(),
        "status": "READY" if available else "UNAVAILABLE",
        "transport": "CAMOUFOX",
        "capture_count": len(rows),
        "available_count": available,
        "captures": rows,
        "elapsed_ms": round((time.perf_counter() - started_all) * 1000.0, 3),
        "policy": {
            "public_read_only": True,
            "semantic_inference_performed": False,
            "fact_promotion_performed": False,
            "source_failure_is_non_blocking": True,
        },
    }
