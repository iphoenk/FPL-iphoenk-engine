from __future__ import annotations

import csv
import io

import requests

from src.sources.registry import source_ingestion_config
from src.utils import DATA, atomic_json, iso_now

CACHE = DATA / "stats"
SOURCE_ID = "vaastav"


def _cfg() -> dict:
    return source_ingestion_config(SOURCE_ID)


def _season_candidates() -> list[str]:
    configured = str(_cfg().get("season") or "").strip()
    if not configured:
        raise RuntimeError("vaastav ingestion season missing from source registry")
    short = configured
    if configured.startswith("20") and "-20" in configured:
        short = configured[:5] + configured[-2:]
    out: list[str] = []
    for value in (short, configured):
        if value and value not in out:
            out.append(value)
    return out


def _base() -> str:
    value = str(_cfg().get("raw_base") or "").strip().rstrip("/")
    if not value:
        raise RuntimeError("vaastav raw_base missing from source registry")
    return value


def _timeout() -> int:
    value = int(_cfg().get("request_timeout_seconds") or 0)
    if value <= 0:
        raise RuntimeError("vaastav request timeout must be positive")
    return value


def _fetch_csv(url: str):
    r = requests.get(url, timeout=_timeout())
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def sync_gw(gw: int):
    """Sync current-season vaastav data using only registry-owned candidate paths."""
    last_error = None
    candidates = list(_cfg().get("current_season_candidates") or [])
    if not candidates:
        raise RuntimeError("vaastav current_season_candidates missing from source registry")

    for season in _season_candidates():
        base = f"{_base()}/{season}"
        for candidate in candidates:
            path = str((candidate or {}).get("path") or "").format(gw=gw)
            data_mode = str((candidate or {}).get("data_mode") or "")
            if not path or not data_mode:
                continue
            url = f"{base}/{path}"
            try:
                rows = _fetch_csv(url)
                if not rows:
                    raise RuntimeError("empty CSV")
                payload = {
                    "source": "vaastav/Fantasy-Premier-League",
                    "source_id": SOURCE_ID,
                    "gw": gw,
                    "season": season,
                    "fetched_at": iso_now(),
                    "source_url": url,
                    "row_count": len(rows),
                    "data_mode": data_mode,
                    "is_gw_specific": data_mode == "GW_SPECIFIC",
                    "status": "LIVE" if data_mode == "GW_SPECIFIC" else "DEGRADED_FALLBACK",
                    "leakage_warning": (
                        "Historical xP/expected-points style columns may be post-match. "
                        "Shift/exclude for predictive training. Season-level fallback data "
                        "must not be treated as GW-specific observations."
                    ),
                    "rows": rows,
                }
                CACHE.mkdir(parents=True, exist_ok=True)
                atomic_json(CACHE / f"vaastav_gw{gw}.json", payload)
                return payload
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"

    failure = {
        "source": "vaastav/Fantasy-Premier-League",
        "source_id": SOURCE_ID,
        "gw": gw,
        "fetched_at": iso_now(),
        "status": "FAILED",
        "error": last_error,
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    atomic_json(CACHE / f"vaastav_gw{gw}_error.json", failure)
    return failure
