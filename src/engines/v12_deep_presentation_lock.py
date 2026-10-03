from __future__ import annotations

import json
import re
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

    expected_header = [
        "FPL MASTER V12 — DEEP REPORT",
        "Planning GW",
        "Logical report slot",
        "Report",
        "Sections",
    ]
    if list(cfg.get("header_order") or []) != expected_header:
        failures.append("HEADER_ORDER_MISMATCH")

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
        "S15": [("Evidence domain","Quality","Decision impact")],
        "S15B": [
            ("Scope","Definition","Coverage"),
            ("Rank","Manager","Team","Points","Gap"),
            ("Player","Owned","Starter","Bench","Captain","Vice","EO"),
            ("Player","Owned","Starter","Captain","EO"),
            ("Player","Owned","Starter","Bench","Captain","Vice","EO"),
            ("Rank","Manager","Pts","Gap","Position vs us","Squad overlap","XI overlap","Captain","Vice"),
            ("Player","Owned","Starter","Captain","EO"),
            ("Player","Football rank","xPts","League C","League EO","Competitive C","Competitive EO","Class"),
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

    s04 = sections.get("S04") or {}
    expected_s04_blocks = [
        "Material news since previous DEEP",
        "OUR15 news",
        "Watchlist / relevant-player news",
        "Team / tactical news",
        "Availability / injury / suspension news",
        "Role / minutes / set-piece developments",
        "Model-detected football changes",
        "Decision consequence",
    ]
    if list(s04.get("blocks") or []) != expected_s04_blocks:
        failures.append("S04_BLOCK_CONTRACT_MISMATCH")

    s14 = sections.get("S14") or {}
    expected_s14_blocks = [
        "Search integrity",
        "HOLD benchmark",
        "Canonical Monte Carlo",
        "Best challenger",
        "1/3/5GW comparison",
        "Execution economics",
        "Robustness / regret",
        "Verdict",
        "Actionability conclusion",
    ]
    if list(s14.get("blocks") or []) != expected_s14_blocks:
        failures.append("S14_SEMANTIC_BLOCK_CONTRACT_MISMATCH")

    s15 = sections.get("S15") or {}
    if list(s15.get("blocks") or []) != [
        "Overall evidence confidence",
        "Evidence limitations",
        "Decision implication",
        "PRIOR != CURRENT",
    ]:
        failures.append("S15_BLOCK_CONTRACT_MISMATCH")

    s17 = sections.get("S17") or {}
    if list(s17.get("blocks") or []) != ["Freshness", "Lineage", "Audit note"]:
        failures.append("S17_BLOCK_CONTRACT_MISMATCH")
    if s17.get("audit_note_optional") is not True:
        failures.append("S17_AUDIT_NOTE_OPTIONAL_NOT_LOCKED")

    ownership = dict(cfg.get("information_ownership") or {})
    expected_ownership = {
        "HEADER": "Report identity only",
        "S01": "Current decision / current action",
        "S14": "Optimizer, Monte Carlo, route and search evidence",
        "S15": "Decision evidence quality, completeness, CURRENT/PRIOR semantics and usability",
        "S17": "Technical source health, freshness, exact-occurrence binding, serving lineage and QA provenance",
        "S19": "Final consolidated judgement",
    }
    if ownership != expected_ownership:
        failures.append("INFORMATION_OWNERSHIP_MISMATCH")

    matrix = dict(cfg.get("s15_s17_ownership_matrix") or {})
    for key in (
        "Squad evidence completeness",
        "Availability evidence quality",
        "Underlying evidence quality",
        "Tactical/role evidence quality",
        "Fixture evidence completeness",
        "Non-PL workload completeness",
        "Finance completeness",
        "Price evidence decision usability",
        "Mini-league evidence usefulness",
        "Weather evidence usefulness",
        "PRIOR vs CURRENT semantics",
    ):
        if matrix.get(key) != "S15":
            failures.append(f"S15_OWNERSHIP_MISMATCH={key}")
    for key in (
        "V6 factual pipeline health",
        "Canonical V12 computation health",
        "Optimizer/MC execution health",
        "Price pipeline health",
        "Mini-league pipeline health",
        "Weather pipeline health",
        "Exact occurrence binding",
        "Serving/private delivery",
        "Presentation QA",
        "Privacy boundary",
    ):
        if matrix.get(key) != "S17":
            failures.append(f"S17_OWNERSHIP_MISMATCH={key}")
    if matrix.get("Workflow/run IDs") != "S17_AUDIT_ONLY":
        failures.append("S17_RUN_ID_AUDIT_OWNERSHIP_MISMATCH")
    if matrix.get("SHA/fingerprint") != "S17_AUDIT_ONLY":
        failures.append("S17_SHA_AUDIT_OWNERSHIP_MISMATCH")

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

_SECTION_HEADING_RE = re.compile(r"^##\s+(\d{1,2})(B?)\.\s+", re.MULTILINE)
_TABLE_DIVIDER_RE = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$")


def _rendered_sections(body: str) -> dict[str, str]:
    matches = list(_SECTION_HEADING_RE.finditer(str(body or "")))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        sid = f"S{int(match.group(1)):02d}{match.group(2)}"
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[sid] = body[start:end]
    return sections


def _rendered_tables(section_text: str) -> list[dict[str, Any]]:
    lines = section_text.splitlines()
    tables: list[dict[str, Any]] = []
    index = 0
    while index + 1 < len(lines):
        header = lines[index].strip()
        divider = lines[index + 1].strip()
        if header.startswith("|") and header.endswith("|") and _TABLE_DIVIDER_RE.match(divider):
            columns = tuple(cell.strip() for cell in header.strip("|").split("|"))
            rows: list[tuple[str, ...]] = []
            index += 2
            while index < len(lines):
                row = lines[index].strip()
                if not (row.startswith("|") and row.endswith("|")):
                    break
                rows.append(tuple(cell.strip() for cell in row.strip("|").split("|")))
                index += 1
            tables.append({"columns": columns, "rows": rows})
            continue
        index += 1
    return tables


def validate_rendered_deep_presentation(
    body: str,
    report: Mapping[str, Any] | None = None,
    contract: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate actual rendered Markdown against the executable DEEP lock."""
    cfg = dict(contract or load_deep_presentation_lock())
    sections_cfg = dict(cfg.get("sections") or {})
    rendered = _rendered_sections(body)
    failures: list[str] = []

    due = bool((report or {}).get("s16b_due"))
    expected = [
        sid for sid in cfg.get("section_order") or []
        if sid != "S16B" or due
    ]
    if list(rendered) != expected:
        failures.append("RENDERED_SECTION_ORDER_MISMATCH=" + ",".join(rendered))

    state_by_sid = {
        str(row.get("section_id") or "").upper(): str(row.get("state") or "").upper()
        for row in (report or {}).get("sections") or []
        if isinstance(row, Mapping)
    }

    for sid in expected:
        section_text = rendered.get(sid, "")
        spec = dict(sections_cfg.get(sid) or {})
        actual_tables = _rendered_tables(section_text)
        expected_tables = list(spec.get("tables") or [])
        state = state_by_sid.get(sid, "COMPLETE")
        if state == "COMPLETE":
            if len(actual_tables) != len(expected_tables):
                failures.append(
                    f"{sid}_RENDERED_TABLE_COUNT={len(actual_tables)}/{len(expected_tables)}"
                )
            for idx, table_spec in enumerate(expected_tables):
                if idx >= len(actual_tables):
                    break
                actual = actual_tables[idx]
                columns = tuple(table_spec.get("columns") or ())
                if actual["columns"] != columns:
                    failures.append(f"{sid}_RENDERED_COLUMNS_MISMATCH={idx + 1}")
                row_count = len(actual["rows"])
                required_exact = table_spec.get("rows_exact")
                if required_exact is None:
                    required_exact = table_spec.get("rows_exact_when_complete")
                minimum = table_spec.get("rows_min")
                if required_exact is not None and row_count != int(required_exact):
                    failures.append(
                        f"{sid}_RENDERED_ROWS={idx + 1}:{row_count}/{required_exact}"
                    )
                if minimum is not None and row_count < int(minimum):
                    failures.append(
                        f"{sid}_RENDERED_ROWS_MIN={idx + 1}:{row_count}/{minimum}"
                    )

        if sid == "S11" and state == "COMPLETE" and actual_tables:
            rows = actual_tables[0]["rows"]
            pos_index = actual_tables[0]["columns"].index("Pos")
            counts: dict[str, int] = {}
            for row in rows:
                if pos_index < len(row):
                    pos = row[pos_index].upper()
                    counts[pos] = counts.get(pos, 0) + 1
            if counts != {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}:
                failures.append("S11_RENDERED_POSITION_SPLIT_MISMATCH")

        if sid == "S16" and state == "COMPLETE":
            block_count = len(re.findall(r"(?m)^### PLAYER\s+\d+\s+—\s+", section_text))
            if block_count != int(spec.get("player_blocks_exact") or 15):
                failures.append(f"S16_RENDERED_PLAYER_BLOCKS={block_count}/15")

    raw_body = str(body or "")
    mode = str((report or {}).get("report_mode") or "DEEP").strip().upper()
    if mode == "DEEP":
        first_heading = _SECTION_HEADING_RE.search(raw_body)
        header_text = raw_body[: first_heading.start()] if first_heading else raw_body
        header_lines = [line.strip() for line in header_text.splitlines() if line.strip()]
        if header_lines[:1] != ["FPL MASTER V12 — DEEP REPORT"]:
            failures.append("HEADER_TITLE_MISSING_OR_NOT_FIRST")
        expected_header_labels = ("Planning GW:", "Logical report slot:", "Report:", "Sections:")
        actual_header_fields = header_lines[1:5]
        if len(actual_header_fields) != 4 or any(
            not actual_header_fields[index].startswith(label)
            for index, label in enumerate(expected_header_labels)
        ):
            failures.append("HEADER_EXACT_4_FIELD_CONTRACT_MISMATCH")
        if len(header_lines) != 5:
            failures.append(f"HEADER_VISIBLE_LINE_COUNT={len(header_lines)}/5")
        header_upper = header_text.upper()
        for token in (
            "CANONICAL RUN",
            "ORCHESTRATOR RUN",
            "REPORT RUN",
            "PRIVATE DELIVERY",
            "PRESENTATION QA",
            "SHA",
            "FINGERPRINT",
            "MC500",
            "ROUTES:",
            "UNIVERSE:",
            "SELECTED ACTION",
            "SERVING NOTE",
        ):
            if token in header_upper:
                failures.append("HEADER_FORBIDDEN_DETAIL=" + token)

    s15_text = rendered.get("S15", "")
    if state_by_sid.get("S15") == "COMPLETE":
        for required in (
            "OVERALL EVIDENCE CONFIDENCE:",
            "EVIDENCE LIMITATIONS",
            "DECISION IMPLICATION:",
            "PRIOR != CURRENT",
        ):
            if required not in s15_text.upper():
                failures.append("S15_REQUIRED_BLOCK_MISSING=" + required)
        for forbidden in (
            "PRIVATE DELIVERY",
            "PRESENTATION QA",
            "PRIVACY BOUNDARY",
            "ORCHESTRATOR",
            "WORKFLOW RUN",
            "SHA",
            "FINGERPRINT",
        ):
            if forbidden in s15_text.upper():
                failures.append("S15_TECHNICAL_OVERLAP=" + forbidden)

    s17_text = rendered.get("S17", "")
    if state_by_sid.get("S17") == "COMPLETE":
        for required in ("FRESHNESS:", "LINEAGE:"):
            if required not in s17_text.upper():
                failures.append("S17_REQUIRED_BLOCK_MISSING=" + required)
        for forbidden in (
            "SQUAD EVIDENCE",
            "AVAILABILITY EVIDENCE",
            "UNDERLYING EVIDENCE",
            "TACTICAL/ROLE EVIDENCE",
            "FIXTURE EVIDENCE",
            "WORKLOAD EVIDENCE",
            "FINANCE COMPLETENESS",
            "DECISION USABILITY",
        ):
            if forbidden in s17_text.upper():
                failures.append("S17_ANALYST_EVIDENCE_OVERLAP=" + forbidden)

    upper = raw_body.upper()
    for token in (
        "FULL ICON+ COMPOSITION",
        "POSITION FORMULAE:",
        "SCAN-DERIVED CHALLENGERS",
        "RAW_PAYLOAD_HASH",
        "ELEMENT_ID",
        "DIRECT6",
        "DIRECT SIX",
    ):
        if token in upper:
            failures.append("RENDERED_FORBIDDEN_TOKEN=" + token)

    if re.search(r"\{\s*['\"][A-Za-z0-9_]+['\"]\s*:", str(body or "")):
        failures.append("RENDERED_RAW_MAPPING_REPR")
    if re.search(
        r"\b(?:raw_payload_hash|source_age_minutes|authoritative_binding|payload_fingerprint)\b",
        str(body or ""),
        re.I,
    ):
        failures.append("RENDERED_INTERNAL_SNAKE_CASE")

    s15b = rendered.get("S15B", "")
    if s15b and state_by_sid.get("S15B") == "COMPLETE":
        for table in _rendered_tables(s15b):
            for col_index, column in enumerate(table["columns"]):
                if column not in {
                    "Coverage", "Owned", "Starter", "Bench", "Captain", "Vice", "EO",
                    "Squad overlap", "XI overlap", "League C", "League EO",
                    "Competitive C", "Competitive EO",
                }:
                    continue
                for row in table["rows"]:
                    if col_index >= len(row):
                        continue
                    value = row[col_index]
                    if value == "UNAVAILABLE":
                        continue
                    if not re.fullmatch(
                        r"-?\d+(?:\.\d+)?/-?\d+(?:\.\d+)? \(-?\d+(?:\.\d+)?%\)",
                        value,
                    ):
                        failures.append(
                            f"S15B_POPULATION_FORMAT_INVALID={column}:{value}"
                        )
                        break

    return list(dict.fromkeys(failures))

