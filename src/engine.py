from __future__ import annotations

import argparse
import json

from src.services.orchestrator import orchestrate
from src.sources import core_insights, vaastav


def run(mode: str = "daily", sync_stats: bool = False, deep_stats: bool = False, as_of: str | None = None) -> dict:
    """Compatibility adapter into the canonical microservice orchestrator.

    No acquisition, prediction, pricing, legality or decision logic lives here.
    """
    return orchestrate(mode, stats=sync_stats, deep_stats=deep_stats, as_of=as_of)


def cli() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("daily", "deadline", "live"):
        command = sub.add_parser(name)
        command.add_argument("--stats", action="store_true")
        command.add_argument("--deep-stats", action="store_true")
        command.add_argument("--as-of", help="Timezone-aware deterministic checkpoint time")
    sync = sub.add_parser("stats-sync")
    sync.add_argument("--gw", type=int, required=True)
    sync.add_argument("--deep", action="store_true")
    advanced = sub.add_parser("advanced-stats")
    advanced.add_argument("--gw", type=int, required=True)
    advanced.add_argument("--query", required=True)
    args = parser.parse_args()

    if args.cmd in {"daily", "deadline", "live"}:
        output = run(args.cmd, args.stats, args.deep_stats, args.as_of)
    elif args.cmd == "stats-sync":
        output = {
            "core_insights": core_insights.sync_gw(args.gw),
            "vaastav": vaastav.sync_gw(args.gw),
            "last_season": vaastav.sync_previous_season(),
        }
        if args.deep:
            output["deep"] = core_insights.sync_optional_deep_files(args.gw)
    else:
        output = core_insights.query_player(args.gw, args.query)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
