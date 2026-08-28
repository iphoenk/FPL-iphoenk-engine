from __future__ import annotations

from src.sources.csv_fetch import fetch_csv
from src.utils import DATA, CONFIG, iso_now, atomic_json, read_json

CACHE = DATA / "stats"
REQUIRED = {"id"}

def _cfg():
    return read_json(CONFIG / "sources.json", {})

def season():
    cfg = _cfg()
    return cfg.get("fpl_core_insights", {}).get("season") or cfg.get("season") or "2026-2027"

def base_url():
    return _cfg().get("fpl_core_insights", {}).get(
        "raw_base",
        "https://raw.githubusercontent.com/olbauday/FPL-Core-Insights/main/data",
    ).rstrip("/")

def _fetch_csv(url: str, timeout: int = 30):
    return fetch_csv(url, timeout=timeout)

def _gw_base(gw: int) -> str:
    return f"{base_url()}/{season()}/By%20Gameweek/GW{gw}"

def _candidate_player_urls(gw: int):
    base = _gw_base(gw)
    return [
        f"{base}/players.csv",
        f"{base}/playerstats.csv",
        f"{base}/playergameweekstats.csv",
    ]

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
        haystack = " ".join(str(row.get(k, "")) for k in ["name","web_name","first_name","second_name","id"]).casefold()
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
    candidates = {
        "shots": [f"{base}/shots.csv"],
        "playermatchstats": [f"{base}/playermatchstats.csv"],
    }
    result = {}
    for name, urls in candidates.items():
        last_error = None
        for url in urls:
            try:
                rows = _fetch_csv(url)
                payload = {
                    "source": "FPL-Core-Insights",
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
            result[name] = {"ok": False, "error": last_error}
    return result
