from __future__ import annotations

"""R6 authority for parsing and validating the actual visible report body.

This module is intentionally downstream of R4 structural compute validation and R5
provenance validation. It does not trust renderer-supplied metadata as evidence that
content was actually visible to the user.
"""

from collections import Counter
from hashlib import sha256
import re
from typing import Any, Mapping, Sequence

from .delivery_integrity import RANK20_REQUIRED_FIELDS, validate_rank20


_SECTION_EXPLICIT_RE = re.compile(
    r"(?mi)^\s{0,3}#{1,6}\s*SECTION\s+(?P<section>\d{1,2}B?)\b[^\n]*$"
)
_SECTION_NUMBERED_RE = re.compile(
    r"(?mi)^\s{0,3}#{1,6}\s*(?P<section>\d{1,2}B?)\.\s+[^\n]+$"
)
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
_EVIDENCE_RE = re.compile(r"(?mi)^\s*(FACT|MODEL|INFERENCE)\s*:\s*(.+?)\s*$")
_TRUNCATION_PATTERNS = (
    re.compile(r"(?i)\[\s*TRUNCATED\s*\]"),
    re.compile(r"(?i)\.\.\.\s*\(\s*truncated\s*\)"),
    re.compile(r"(?i)\boutput\s+truncated\b"),
    re.compile(r"(?i)\bcontent\s+truncated\b"),
)
_PROGRESS_RE = re.compile(
    r"(?i)^\s*(?:generating|building|preparing|processing|loading)\s+(?:the\s+)?report\b"
)

_VISIBLE_COUNT_SECTIONS: Mapping[str, tuple[str, str]] = {
    "OUR15": ("S02", "TABLE"),
    "XI": ("S05", "XI"),
    "BENCH": ("S05", "BENCH"),
    "WATCHLIST20": ("S10", "WATCHLIST"),
    "RISE20": ("S11", "RANK20_RISE"),
    "FALL20": ("S12", "RANK20_FALL"),
}
_ADDITIONAL_VISIBLE_COUNTS: Mapping[str, tuple[str, str, int]] = {
    "ALL15_TACTICAL": ("S15", "TABLE", 15),
}
_POSITION_TARGET = {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}

_HEADER_ALIASES = {
    "#": "rank",
    "id": "element_id",
    "element": "element_id",
    "player": "player_name",
    "name": "player_name",
    "price": "current_price",
    "ownership": "ownership_percent",
    "ownership_pct": "ownership_percent",
    "own_pct": "ownership_percent",
    "owned": "ownership_tag",
    "owned_tag": "ownership_tag",
    "own_tag": "ownership_tag",
    "dir": "direction",
    "now": "current_progress_percent",
    "current_progress": "current_progress_percent",
    "projected": "projection_offset_0_percent",
    "projection": "projection_offset_0_percent",
    "cycle": "predicted_change_cycle",
    "predicted_at": "predicted_change_at",
    "eta_model_wib": "predicted_change_at",
    "eta": "eta_human",
    "urgency": "model_urgency",
    "conf": "confidence",
    "observed": "observed_at",
    "hash": "raw_payload_hash",
    "provenance_hash": "raw_payload_hash",
    "pos": "position",
}


def _normalize_section_id(token: str) -> str:
    match = re.fullmatch(r"(?i)(\d{1,2})(B?)", str(token or "").strip())
    if not match:
        return ""
    return f"S{int(match.group(1)):02d}{match.group(2).upper()}"


def _section_matches(body: str) -> list[re.Match[str]]:
    matches = [*_SECTION_EXPLICIT_RE.finditer(body), *_SECTION_NUMBERED_RE.finditer(body)]
    return sorted(matches, key=lambda match: match.start())


def _parse_sections(body: str) -> tuple[list[str], dict[str, list[str]], int | None]:
    matches = _section_matches(body)
    section_ids: list[str] = []
    content_by_id: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        section_id = _normalize_section_id(match.group("section"))
        section_ids.append(section_id)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content_by_id.setdefault(section_id, []).append(body[match.end():end].strip())
    first_start = matches[0].start() if matches else None
    return section_ids, content_by_id, first_start


