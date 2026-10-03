from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
DEADLINE_LOCK = ROOT / "config" / "intelligence" / "v12_deadline_final_presentation_lock_v1.json"
MATCH_LOCK = ROOT / "config" / "intelligence" / "v12_match_presentation_lock_v1.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_deadline_final_presentation_lock() -> dict[str, Any]:
    return _load(DEADLINE_LOCK)


def load_match_presentation_lock() -> dict[str, Any]:
    return _load(MATCH_LOCK)


def validate_deadline_final_presentation_lock(contract: Mapping[str, Any] | None = None) -> list[str]:
    cfg = dict(contract or load_deadline_final_presentation_lock())
    failures: list[str] = []
    if cfg.get("inherits") != "config/intelligence/v12_deep_presentation_lock_v1.json":
        failures.append("DEADLINE_MUST_INHERIT_DEEP_LOCK")
    if list(cfg.get("header_additions") or []) != ["Official deadline","Countdown","Checkpoint","Decision state"]:
        failures.append("DEADLINE_HEADER_ADDITIONS_MISMATCH")
    overlay = dict(cfg.get("deadline_overlay") or {})
    expected_tables = {
        "S05": [
            ("Player","News","Availability impact","Evidence tier","As of","Decision impact"),
            ("Player","Predicted status","Evidence tier","Confidence","Decision consequence"),
        ],
        "S08": [("Role","Player","State","Reversal trigger")],
        "S14": [("Route","Legal","Affordable","1GW","3GW","5GW","P>HOLD","Value of waiting","Reversal / Abort","Action")],
        "S18": [("Field","Current call")],
    }
    for sid, cols in expected_tables.items():
        actual=[tuple(t.get("columns") or ()) for t in (overlay.get(sid) or {}).get("tables") or []]
        if actual != cols:
            failures.append(f"DEADLINE_{sid}_TABLE_COLUMNS_MISMATCH")
    s08=((overlay.get("S08") or {}).get("tables") or [{}])[0]
    if s08.get("rows_exact") != 2:
        failures.append("DEADLINE_S08_ROWS_NOT_2")
    s18=((overlay.get("S18") or {}).get("tables") or [{}])[0]
    if s18.get("rows") != ["NOW","NEXT","TRIGGER TO ACT","LATEST SAFE DECISION POINT","COST OF WAITING","ABORT / REVERSAL","BEST ALTERNATIVE"]:
        failures.append("DEADLINE_S18_ROWS_MISMATCH")
    s15b=dict(overlay.get("S15B") or {})
    if s15b.get("extra_tables_forbidden") is not True:
        failures.append("DEADLINE_S15B_NOT_PROTECTED")
    lock=dict((cfg.get("final_overlay") or {}).get("gw_lock_package") or {})
    expected_rows=["Target GW","Transfers out","Transfers in","Number of moves","FT / hit treatment","Bank after","Formation","Exact XI (11)","Bench GK","Outfield bench priority 1-3","Captain","Vice-captain","Chip","Primary action","Abort trigger","Fallback","Evidence timestamp","Canonical authority version"]
    if list(lock.get("table_columns") or []) != ["Field","Value"]:
        failures.append("FINAL_GW_LOCK_COLUMNS_MISMATCH")
    if list(lock.get("rows") or []) != expected_rows or lock.get("rows_exact") != 18:
        failures.append("FINAL_GW_LOCK_ROWS_MISMATCH")
    if lock.get("alternatives_below_lock_package_only") is not True:
        failures.append("FINAL_ALTERNATIVES_PLACEMENT_NOT_LOCKED")
    rules=dict(cfg.get("rules") or {})
    for key in ("deep_backbone_must_remain_exact","no_deep_column_changes","deadline_is_overlay_not_replacement","generic_recursive_key_value_dump_forbidden","s15b_must_remain_exact_deep_lock","s16b_lifecycle_must_not_be_modified","unknown_finance_must_not_be_fabricated"):
        if rules.get(key) is not True:
            failures.append(f"DEADLINE_RULE_NOT_LOCKED={key}")
    return failures


def validate_match_presentation_lock(contract: Mapping[str, Any] | None = None) -> list[str]:
    cfg=dict(contract or load_match_presentation_lock())
    failures: list[str]=[]
    expected=[f"MATCH{i}" for i in range(1,14)]
    if list(cfg.get("section_order") or []) != expected:
        failures.append("MATCH_SECTION_ORDER_MISMATCH")
    sections=dict(cfg.get("sections") or {})
    if list(sections) != expected:
        failures.append("MATCH_SCHEMA_ORDER_MISMATCH")
    expected_columns={
        "MATCH2":[("Player","Pos","Club","Match status")],
        "MATCH3":[("Player","Event","Match status","Minutes","Raw pts","Multiplier","Effective pts")],
        "MATCH4":[("Slot","Player"),("Out","Potential in","Status")],
        "MATCH5":[("Role","Player","Raw pts","Multiplier","Effective pts","Appearance")],
        "MATCH6":[("Player","Match status","Minutes","Raw pts","Multiplier","Effective pts")],
        "MATCH7":[("Player","Bonus","BPS")],
        "MATCH8":[("Player","Event","Detail","Match status","Decision implication")],
        "MATCH9":[("Player","Club","Signal","Evidence","Sustainable / noisy","OUR15 / next-opponent implication")],
        "MATCH10":[("Player","Owned","Starter","Captain","Vice","EO","Live consequence"),("Manager","Live points","Gap","Captain","Key threat","Key shield")],
        "MATCH11":[("Player / Team","Learning","Evidence","Next-GW implication","Action state")],
        "MATCH13":[("Source","Status","As of")],
    }
    for sid, cols in expected_columns.items():
        actual=[tuple(t.get("columns") or ()) for t in (sections.get(sid) or {}).get("tables") or []]
        if actual != cols:
            failures.append(f"{sid}_TABLE_COLUMNS_MISMATCH")
    for sid, count in (("MATCH2",15),("MATCH4",4),("MATCH5",2),("MATCH6",15)):
        table=((sections.get(sid) or {}).get("tables") or [{}])[0]
        if table.get("rows_exact") != count:
            failures.append(f"{sid}_ROWS_NOT_{count}")
    if list((sections.get("MATCH12") or {}).get("fields") or []) != ["Next critical observation","Why it matters","When to reassess"]:
        failures.append("MATCH12_FIELDS_MISMATCH")
    rules=dict(cfg.get("rules") or {})
    for key in ("generic_recursive_key_value_dump_forbidden","raw_python_or_json_repr_forbidden","element_id_forbidden_in_visible_tables","raw_internal_field_names_forbidden","machine_enum_as_primary_wording_forbidden","counts_require_denominator_and_percentage_when_population_known","healthy_submitted_picks_scope_survives_stale_standings"):
        if rules.get(key) is not True:
            failures.append(f"MATCH_RULE_NOT_LOCKED={key}")
    return failures
