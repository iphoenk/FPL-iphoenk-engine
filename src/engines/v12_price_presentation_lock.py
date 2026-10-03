from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
PRICE_LOCK = ROOT / "config" / "intelligence" / "v12_price_presentation_lock_v1.json"


def load_price_presentation_lock() -> dict[str, Any]:
    return json.loads(PRICE_LOCK.read_text(encoding="utf-8"))


def validate_price_presentation_lock(
    contract: Mapping[str, Any] | None = None,
) -> list[str]:
    cfg = dict(contract or load_price_presentation_lock())
    failures: list[str] = []
    expected = [f"PRICE{i}" for i in range(1, 13)]
    if list(cfg.get("section_order") or []) != expected:
        failures.append("PRICE_SECTION_ORDER_MISMATCH")
    sections = dict(cfg.get("sections") or {})
    if list(sections) != expected:
        failures.append("PRICE_SCHEMA_ORDER_MISMATCH")

    expected_columns = {
        "PRICE2": [("Player","Pos","Market","Sell","Direction","Progress","ETA / Status","Decision impact")],
        "PRICE3": [("Player","Official Δ","Current price","Evidence class")],
        "PRICE4": [
            ("Player","Price pressure","Squad need","Football horizon","Affordability impact","Action"),
            ("Route","Price risk","Current affordability","Football relevance","Decision impact"),
        ],
        "PRICE5": [("Player","Pos","£","Direction","Progress","ETA / Status","Football relevance","Squad relevance","Affordability relevance")],
        "PRICE6": [("#","Player","Pos / Club","£","Progress","Direction","ETA / Status","Confidence","OUR15","Watchlist","As of")],
        "PRICE7": [("#","Player","Pos / Club","£","Progress","Direction","ETA / Status","Confidence","OUR15","Watchlist","As of")],
        "PRICE8": [
            ("Route","OUT sell","IN price","Bank before","Affordable","Bank after","FT","Hit"),
            ("Route","Target +0.1","OUT -0.1","Combined","Route survives","1GW","3GW","5GW","Reversal risk"),
        ],
        "PRICE9": [("Player / Route","Scope","Owned","Starter","Captain","EO","Price implication")],
        "PRICE10": [("Field","Current call")],
        "PRICE11": [("Source","Status","As of")],
    }
    for sid, cols in expected_columns.items():
        actual = [
            tuple(table.get("columns") or ())
            for table in (sections.get(sid) or {}).get("tables") or []
        ]
        if actual != cols:
            failures.append(f"{sid}_TABLE_COLUMNS_MISMATCH")

    if ((sections.get("PRICE2") or {}).get("tables") or [{}])[0].get("rows_exact_when_complete") != 15:
        failures.append("PRICE2_ROWS_NOT_15")
    for sid in ("PRICE5","PRICE6","PRICE7"):
        if ((sections.get(sid) or {}).get("tables") or [{}])[0].get("rows_exact_when_complete") != 20:
            failures.append(f"{sid}_ROWS_NOT_20")
    action = ((sections.get("PRICE10") or {}).get("tables") or [{}])[0]
    if action.get("rows_exact") != 6 or list(action.get("rows") or []) != [
        "NOW","NEXT","TRIGGER TO ACT","LATEST SAFE DECISION POINT","COST OF WAITING","ABORT / REVERSAL"
    ]:
        failures.append("PRICE10_ACTION_BOARD_ROWS_MISMATCH")

    rules = dict(cfg.get("rules") or {})
    for key in (
        "canonical_truth_only",
        "no_recalculation_in_presentation",
        "generic_recursive_key_value_dump_forbidden",
        "raw_python_or_json_repr_forbidden",
        "element_id_forbidden_in_visible_tables",
        "raw_internal_field_names_forbidden",
        "machine_enum_as_primary_wording_forbidden",
        "raw_run_workflow_sha_fingerprint_forbidden_in_main_body",
        "fact_model_inference_must_remain_distinct",
        "tables_must_use_exact_columns_and_order",
    ):
        if rules.get(key) is not True:
            failures.append(f"PRICE_RULE_NOT_LOCKED={key}")
    return failures