def _split_table_cells(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator_row(line: str) -> bool:
    cells = _split_table_cells(line)
    return bool(cells) and all(_TABLE_SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells)


def _parse_markdown_tables(section_body: str) -> list[tuple[list[str], list[list[str]]]]:
    lines = section_body.splitlines()
    tables: list[tuple[list[str], list[list[str]]]] = []
    index = 0
    while index + 1 < len(lines):
        if not _TABLE_LINE_RE.match(lines[index]) or not _is_separator_row(lines[index + 1]):
            index += 1
            continue
        headers = _split_table_cells(lines[index])
        index += 2
        rows: list[list[str]] = []
        while index < len(lines) and _TABLE_LINE_RE.match(lines[index]):
            if index + 1 < len(lines) and _is_separator_row(lines[index + 1]):
                break
            if not _is_separator_row(lines[index]):
                rows.append(_split_table_cells(lines[index]))
            index += 1
        tables.append((headers, rows))
    return tables


def _count_markdown_table_rows(section_body: str) -> int:
    return sum(len(rows) for _, rows in _parse_markdown_tables(section_body))


def _normalize_header(value: str) -> str:
    raw = str(value or "").strip().lower().replace("%", "_pct")
    raw = re.sub(r"[`*]", "", raw)
    raw = re.sub(r"[^a-z0-9#]+", "_", raw).strip("_")
    return _HEADER_ALIASES.get(raw, raw)


def _count_label_list(section_body: str, label: str) -> tuple[int, list[str]]:
    match = re.search(rf"(?mi)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", section_body)
    if not match:
        return 0, []
    values = [item.strip() for item in match.group(1).split(",") if item.strip()]
    return len(values), values


def _extract_table_column(section_body: str, field: str) -> list[str]:
    result: list[str] = []
    for headers, rows in _parse_markdown_tables(section_body):
        normalized = [_normalize_header(header) for header in headers]
        if field not in normalized:
            continue
        column = normalized.index(field)
        for row in rows:
            if len(row) > column and row[column].strip():
                result.append(row[column].strip())
    return result


def _watchlist_contract(section_body: str) -> tuple[int, list[str]]:
    failures: list[str] = []
    ranks = _extract_table_column(section_body, "rank")
    positions = [value.upper() for value in _extract_table_column(section_body, "position")]
    ownership = [value.upper() for value in _extract_table_column(section_body, "ownership_tag")]
    actual = len(set(ranks)) if ranks else _count_markdown_table_rows(section_body)
    if len(positions) != actual:
        failures.append("VISIBLE_WATCHLIST_POSITION_MISSING")
    else:
        position_counts = Counter(positions)
        if any(position_counts.get(position, 0) != target for position, target in _POSITION_TARGET.items()):
            failures.append("VISIBLE_WATCHLIST_POSITION_DISTRIBUTION_INVALID")
    if len(ownership) != actual or any(tag != "NON_OWNED" for tag in ownership):
        failures.append("VISIBLE_WATCHLIST_OWNERSHIP_INVALID")
    return actual, failures


def _rank20_contract(
    section_body: str,
    *,
    label: str,
) -> tuple[int, list[str]]:
    records: dict[int, dict[str, Any]] = {}
    failures: list[str] = []
    table_duplicate_ranks: set[int] = set()

    for headers, rows in _parse_markdown_tables(section_body):
        canonical_headers = [_normalize_header(header) for header in headers]
        if "rank" not in canonical_headers:
            continue
        rank_column = canonical_headers.index("rank")
        seen_in_table: set[int] = set()
        for row in rows:
            if len(row) != len(canonical_headers) or rank_column >= len(row):
                failures.append(f"VISIBLE_RANK20_ROW_MALFORMED={label}")
                continue
            try:
                rank = int(row[rank_column].strip())
            except (TypeError, ValueError):
                failures.append(f"VISIBLE_RANK20_RANK_INVALID={label}")
                continue
            if rank in seen_in_table:
                table_duplicate_ranks.add(rank)
            seen_in_table.add(rank)
            target = records.setdefault(rank, {"rank": rank})
            for field, value in zip(canonical_headers, row):
                if field not in RANK20_REQUIRED_FIELDS:
                    continue
                text = value.strip()
                normalized_value: Any = rank if field == "rank" else text
                if field in target and target[field] != normalized_value:
                    failures.append(f"VISIBLE_RANK20_FIELD_CONFLICT={label}:{rank}:{field}")
                target[field] = normalized_value

    if table_duplicate_ranks:
        failures.append(
            f"VISIBLE_RANK20_DUPLICATE_RANK={label}:{','.join(map(str, sorted(table_duplicate_ranks)))}"
        )

    actual = len(records)
    expected_rank_set = set(range(1, 21))
    if actual == 20 and set(records) != expected_rank_set:
        failures.append(f"VISIBLE_RANK20_RANK_SET_INVALID={label}")

    missing_fields = sorted(
        field
        for field in RANK20_REQUIRED_FIELDS
        if any(not str(records.get(rank, {}).get(field, "")).strip() for rank in records)
    )
    if missing_fields:
        failures.append(f"VISIBLE_RANK20_SCHEMA_MISSING={label}:{','.join(missing_fields)}")

    if actual == 20 and set(records) == expected_rank_set and not missing_fields:
        semantic = validate_rank20(
            [records[rank] for rank in range(1, 21)],
            label=label,
        )
        for semantic_failure in semantic["failures"]:
            failures.append(f"VISIBLE_RANK20_SEMANTIC_INVALID={label}:{semantic_failure}")

    return actual, failures


def _parse_evidence_labels(body: str) -> dict[str, list[str]]:
    result = {"FACT": [], "MODEL": [], "INFERENCE": []}
    for match in _EVIDENCE_RE.finditer(body):
        namespace = match.group(1).upper()
        value = match.group(2).strip()
        if value:
            result[namespace].append(value)
    return result


def _body_has_progress_placeholder(body: str, first_section_start: int | None) -> bool:
    prefix = body if first_section_start is None else body[:first_section_start]
    return any(_PROGRESS_RE.search(line) for line in prefix.splitlines())


def _parse_weather_state(body: str) -> str:
    if re.search(r"(?mi)^\s{0,3}#{1,6}\s*WEATHER\s*[—-]\s*DIRECT\s+CHATGPT\s*$", body):
        return "DIRECT_CHATGPT"
    if re.search(r"(?mi)^\s*WEATHER\s+SOURCE\s*:\s*DEGRADED\s*$", body):
        return "SOURCE_DEGRADED"
    if re.search(
        r"(?mi)^\s*WEATHER\s*:\s*NOT\s+IN\s+SCOPE\s*[—-]\s*PRICE-ONLY\s+CHECKPOINT\s*$",
        body,
    ):
        return "PRICE_NOT_IN_SCOPE"
    if re.search(r"(?mi)^\s*WEATHER\s*:\s*MATCH\s+CURRENT\s*$", body):
        return "MATCH_CURRENT"
    legacy = re.search(
        r"(?mi)^\s*WEATHER\s*:\s*(DIRECT_CHATGPT|SOURCE_DEGRADED|PRICE_NOT_IN_SCOPE|MATCH_CURRENT)\s*$",
        body,
    )
    return legacy.group(1).upper() if legacy else "MISSING"


def _mini_league_denominator_complete(body: str) -> bool:
    return bool(
        re.search(r"(?mi)^\s*MINI[_ -]LEAGUE[_ -]DENOMINATOR\s*:\s*COMPLETE\s*$", body)
        or re.search(r"(?mi)^\s*MANAGER\s+COVERAGE\s*:\s*COMPLETE\s*$", body)
    )


def validate_visible_report_body(
    *,
    rendered_body: str,
    expected_section_ids: Sequence[str],
    expected_counts: Mapping[str, int],
    expected_fact_keys: Sequence[str],
    expected_model_keys: Sequence[str],
    expected_inference_keys: Sequence[str],
    expected_weather_state: str,
    mini_league_denominator_complete_required: bool,
) -> dict[str, Any]:
    """Validate what was actually rendered, not what renderer metadata claims."""
    body = rendered_body if isinstance(rendered_body, str) else ""
    failures: list[str] = []
    if not body.strip():
        failures.append("VISIBLE_BODY_EMPTY")

    section_ids, section_content, first_section_start = _parse_sections(body)
    if _body_has_progress_placeholder(body, first_section_start):
        failures.append("VISIBLE_BODY_PROGRESS_PLACEHOLDER")
    if any(pattern.search(body) for pattern in _TRUNCATION_PATTERNS):
        failures.append("VISIBLE_BODY_TRUNCATION_MARKER")

    expected_sections = [str(section_id).strip().upper() for section_id in expected_section_ids]
    expected_set = set(expected_sections)
    actual_set = set(section_ids)
    section_counts = Counter(section_ids)
    missing_sections = [section_id for section_id in expected_sections if section_id not in actual_set]
    duplicate_sections = [
        section_id for section_id in expected_sections if section_counts.get(section_id, 0) > 1
    ]
    unexpected_sections = list(
        dict.fromkeys(section_id for section_id in section_ids if section_id not in expected_set)
    )

    if missing_sections:
        failures.append(f"VISIBLE_SECTIONS_MISSING={','.join(missing_sections)}")
    if duplicate_sections:
        failures.append(f"VISIBLE_SECTION_DUPLICATE={','.join(duplicate_sections)}")
    if unexpected_sections:
        failures.append(f"VISIBLE_SECTION_UNEXPECTED={','.join(unexpected_sections)}")
    if section_ids != expected_sections:
        failures.append("VISIBLE_SECTION_SEQUENCE_MISMATCH")

    empty_sections = [
        section_id
        for section_id in expected_sections
        if section_id in section_content
        and not any(part.strip() for part in section_content[section_id])
    ]
    if empty_sections:
        failures.append(f"VISIBLE_SECTION_EMPTY={','.join(empty_sections)}")

    visible_counts: dict[str, int] = {}
    for label, target in expected_counts.items():
        section_id, strategy = _VISIBLE_COUNT_SECTIONS.get(label, ("", ""))
        section_body = "\n".join(section_content.get(section_id, []))
        strategy_failures: list[str] = []
        if strategy == "TABLE":
            actual = _count_markdown_table_rows(section_body)
        elif strategy in {"XI", "BENCH"}:
            actual, _ = _count_label_list(section_body, strategy)
        elif strategy == "WATCHLIST":
            actual, strategy_failures = _watchlist_contract(section_body)
        elif strategy == "RANK20_RISE":
            actual, strategy_failures = _rank20_contract(
                section_body,
                label="RISE20",
            )
        elif strategy == "RANK20_FALL":
            actual, strategy_failures = _rank20_contract(
                section_body,
                label="FALL20",
            )
        else:
            actual = 0
        visible_counts[label] = actual
        failures.extend(strategy_failures)
        if actual != target:
            failures.append(f"VISIBLE_COUNT_MISMATCH={label}:{actual}!={target}")

    for label, (section_id, strategy, target) in _ADDITIONAL_VISIBLE_COUNTS.items():
        section_body = "\n".join(section_content.get(section_id, []))
        actual = _count_markdown_table_rows(section_body) if strategy == "TABLE" else 0
        visible_counts[label] = actual
        if actual != target:
            failures.append(f"VISIBLE_COUNT_MISMATCH={label}:{actual}!={target}")

    our15_body = "\n".join(section_content.get("S02", []))
    our15_ids = _extract_table_column(our15_body, "element_id")
    our15_names = _extract_table_column(our15_body, "player_name")
    if len(our15_ids) != 15 or len(set(our15_ids)) != 15:
        failures.append("VISIBLE_OUR15_IDENTITY_INVALID")

    xi_count, xi_names = _count_label_list("\n".join(section_content.get("S05", [])), "XI")
    bench_count, bench_names = _count_label_list("\n".join(section_content.get("S05", [])), "BENCH")
    if xi_count == 11 and bench_count == 4 and our15_names:
        if set(xi_names) & set(bench_names) or set(xi_names + bench_names) != set(our15_names):
            failures.append("VISIBLE_XI_BENCH_NOT_EXACT_OUR15")

    tactical_ids = _extract_table_column("\n".join(section_content.get("S15", [])), "element_id")
    if len(tactical_ids) == 15 and our15_ids and set(tactical_ids) != set(our15_ids):
        failures.append("VISIBLE_ALL15_TACTICAL_ID_SET_MISMATCH")

    evidence = _parse_evidence_labels(body)
    if expected_fact_keys and not evidence["FACT"]:
        failures.append("VISIBLE_FACT_KEYS_MISMATCH")
    if expected_model_keys and not evidence["MODEL"]:
        failures.append("VISIBLE_MODEL_KEYS_MISMATCH")
    if expected_inference_keys and not evidence["INFERENCE"]:
        failures.append("VISIBLE_INFERENCE_KEYS_MISMATCH")

    visible_weather_state = _parse_weather_state(body)
    normalized_expected_weather = str(expected_weather_state or "MISSING").strip().upper()
    if visible_weather_state != normalized_expected_weather:
        failures.append(
            f"VISIBLE_WEATHER_CONTRACT_STATE_MISMATCH={normalized_expected_weather}!={visible_weather_state}"
        )

    mini_league_complete = _mini_league_denominator_complete(body)
    if mini_league_denominator_complete_required and not mini_league_complete:
        failures.append("VISIBLE_MINI_LEAGUE_DENOMINATOR_INCOMPLETE")

    body_hash = sha256(body.encode("utf-8")).hexdigest()
    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "body_sha256": body_hash,
        "section_ids": section_ids,
        "counts": visible_counts,
        "fact_keys": evidence["FACT"],
        "model_keys": evidence["MODEL"],
        "inference_keys": evidence["INFERENCE"],
        "weather_contract_state": visible_weather_state,
        "mini_league_denominator_complete": mini_league_complete,
    }
