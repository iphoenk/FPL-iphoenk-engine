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


_SECTION_HEADING_RE = re.compile(
    r"(?mi)^\s{0,3}#{1,6}\s*SECTION\s+(?P<section>\d{1,2}B?)\b[^\n]*$"
)
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
_EVIDENCE_RE = re.compile(r"(?mi)^\s*(FACT|MODEL|INFERENCE)\s*:\s*(.+?)\s*$")
_WEATHER_RE = re.compile(r"(?mi)^\s*WEATHER\s*:\s*([A-Z0-9_+-]+)\s*$")
_MINI_DENOMINATOR_RE = re.compile(
    r"(?mi)^\s*MINI_LEAGUE_DENOMINATOR\s*:\s*([A-Z_]+)\s*$"
)
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
    "WATCHLIST20": ("S10", "TABLE"),
    "RISE20": ("S11", "TABLE"),
    "FALL20": ("S12", "TABLE"),
}
_ADDITIONAL_VISIBLE_COUNTS: Mapping[str, tuple[str, str, int]] = {
    "ALL15_TACTICAL": ("S15", "TABLE", 15),
}


def _normalize_section_id(token: str) -> str:
    match = re.fullmatch(r"(?i)(\d{1,2})(B?)", str(token or "").strip())
    if not match:
        return ""
    return f"S{int(match.group(1)):02d}{match.group(2).upper()}"


def _parse_sections(body: str) -> tuple[list[str], dict[str, list[str]]]:
    matches = list(_SECTION_HEADING_RE.finditer(body))
    section_ids: list[str] = []
    content_by_id: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        section_id = _normalize_section_id(match.group("section"))
        section_ids.append(section_id)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content_by_id.setdefault(section_id, []).append(body[match.end():end].strip())
    return section_ids, content_by_id


def _split_table_cells(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator_row(line: str) -> bool:
    cells = _split_table_cells(line)
    return bool(cells) and all(_TABLE_SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells)


def _count_markdown_table_rows(section_body: str) -> int:
    """Count data rows across markdown tables, excluding header/separator rows."""
    count = 0
    awaiting_separator = False
    in_table = False
    for raw_line in section_body.splitlines():
        if not _TABLE_LINE_RE.match(raw_line):
            awaiting_separator = False
            in_table = False
            continue
        if _is_separator_row(raw_line):
            if awaiting_separator:
                in_table = True
            awaiting_separator = False
            continue
        if in_table:
            count += 1
        else:
            awaiting_separator = True
    return count


def _count_label_list(section_body: str, label: str) -> int:
    match = re.search(rf"(?mi)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", section_body)
    if not match:
        return 0
    return len([item for item in match.group(1).split(",") if item.strip()])


def _parse_evidence_keys(body: str) -> dict[str, list[str]]:
    result = {"FACT": [], "MODEL": [], "INFERENCE": []}
    for match in _EVIDENCE_RE.finditer(body):
        namespace = match.group(1).upper()
        values = [item.strip() for item in re.split(r"[,;]", match.group(2)) if item.strip()]
        result[namespace].extend(values)
    return {key: sorted(set(values)) for key, values in result.items()}


def _body_has_progress_placeholder(body: str, first_section_start: int | None) -> bool:
    prefix = body if first_section_start is None else body[:first_section_start]
    return any(_PROGRESS_RE.search(line) for line in prefix.splitlines())


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

    first_section_match = _SECTION_HEADING_RE.search(body)
    if _body_has_progress_placeholder(
        body,
        first_section_match.start() if first_section_match is not None else None,
    ):
        failures.append("VISIBLE_BODY_PROGRESS_PLACEHOLDER")
    if any(pattern.search(body) for pattern in _TRUNCATION_PATTERNS):
        failures.append("VISIBLE_BODY_TRUNCATION_MARKER")

    section_ids, section_content = _parse_sections(body)
    expected_sections = [str(section_id).strip().upper() for section_id in expected_section_ids]
    expected_set = set(expected_sections)
    actual_set = set(section_ids)
    counts = Counter(section_ids)
    missing_sections = [section_id for section_id in expected_sections if section_id not in actual_set]
    duplicate_sections = [
        section_id for section_id in expected_sections if counts.get(section_id, 0) > 1
    ]
    unexpected_sections = [section_id for section_id in section_ids if section_id not in expected_set]
    unexpected_sections = list(dict.fromkeys(unexpected_sections))

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
        if strategy == "TABLE":
            actual = _count_markdown_table_rows(section_body)
        elif strategy in {"XI", "BENCH"}:
            actual = _count_label_list(section_body, strategy)
        else:
            actual = 0
        visible_counts[label] = actual
        if actual != target:
            failures.append(f"VISIBLE_COUNT_MISMATCH={label}:{actual}!={target}")

    for label, (section_id, strategy, target) in _ADDITIONAL_VISIBLE_COUNTS.items():
        section_body = "\n".join(section_content.get(section_id, []))
        actual = _count_markdown_table_rows(section_body) if strategy == "TABLE" else 0
        visible_counts[label] = actual
        if actual != target:
            failures.append(f"VISIBLE_COUNT_MISMATCH={label}:{actual}!={target}")

    evidence = _parse_evidence_keys(body)
    expected_fact = sorted(str(key) for key in expected_fact_keys)
    expected_model = sorted(str(key) for key in expected_model_keys)
    expected_inference = sorted(str(key) for key in expected_inference_keys)
    if evidence["FACT"] != expected_fact:
        failures.append("VISIBLE_FACT_KEYS_MISMATCH")
    if evidence["MODEL"] != expected_model:
        failures.append("VISIBLE_MODEL_KEYS_MISMATCH")
    if evidence["INFERENCE"] != expected_inference:
        failures.append("VISIBLE_INFERENCE_KEYS_MISMATCH")
    if set(evidence["FACT"]) & set(evidence["MODEL"]):
        failures.append("VISIBLE_FACT_MODEL_BLEED")

    weather_match = _WEATHER_RE.search(body)
    visible_weather_state = weather_match.group(1).upper() if weather_match else "MISSING"
    expected_weather = str(expected_weather_state or "MISSING").strip().upper() or "MISSING"
    if visible_weather_state != expected_weather:
        failures.append(
            f"VISIBLE_WEATHER_CONTRACT_STATE_MISMATCH={visible_weather_state}!={expected_weather}"
        )

    denominator_match = _MINI_DENOMINATOR_RE.search(body)
    visible_denominator_complete = bool(
        denominator_match and denominator_match.group(1).upper() == "COMPLETE"
    )
    if mini_league_denominator_complete_required and not visible_denominator_complete:
        failures.append("VISIBLE_MINI_LEAGUE_DENOMINATOR_INCOMPLETE")

    return {
        "status": "PASS" if not failures else "FAIL",
        "visible_body_validated": not failures,
        "failures": failures,
        "body_sha256": sha256(body.encode("utf-8")).hexdigest(),
        "section_ids": section_ids,
        "missing_sections": missing_sections,
        "duplicate_sections": duplicate_sections,
        "unexpected_sections": unexpected_sections,
        "counts": visible_counts,
        "fact_keys": evidence["FACT"],
        "model_keys": evidence["MODEL"],
        "inference_keys": evidence["INFERENCE"],
        "weather_contract_state": visible_weather_state,
        "mini_league_denominator_complete": visible_denominator_complete,
    }
