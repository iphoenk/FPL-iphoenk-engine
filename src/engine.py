from __future__ import annotations

import argparse
import json

from src.engines.base_state import (
    bootstrap_maps,
    detect_phase,
    expanded_live,
    native_entry_summary,
    resolve_locked_player,
)
from src.sources import core_insights, vaastav
from src.version import ENGINE_VERSION, SCHEMA_VERSION


def maps(bootstrap):
    """Compatibility helper. Active production services use bootstrap_maps directly."""
    teams, positions, by_id = bootstrap_maps(bootstrap)
    by_name = {}
    for player in bootstrap.get("elements") or []:
        names = [
            player.get("web_name", ""),
            player.get("second_name", ""),
            f"{player.get('first_name', '')} {player.get('second_name', '')}".strip(),
        ]
        for name in names:
            if name:
                by_name[name.casefold()] = player
    return teams, positions, by_id, by_name


def run(mode: str = "daily", sync_stats: bool = False, deep_stats: bool = False):
    """Compatibility facade around the active V3 service orchestrator.

    Production service ownership lives in config/v3_service_registry.json. This
    facade intentionally contains no FPL network, squad, market, live or report
    business logic.
    """
    from src.runtime_v3.orchestrator import run as run_runtime

    return run_runtime(mode=mode, stats=sync_stats, deep_stats=deep_stats)


def cli() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ["daily", "deadline", "live"]:
        command = sub.add_parser(name)
        command.add_argument("--stats", action="store_true")
        command.add_argument("--deep-stats", action="store_true")
    stats_sync = sub.add_parser("stats-sync")
    stats_sync.add_argument("--gw", type=int, required=True)
    stats_sync.add_argument("--deep", action="store_true")
    advanced = sub.add_parser("advanced-stats")
    advanced.add_argument("--gw", type=int, required=True)
    advanced.add_argument("--query", required=True)
    args = parser.parse_args()

    if args.cmd in {"daily", "deadline", "live"}:
        print(json.dumps(run(args.cmd, args.stats, args.deep_stats), ensure_ascii=False, indent=2))
    elif args.cmd == "stats-sync":
        out = {"core_insights": core_insights.sync_gw(args.gw), "vaastav": vaastav.sync_gw(args.gw)}
        if args.deep:
            out["deep"] = core_insights.sync_optional_deep_files(args.gw)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(core_insights.query_player(args.gw, args.query), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
