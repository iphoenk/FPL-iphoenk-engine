from __future__ import annotations

import argparse
import json

from src.sources import core_insights, vaastav
from src.utils import DATA, atomic_json, iso_now, read_json

OFFICIAL = DATA / "official_snapshot.json"
OUT = DATA / "advanced_stats_sync.json"
STATS = DATA / "stats"


def _publish_current_alias(name: str, gw: int) -> bool:
    source = STATS / f"{name}_gw{gw}.json"
    if not source.exists():
        return False
    payload = read_json(source, {})
    if not payload:
        return False
    alias = dict(payload)
    alias["current_alias_for_gw"] = gw
    alias["archive_source"] = f"data/stats/{name}_gw{gw}.json"
    atomic_json(STATS / f"{name}_current.json", alias)
    return True


def run(*, sync_stats: bool = True, deep_stats: bool = False) -> dict:
    official = read_json(OFFICIAL, {})
    phase = official.get("phase") or {}
    stats_gw = phase.get("current_gw") or phase.get("last_finished_gw")
    result = {
        "generated_at": iso_now(),
        "enabled": bool(sync_stats),
        "deep_stats": bool(deep_stats),
        "stats_gw": stats_gw,
        "core_insights": None,
        "vaastav": None,
        "deep": None,
        "current_aliases": {},
    }
    if sync_stats and stats_gw:
        gw = int(stats_gw)
        core = core_insights.sync_gw(gw)
        vaa = vaastav.sync_gw(gw)
        result["core_insights"] = {
            "ok": bool(core.get("schema_valid")),
            "rows": core.get("row_count"),
            "error": core.get("error"),
        }
        result["vaastav"] = {
            "ok": bool(vaa.get("rows")),
            "rows": vaa.get("row_count"),
            "error": vaa.get("error"),
            "data_mode": vaa.get("data_mode"),
        }
        if deep_stats:
            result["deep"] = core_insights.sync_optional_deep_files(gw)
        for name in ("shots", "playermatchstats"):
            result["current_aliases"][name] = _publish_current_alias(name, gw)
    atomic_json(OUT, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--deep-stats", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(sync_stats=args.stats, deep_stats=args.deep_stats), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
