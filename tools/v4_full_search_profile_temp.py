from __future__ import annotations

import cProfile
import pstats
import signal
import sys
from io import StringIO

from src.engines.v4_decision_pipeline import effective_planning_squad
from src.engines.v4_full_universe_package_search import search_full_universe_packages
from src.engines.v4_tactical_interaction import build_tactical_interactions
from src.engines.v4_wc_optimizer import build_candidates
from src.utils import CONFIG, DATA, read_json


# Profiling harness only. Production code must not depend on this module.
def main() -> None:
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    team = read_json(DATA / "team.json", {})
    latest = read_json(DATA / "latest.json", {})
    configured_lock = read_json(CONFIG / "locked_squad.json", {})
    understat = read_json(DATA / "understat_tactical_v4.json", {})
    prices = read_json(DATA / "prices.json", {})
    locked = effective_planning_squad(team, configured_lock, latest)
    candidates = build_candidates(predictions, universe)
    interactions = build_tactical_interactions(predictions, universe, understat)

    profiler = cProfile.Profile()

    def dump_and_exit(signum, frame):
        profiler.disable()
        buf = StringIO()
        stats = pstats.Stats(profiler, stream=buf).strip_dirs().sort_stats("cumulative")
        stats.print_stats(60)
        print("PROFILE_TIMEOUT_25S", flush=True)
        print(buf.getvalue(), flush=True)
        raise SystemExit(124)

    signal.signal(signal.SIGALRM, dump_and_exit)
    signal.alarm(25)
    profiler.enable()
    out = search_full_universe_packages(
        candidates,
        locked,
        predictions=predictions,
        universe=universe,
        understat=understat,
        interactions=interactions,
        prices=prices,
        max_replacements=3,
    )
    profiler.disable()
    signal.alarm(0)
    buf = StringIO()
    pstats.Stats(profiler, stream=buf).strip_dirs().sort_stats("cumulative").print_stats(60)
    print("PROFILE_COMPLETED", flush=True)
    print(buf.getvalue(), flush=True)
    print({
        "status": (out.get("search") or {}).get("status"),
        "diagnostics": (out.get("search") or {}).get("diagnostics"),
    }, flush=True)


if __name__ == "__main__":
    main()
