from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    service = ROOT / "src/services/challenger_comparator_service.py"
    text = service.read_text(encoding="utf-8")
    erroneous = '        "start_probability_trend_5gw": start_trend,\n        "expected_minutes_trend_5gw": minute_trend,\n'
    if text.count(erroneous) != 1:
        raise RuntimeError(f"unexpected trend insertion count: {text.count(erroneous)}")
    text = text.replace(erroneous, "", 1)
    anchor = '        "dnp_probability_3gw": round(dnp, 4) if dnp is not None else None,\n        "raw_attacking_rate": round(raw_attacking, 4),\n'
    replacement = '        "dnp_probability_3gw": round(dnp, 4) if dnp is not None else None,\n        "start_probability_trend_5gw": start_trend,\n        "expected_minutes_trend_5gw": minute_trend,\n        "raw_attacking_rate": round(raw_attacking, 4),\n'
    if anchor not in text:
        raise RuntimeError("role sustainability return anchor missing")
    text = text.replace(anchor, replacement, 1)
    service.write_text(text, encoding="utf-8")

    ownership_path = ROOT / "config/architecture_ownership_registry.json"
    ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
    shared = ownership.setdefault("shared_primitives", [])
    if not any(row.get("id") == "SQUAD_LEGALITY" for row in shared):
        shared.append({
            "id": "SQUAD_LEGALITY",
            "owner": "domain_legality",
            "implementation": "src.engines.fpl_legality.squad_shape_is_legal",
            "consumers": ["raw_snapshot", "optimization", "framework_postflight", "challenger_comparator"]
        })
    comparator = next(row for row in shared if row.get("id") == "CHALLENGER_COMPARISON_ORCHESTRATION")
    comparator["reuses"] = ["SQUAD_LEGALITY" if value == "PLAN_AND_SQUAD_LEGALITY" else value for value in comparator.get("reuses") or []]
    ownership_path.write_text(json.dumps(ownership, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("comparator integration correction applied")


if __name__ == "__main__":
    main()
