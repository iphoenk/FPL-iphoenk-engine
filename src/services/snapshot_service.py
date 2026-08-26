from __future__ import annotations

import argparse
import json

from src.engine import run


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("daily", "deadline", "live"))
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--deep-stats", action="store_true")
    parser.add_argument("--as-of")
    args = parser.parse_args()
    out = run(args.mode, args.stats, args.deep_stats, args.as_of)
    summary = {
        "service": "snapshot_prediction",
        "engine": out.get("engine_version"),
        "generated_at": out.get("generated_at"),
        "checkpoint": (out.get("checkpoint_context") or {}).get("policy_id"),
        "players": (out.get("prediction_summary") or {}).get("players"),
        "performance_ms": (out.get("performance") or {}).get("engine_before_snapshot_write_ms"),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return out


if __name__ == "__main__":
    cli()
