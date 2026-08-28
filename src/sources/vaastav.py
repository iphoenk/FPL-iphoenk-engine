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


def previous_season():
    """Return vaastav's short label for the season before the configured one."""
    configured = str(_cfg().get("season", "2026-2027"))
    try:
        start = int(configured[:4]) - 1
    except (TypeError, ValueError):
        start = 2025
    return f"{start}-{str(start + 1)[-2:]}"


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


def sync_previous_season():
    """Fetch a dedicated prior-season snapshot, never a current-season fallback."""
    season = previous_season()
    last_error = None
    for filename in ("players_raw.csv", "cleaned_players.csv"):
        url = f"{_base()}/{season}/{filename}"
        try:
            rows = _fetch_csv(url)
            if not rows:
                raise RuntimeError("empty CSV")
            columns = set(rows[0])
            required = {"first_name", "second_name", "minutes"}
            if not required.issubset(columns):
                raise RuntimeError(f"schema missing required columns: {sorted(required - columns)}")
            payload = {
                "source": "vaastav/Fantasy-Premier-League",
                "season": season,
                "fetched_at": iso_now(),
                "available_at": iso_now(),
                "source_url": url,
                "row_count": len(rows),
                "data_mode": "PREVIOUS_SEASON_SNAPSHOT",
                "status": "LIVE",
                "schema_columns": sorted(columns),
                "rows": rows,
            }
            CACHE.mkdir(parents=True, exist_ok=True)
            atomic_json(CACHE / "vaastav_previous_season.json", payload)
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
    CACHE.mkdir(parents=True, exist_ok=True)
    atomic_json(CACHE / "vaastav_previous_season_error.json", failure)
    return failure
