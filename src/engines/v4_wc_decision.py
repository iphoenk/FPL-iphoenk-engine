from __future__ import annotations
import json
from src.utils import DATA, CONFIG, atomic_json, read_json
from src.engines.v4_wc_optimizer import decision_report


def run() -> dict:
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    locked = read_json(CONFIG / "locked_squad.json", {})
    report = decision_report(predictions, universe, locked)
    atomic_json(DATA / "wc_decision_v4.json", report)
    return report


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
