from __future__ import annotations

import csv
import io

import requests

from src.sources.registry import source_ingestion_config
from src.utils import DATA, atomic_json, iso_now, read_json

CACHE = DATA / "stats"
REQUIRED = {"id"}
SOURCE_ID = "fpl_core_insights"


def _cfg() -> dict:
    return source_ingestion_config(SOURCE_ID)


def season() -> str:
    value = str(_cfg().get("season") or "").strip()
    if not value:
        raise RuntimeError("fpl_core_insights ingestion season missing from source registry")
    return value


def base_url() -> str:
    value = str(_cfg().get("raw_base") or "").strip().rstrip("/")
    if not value:
        raise RuntimeError("fpl_core_insights raw_base missing from source registry")
    return value


def _timeout() -> int:
    value = int(_cfg().get("request_timeout_seconds") or 0)
    if value <= 0:
        raise RuntimeError("fpl_core_insights request timeout must be positive")
    return value


def _fetch_csv(url: str):
    r = requests.get(url, timeout=_timeout())
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def _gw_base(gw: int) -> str:
    return f"{base_url()}/{season()}/By%20Gameweek/GW{gw}"


def _candidate_player_urls(gw: int) -> list[str]:
    base = _gw_base(gw)
    filenames = [str(x) for x in _cfg().get("gameweek_player_files") or []]
    if not filenames:
        raise RuntimeError("fpl_core_insights gameweek_player_files missing from source registry")
    return [f"{base}/{name}" for name in filenames]


def sync_gw(gw: int):
    last_error = None
    for url in _candidate_player_urls(gw):
        try:
            rows = _fetch_csv(url)
            if not rows:
                raise RuntimeError("empty CSV")
            columns = set(rows[0].keys())
            if not REQUIRED.issubset(columns):
                raise RuntimeError(f"schema missing required columns: {sorted(REQUIRED - columns)}")
            payload = {
                "source": "FPL-Core-Insights",
                "source_id": SOURCE_ID,
                "source_tier": "community_enrichment",
                "season": season(),
                "gw": gw,
                "fetched_at": iso_now(),
                "available_at": iso_now(),
                "data_class": "post_match_or_post_gw",
                "leakage_guard": "NOT_ELIGIBLE_FOR_SAME_GW_PREDEADLINE_TRAINING",
                "source_url": url,
                "row_count": len(rows),
                "schema_columns": sorted(columns),
                "schema_valid": True,
                "rows": rows,
            }
            CACHE.mkdir(parents=True, exist_ok=True)
            atomic_json(CACHE / f"core_insights_gw{gw}.json", payload)
            return payload
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    failure = {
        "source": "FPL-Core-Insights",
        "source_id": SOURCE_ID,
        "season": season(),
        "gw": gw,
        "fetched_at": iso_now(),
        "schema_valid": False,
        "error": last_error,
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    atomic_json(CACHE / f"core_insights_gw{gw}_error.json", failure)
    return failure


def load_gw(gw: int):
    return read_json(CACHE / f"core_insights_gw{gw}.json", {})


def query_player(gw: int, query: str):
    data = load_gw(gw)
    q = query.casefold()
    hits = []
    for row in data.get("rows", []):
        haystack = " ".join(str(row.get(k, "")) for k in ["name", "web_name", "first_name", "second_name", "id"]).casefold()
        if q in haystack:
            hits.append(row)
    return {
        "source": data.get("source"),
        "gw": gw,
        "fetched_at": data.get("fetched_at"),
        "schema_valid": data.get("schema_valid"),
        "matches": hits,
    }


def sync_optional_deep_files(gw: int):
    base = _gw_base(gw)
    configured = _cfg().get("deep_files") or {}
    if not isinstance(configured, dict):
        raise RuntimeError("fpl_core_insights deep_files must be an object")
    result = {}
    for name, filenames in configured.items():
        urls = [f"{base}/{filename}" for filename in filenames or []]
        last_error = None
        for url in urls:
            try:
                rows = _fetch_csv(url)
                payload = {
                    "source": "FPL-Core-Insights",
                    "source_id": SOURCE_ID,
                    "dataset": name,
                    "season": season(),
                    "gw": gw,
                    "fetched_at": iso_now(),
                    "source_url": url,
                    "row_count": len(rows),
                    "schema_columns": sorted(rows[0].keys()) if rows else [],
                    "rows": rows,
                }
                CACHE.mkdir(parents=True, exist_ok=True)
                atomic_json(CACHE / f"{name}_gw{gw}.json", payload)
                result[name] = {"ok": True, "rows": len(rows), "url": url}
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
        else:
            result[name] = {"ok": False, "error": last_error or "no configured URL"}
    return result
