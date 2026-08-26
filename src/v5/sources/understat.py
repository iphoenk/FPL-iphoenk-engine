from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.sources.season import season_authority

CONFIG = "config/intelligence/source_fusion.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_cache(path: Path, ttl_seconds: int) -> dict[str, Any] | None:
    if not path.exists():
        return None
    age = _now().timestamp() - path.stat().st_mtime
    if age > ttl_seconds:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def collect() -> dict[str, Any]:
    cfg = load_json_config(CONFIG)["understat"]
    season = season_authority()
    start_year = int(season["start_year"])
    if not cfg.get("enabled", False):
        return {"source": "understat", "status": "DISABLED", "players": [], "season": season}
    template = str(cfg["cache_path_template"])
    cache = Path(template.format(season=start_year))
    cached = _load_cache(cache, int(cfg["cache_ttl_seconds"]))
    if cached:
        return {**cached, "fetch_mode": "CACHE", "season": season, "player_count": len(cached.get("players") or [])}
    try:
        from understatapi import UnderstatClient
    except Exception as exc:
        return {
            "source": "understat",
            "status": "UNAVAILABLE",
            "reason": f"dependency:{type(exc).__name__}",
            "players": [],
            "season": season,
        }
    try:
        with UnderstatClient() as client:
            rows = client.league(league=str(cfg["league"])).get_player_data(season=str(start_year))
        normalized = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            normalized.append({
                "understat_id": row.get("id"),
                "player_name": row.get("player_name"),
                "team_title": row.get("team_title"),
                "games": row.get("games"),
                "time": row.get("time"),
                "shots": row.get("shots"),
                "xg": row.get("xG"),
                "xa": row.get("xA"),
                "key_passes": row.get("key_passes"),
                "xg_chain": row.get("xGChain"),
                "xg_buildup": row.get("xGBuildup"),
            })
        payload = {
            "source": "understat",
            "status": "ACTIVE" if normalized else "DEGRADED",
            "generated_at": _now().isoformat(),
            "fetch_mode": "NETWORK",
            "season": season,
            "capabilities": cfg.get("capabilities") or [],
            "player_count": len(normalized),
            "players": normalized,
            "governance": {"challenger_only": True, "never_proxy_box_touches_from_shot_location": True},
        }
        _write_cache(cache, payload)
        return payload
    except Exception as exc:
        return {
            "source": "understat",
            "status": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}:{exc}",
            "players": [],
            "season": season,
        }
