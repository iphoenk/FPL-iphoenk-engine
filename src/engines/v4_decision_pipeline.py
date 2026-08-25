from __future__ import annotations

import json
from time import perf_counter

from src.utils import DATA, CONFIG, atomic_json, read_json
from src.engines.v4_wc_optimizer import decision_report
from src.engines.v4_wc_package_audit import audit_packages
from src.engines.v4_lineup_optimizer import optimize_lineup, MANUAL_FILE
from src.engines.v4_recommendation_sanity import sanity_report

OUTFILE = DATA / "decision_pipeline_v4.json"


def run():
    t0 = perf_counter()
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    locked = read_json(CONFIG / "locked_squad.json", {})
    manual = read_json(MANUAL_FILE, {})
    latest = read_json(DATA / "latest.json", {})
    timings = {"load_shared_inputs_ms": round((perf_counter() - t0) * 1000.0, 1)}

    t = perf_counter()
    wc = decision_report(predictions, universe, locked)
    atomic_json(DATA / "wc_decision_v4.json", wc)
    timings["wc_decision_ms"] = round((perf_counter() - t) * 1000.0, 1)

    t = perf_counter()
    packages = audit_packages(predictions, universe, locked)
    atomic_json(DATA / "wc_package_audit_v4.json", packages)
    timings["package_audit_ms"] = round((perf_counter() - t) * 1000.0, 1)

    t = perf_counter()
    lineup = optimize_lineup(predictions, universe, locked, manual=manual)
    atomic_json(DATA / "lineup_decision_v4.json", lineup)
    timings["lineup_ms"] = round((perf_counter() - t) * 1000.0, 1)

    t = perf_counter()
    sanity = sanity_report(predictions, universe, packages, latest)
    atomic_json(DATA / "recommendation_sanity_v4.json", sanity)
    timings["evidence_sanity_ms"] = round((perf_counter() - t) * 1000.0, 1)
    timings["total_pipeline_ms"] = round((perf_counter() - t0) * 1000.0, 1)

    out = {
        "schema_version": 460,
        "engine": "v4.6-unified-decision-pipeline",
        "timings": timings,
        "results": {
            "wc_raw": wc.get("classification"),
            "package_raw": packages.get("overall_verdict"),
            "recommendation_final": sanity.get("final_verdict"),
            "recommended_replacements": (sanity.get("recommended_package") or {}).get("replacements"),
            "lineup_governance": (lineup.get("governance") or {}).get("decision"),
            "formation": lineup.get("formation"),
            "captain": (lineup.get("captain") or {}).get("name"),
        },
        "performance_guardrails": {
            "shared_json_loaded_once": True,
            "concise_stdout": True,
            "search_quality_reduction": False,
        },
    }
    atomic_json(OUTFILE, out)
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
