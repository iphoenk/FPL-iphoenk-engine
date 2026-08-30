from __future__ import annotations

import cProfile
import io
import json
import pstats
from pathlib import Path
from time import perf_counter

from src.engines.v4_decision_pipeline import effective_planning_squad
from src.engines.v4_wc_optimizer import build_candidates
from src.engines.v4_wc_package_audit_fast import audit_packages_from_candidates_fast
from src.utils import CONFIG, DATA, read_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "profile-output"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    team = read_json(DATA / "team.json", {})
    latest = read_json(DATA / "latest.json", {})
    configured = read_json(CONFIG / "locked_squad.json", {})
    locked = effective_planning_squad(team, configured, latest)
    candidates = build_candidates(predictions, universe)

    profiler = cProfile.Profile()
    started = perf_counter()
    result = profiler.runcall(audit_packages_from_candidates_fast, candidates, locked)
    elapsed = (perf_counter() - started) * 1000.0

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative")
    stats.print_stats(80)
    (OUT / "package-cprofile.txt").write_text(stream.getvalue(), encoding="utf-8")
    (OUT / "package-cprofile.json").write_text(json.dumps({
        "elapsed_ms": round(elapsed, 3),
        "evaluated_packages": (result.get("performance") or {}).get("evaluated_packages"),
        "keep_profiles": (result.get("performance") or {}).get("keep_profiles"),
        "bounded_state_cache_entries": (result.get("performance") or {}).get("bounded_state_cache_entries"),
        "chosen_profile_cache_entries": (result.get("performance") or {}).get("chosen_profile_cache_entries"),
        "frontier_per_position": (result.get("performance") or {}).get("frontier_per_position"),
        "beam_size": (result.get("performance") or {}).get("beam_size"),
        "search_quality_reduction": (result.get("performance") or {}).get("search_quality_reduction"),
        "overall_verdict": result.get("overall_verdict"),
        "recommended_package": result.get("recommended_package"),
    }, indent=2), encoding="utf-8")
    print(json.dumps({"package_cprofile_ms": round(elapsed, 3), "evaluated": (result.get("performance") or {}).get("evaluated_packages")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
