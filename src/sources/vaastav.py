from __future__ import annotations

from src.sources.csv_fetch import fetch_csv
from src.utils import DATA, CONFIG, iso_now, atomic_json, read_json

CACHE = DATA / "stats"


def _cfg():
    return read_json(CONFIG / "sources.json", {})


def _season_candidates():
    configured = _cfg().get("season", "2026-2027")
    short = configured
    if configured.startswith("20") and "-20" in configured:
        # 2026-2027 -> 2026-27, which is vaastav's current convention.
        short = configured[:5] + configured[-2:]
    candidates = [short, configured]
    out = []
    for s in candidates:
        if s and s not in out:
            out.append(s)
    return out


def season_before(offset: int = 1):
    """Return Vaastav's short label for a completed season before the configured season."""
    configured = str(_cfg().get("season", "2026-2027"))
    try:
        start = int(configured[:4]) - int(offset)
    except (TypeError, ValueError):
        start = 2026 - int(offset)
    return f"{start}-{str(start + 1)[-2:]}"


def previous_season():
    return season_before(1)


def historical_seasons(depth: int | None = None):
    """Older completed seasons used only as a bounded fallback behind last season."""
    configured_depth = int((_cfg().get("vaastav") or {}).get("historical_depth", 2))
    count = max(0, int(configured_depth if depth is None else depth))
    return [season_before(offset) for offset in range(2, 2 + count)]


def _base():
    return _cfg().get("vaastav", {}).get(
        "raw_base",
        "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data",
    ).rstrip("/")


def _fetch_csv(url: str, timeout: int = 25):
    return fetch_csv(url, timeout=timeout)


def sync_gw(gw: int):
    """
    Prefer a true GW-specific vaastav file when available.
    For very early current seasons, vaastav may expose only season-level files.
    In that case use cleaned_players.csv as a non-GW fallback and mark it clearly,
    rather than treating the source as failed.
    """
    last_error = None

    for season in _season_candidates():
        base = f"{_base()}/{season}"
        candidates = [
            (f"{base}/gws/gw{gw}.csv", "GW_SPECIFIC"),
            (f"{base}/gws/merged_gw.csv", "MERGED_GW_FALLBACK"),
            (f"{base}/cleaned_players.csv", "SEASON_SNAPSHOT_FALLBACK"),
            (f"{base}/players_raw.csv", "SEASON_RAW_FALLBACK"),
        ]

        for url, data_mode in candidates:
            try:
                rows = _fetch_csv(url)
                if not rows:
                    raise RuntimeError("empty CSV")

                payload = {
                    "source": "vaastav/Fantasy-Premier-League",
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
        "gw": gw,
        "fetched_at": iso_now(),
        "status": "FAILED",
        "error": last_error,
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    atomic_json(CACHE / f"vaastav_gw{gw}_error.json", failure)
    return failure


def _sync_completed_season(season: str, outfile: str, data_mode: str):
    """Fetch or reuse an immutable completed-season snapshot from the canonical Vaastav adapter."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / outfile
    cached = read_json(path, {})
    if cached.get("status") == "LIVE" and cached.get("season") == season and cached.get("rows"):
        return {**cached, "cache_reused": True}

    last_error = None
    for filename in ("players_raw.csv", "cleaned_players.csv"):
        url = f"{_base()}/{season}/{filename}"
        try:
            rows = _fetch_csv(url)
            if not rows:
                raise RuntimeError("empty CSV")
            columns = set(rows[0])
            required = {"first_name", "second_name", "minutes", "code", "starts"}
            if not required.issubset(columns):
                raise RuntimeError(f"schema missing required columns: {sorted(required - columns)}")
            payload = {
                "source": "vaastav/Fantasy-Premier-League",
                "season": season,
                "fetched_at": iso_now(),
                "available_at": iso_now(),
                "source_url": url,
                "row_count": len(rows),
                "data_mode": data_mode,
                "status": "LIVE",
                "schema_columns": sorted(columns),
                "immutable_completed_season": True,
                "rows": rows,
            }
            atomic_json(path, payload)
            return payload
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    failure = {
        "source": "vaastav/Fantasy-Premier-League",
        "season": season,
        "fetched_at": iso_now(),
        "status": "FAILED",
        "error": last_error,
    }
    atomic_json(CACHE / f"{path.stem}_error.json", failure)
    return failure


def sync_previous_season():
    return _sync_completed_season(
        previous_season(),
        "vaastav_previous_season.json",
        "PREVIOUS_SEASON_SNAPSHOT",
    )


def sync_historical_season(season: str):
    if season not in historical_seasons():
        raise ValueError(f"historical season outside configured depth: {season}")
    safe = season.replace("-", "_")
    return _sync_completed_season(
        season,
        f"vaastav_historical_{safe}.json",
        "HISTORICAL_SEASON_SNAPSHOT",
    )
