from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "config" / "intelligence" / "v12_deep_presentation_lock_v1.json"


def load_deep_presentation_lock() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def validate_deep_presentation_lock_contract(
    contract: Mapping[str, Any] | None = None,
) -> list[str]:
    cfg = dict(contract or load_deep_presentation_lock())
    failures: list[str] = []
    expected_order = [
        "S01","S02","S03","S04","S05","S06","S06B","S07","S08","S09",
        "S10","S11","S12","S13","S14","S14B","S15","S15B","S16","S16B",
        "S17","S18","S19",
    ]
    if list(cfg.get("section_order") or []) != expected_order:
        failures.append("SECTION_ORDER_MISMATCH")

    sections = dict(cfg.get("sections") or {})
    if list(sections) != expected_order:
        failures.append("SECTION_SCHEMA_ORDER_MISMATCH")

    expected_tables = {
        "S01": [("Axis","Status","Current call")],
        "S02": [("Player","Pos","Opponent","Pstart","xMins","1GW xPts","3GW","5GW","Note")],
        "S06B": [("Player","Pstart","xMins","1GW xPts")],
        "S08": [("Rank","Player","xPts","Phaul","Pstart","xMins")],
        "S09": [("Chip","Status")],
        "S10": [("Player","Price","Direction","Progress")],
        "S11": [("Player","Pos","£","xMins","Pstart","DNP","Score","Admit","Evidence")],
        "S12": [("#","Player","£","Progress","ETA")],
        "S13": [("#","Player","£","Progress","ETA")],
        "S15": [("Evidence domain","Status")],
        "S15B": [
            ("Scope","Definition","Coverage"),
            ("Rank","Manager","Team","Points","Gap"),
            ("Player","Owned","Starter","Bench","Captain","Vice","EO"),
            ("Player","Owned","Starter","Captain","EO"),
            ("Player","Owned","Starter","Bench","Captain","Vice","EO"),
            ("Rank","Manager","Pts","Gap","Squad overlap","XI overlap","Captain","Vice"),
            ("Player","Owned","Starter","Captain","EO"),
            ("Player","Football rank","xPts","League C","League EO","Direct6 C","Direct6 EO","Class"),
        ],
        "S17": [("Plane","Status")],
    }

    for section_id, table_specs in expected_tables.items():
        actual = [
            tuple(row.get("columns") or ())
            for row in (sections.get(section_id) or {}).get("tables") or []
        ]
        if actual != table_specs:
            failures.append(f"{section_id}_TABLE_COLUMNS_MISMATCH")

    s02 = ((sections.get("S02") or {}).get("tables") or [{}])[0]
    s11 = ((sections.get("S11") or {}).get("tables") or [{}])[0]
    s12 = ((sections.get("S12") or {}).get("tables") or [{}])[0]
    s13 = ((sections.get("S13") or {}).get("tables") or [{}])[0]
    if s02.get("rows_exact") != 15:
        failures.append("S02_ROWS_NOT_15")
    if s11.get("rows_exact") != 20:
        failures.append("S11_ROWS_NOT_20")
    if dict(s11.get("position_split") or {}) != {"GK":5,"DEF":5,"MID":5,"FWD":5}:
        failures.append("S11_POSITION_SPLIT_MISMATCH")
    if s12.get("rows_exact_when_complete") != 20:
        failures.append("S12_ROWS_NOT_20_WHEN_COMPLETE")
    if s13.get("rows_exact_when_complete") != 20:
        failures.append("S13_ROWS_NOT_20_WHEN_COMPLETE")

    s15b = sections.get("S15B") or {}
    if s15b.get("forbid_table_merge") is not True:
        failures.append("S15B_TABLE_MERGE_NOT_FORBIDDEN")
    if "numerator/denominator" not in str(s15b.get("denominator_format") or ""):
        failures.append("S15B_DENOMINATOR_FORMAT_NOT_LOCKED")

    s16b = sections.get("S16B") or {}
    if s16b.get("visibility") != "lifecycle_controlled":
        failures.append("S16B_LIFECYCLE_VISIBILITY_NOT_LOCKED")

    rules = dict(cfg.get("global_rules") or {})
    for key in (
        "tables_must_use_exact_columns_and_order",
        "extra_table_columns_forbidden",
        "merged_unrelated_tables_forbidden",
        "missing_supported_population_denominator_forbidden",
        "percentage_without_count_denominator_forbidden_when_population_known",
    ):
        if rules.get(key) is not True:
            failures.append(f"GLOBAL_RULE_NOT_LOCKED={key}")
    return failures
