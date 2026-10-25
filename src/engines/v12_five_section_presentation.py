"""Mandatory five-section presentation contract for the ordinary ChatGPT report.

Presentation only: canonical DEEP section text is regrouped verbatim under exactly five
top-level sections. Nothing is recalculated, reworded or invented; a missing value stays
missing and a failed check fails closed (the report is then never canonical).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "intelligence" / "v12_five_section_presentation_v1.json"
CANONICAL_IDS = (
    "S01", "S02", "S03", "S04", "S05", "S06", "S06B", "S07", "S08", "S09", "S10", "S11", "S12", "S13",
    "S14", "S14B", "S15", "S15B", "S16", "S16B", "S17", "S18", "S19",
)
OPTIONAL_IDS = frozenset({"S16B"})  # only when the post-match review is due

_SECTION_RE = re.compile(r"(?m)^## (\d{1,2})(B?)\.\s+(.+?)\s*$")
_TOP_RE = re.compile(r"(?m)^## (?!\d)(.+?)\s*$")
_GW_RE = re.compile(r"(?m)^Planning GW:\s*GW?\s*(\d{1,2})\b")
_SLOT_RE = re.compile(r"(?m)^Logical report slot:\s*(\d{1,2} \w{3} \d{4}), (\d{2}:\d{2}) WIB\s*$")
_STATUS_RE = re.compile(r"(?m)^Report:\s*(.+)$")
_HEADING_RE = re.compile(r"(?m)^(#{1,6})(\s)")


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def config_failures(cfg: Mapping[str, Any] | None = None) -> list[str]:
    cfg = dict(cfg or load_config())
    groups = cfg.get("section_groups") or {}
    failures = []
    if list(groups) != list(cfg.get("top_level_sections") or []) or len(groups) != 5:
        failures.append("GROUPS_NOT_EXACTLY_FIVE_IN_ORDER")
    flat = [s for ids in groups.values() for s in ids]
    if sorted(flat) != sorted(CANONICAL_IDS):
        failures.append("GROUP_MAP_NOT_EXACT_PARTITION_OF_CANONICAL_SECTIONS")
    return failures


def parse_canonical(body: str) -> dict[str, Any]:
    matches = list(_SECTION_RE.finditer(body))
    sections: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for i, m in enumerate(matches):
        sid = f"S{int(m.group(1)):02d}{m.group(2)}"
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        if sid in sections:
            sections[sid]["duplicate"] = "1"
            continue
        sections[sid] = {"title": m.group(3), "text": body[m.end():end].strip("\n"), "duplicate": ""}
        order.append(sid)
    header = body[: matches[0].start()] if matches else body
    return {"header": header.rstrip("\n"), "sections": sections, "order": order}


def _names(line: str) -> list[str]:
    return [p.strip() for p in line.split(",") if p.strip()]


def _line(text: str, label: str) -> str | None:
    m = re.search(rf"(?m)^{re.escape(label)}:\s*(.+?)\s*$", text)
    return m.group(1) if m else None


def extract_facts(parsed: Mapping[str, Any]) -> dict[str, Any]:
    secs = parsed["sections"]
    header = parsed["header"]
    s06 = secs.get("S06", {}).get("text", "")
    s08 = secs.get("S08", {}).get("text", "")
    s19 = secs.get("S19", {}).get("text", "")
    s18 = secs.get("S18", {}).get("text", "")
    gw = _GW_RE.search(header)
    slot = _SLOT_RE.search(header)
    xi = _names(_line(s06, "XI") or "")
    bench = _names(_line(s06, "Bench") or "")
    cv = re.search(r"Current C:\s*(.+?);\s*Current VC:\s*(.+?);", s08)
    s19_cv = re.search(r"(?m)^Captain:\s*(.+?)\s*\([^)]*\);\s*Vice:\s*(.+?)\.?\s*$", s19)
    s18_cv = re.search(r"(?m)^Canonical C/VC:\s*(.+?)\s*/\s*(.+?);", s18)
    s19_xi_line = _line(s19, "XI") or ""
    s19_xi = _names(s19_xi_line.split(";", 1)[1]) if ";" in s19_xi_line else []
    status = _STATUS_RE.search(header)
    return {
        "gw": int(gw.group(1)) if gw else None,
        "slot_text": f"{slot.group(1)}, {slot.group(2)} WIB" if slot else None,
        "report_status": status.group(1) if status else "",
        "xi": xi,
        "bench": bench,
        "s19_xi": s19_xi,
        "cv": {"S08": (cv.group(1), cv.group(2)) if cv else None,
               "S19": (s19_cv.group(1), s19_cv.group(2)) if s19_cv else None,
               "S18": (s18_cv.group(1), s18_cv.group(2)) if s18_cv else None},
    }


def _demote(text: str) -> str:
    return _HEADING_RE.sub(lambda m: "#" * min(6, len(m.group(1)) + 1) + m.group(2), text)


def build_view(body: str, cfg: Mapping[str, Any] | None = None) -> str:
    """Regroup the canonical DEEP body under exactly five `## ` sections (verbatim section text)."""
    cfg = dict(cfg or load_config())
    parsed = parse_canonical(body)
    out = [parsed["header"].strip("\n")] if parsed["header"].strip() else []
    for title, ids in cfg["section_groups"].items():
        out += ["", f"## {title}"]
        for sid in sorted((i for i in ids if i in parsed["sections"]), key=CANONICAL_IDS.index):
            sec = parsed["sections"][sid]
            num = sid[1:]
            num = f"{int(num[:2])}{num[2:]}"
            out += ["", f"### {num}. {sec['title']}", _demote(sec["text"])]
    return "\n".join(out).rstrip("\n") + "\n"


def build_degraded_fallback(reason: str, cfg: Mapping[str, Any] | None = None) -> str:
    """Explicit non-canonical output: still exactly five sections, no report values."""
    cfg = dict(cfg or load_config())
    safe = re.sub(r"\s+", " ", str(reason or "UNSPECIFIED"))[:200]
    out = [f"{cfg['degraded_marker']}: no verified report available ({safe})"]
    for title in cfg["top_level_sections"]:
        out += ["", f"## {title}", "NOT AVAILABLE: no verified canonical data. Nothing was inferred or reused."]
    return "\n".join(out) + "\n"


def validate_view(
    view: str,
    *,
    canonical_body: str | None = None,
    expected_gw: int | None = None,
    expected_slot_wib: str | None = None,
    cfg: Mapping[str, Any] | None = None,
) -> list[str]:
    """Deterministic presentation QA. Empty list means pass; any code fails closed."""
    cfg = dict(cfg or load_config())
    failures = config_failures(cfg)
    titles = cfg["top_level_sections"]
    tops = [m.group(1) for m in _TOP_RE.finditer(view)]
    if len(tops) != 5:
        failures.append(f"SECTION_COUNT={len(tops)}")
    if tops != titles:
        failures.append("SECTION_ORDER_OR_TITLE_MISMATCH")
    marker = cfg["degraded_marker"]
    if marker in view:
        # explicit fallback: must carry no report claims
        if re.search(r"(?m)^(XI|Bench|Captain|Current C):", view):
            failures.append("DEGRADED_FALLBACK_CONTAINS_REPORT_CLAIMS")
        return sorted(set(failures))
    if canonical_body is None:
        failures.append("CANONICAL_BODY_REQUIRED")
        return sorted(set(failures))

    parsed = parse_canonical(canonical_body)
    facts = extract_facts(parsed)
    secs = parsed["sections"]
    for sid, sec in secs.items():
        if sec["duplicate"]:
            failures.append(f"CANONICAL_SECTION_DUPLICATE={sid}")
    missing = [s for s in CANONICAL_IDS if s not in secs and s not in OPTIONAL_IDS]
    failures += [f"CANONICAL_SECTION_MISSING={s}" for s in missing]
    unknown = [s for s in secs if s not in CANONICAL_IDS]
    failures += [f"CANONICAL_SECTION_UNKNOWN={s}" for s in unknown]

    # every present canonical section appears exactly once, in its group, in canonical order, verbatim
    expected = build_view(canonical_body, cfg)
    if view.strip() != expected.strip():
        failures.append("VIEW_NOT_VERBATIM_REGROUPING_OF_CANONICAL_BODY")

    if facts["gw"] is None:
        failures.append("GW_MISSING")
    elif expected_gw is not None and facts["gw"] != expected_gw:
        failures.append(f"GW_MISMATCH={facts['gw']}!={expected_gw}")
    if expected_slot_wib is not None and facts["slot_text"] != expected_slot_wib:
        failures.append("OCCURRENCE_SLOT_MISMATCH")

    xi, bench = facts["xi"], facts["bench"]
    if len(xi) != 11:
        failures.append(f"XI_COUNT={len(xi)}")
    if len(set(xi)) != len(xi):
        failures.append("XI_DUPLICATE_PLAYER")
    if len(bench) != 4 or len(set(bench)) != len(bench):
        failures.append(f"BENCH_INVALID={len(bench)}")
    if set(xi) & set(bench):
        failures.append("XI_BENCH_OVERLAP")
    if facts["s19_xi"] and set(facts["s19_xi"]) != set(xi):
        failures.append("XI_INCONSISTENT_S06_S19")

    pairs = {k: v for k, v in facts["cv"].items() if v}
    if not pairs.get("S08"):
        failures.append("CV_MISSING_S08")
    if len(set(pairs.values())) > 1:
        failures.append("CV_INCONSISTENT_ACROSS_SECTIONS")
    for pair in pairs.values():
        cap, vice = pair
        if cap == vice:
            failures.append("CV_SAME_PLAYER")
        if xi and (cap not in xi or vice not in xi):
            failures.append("CV_NOT_IN_XI")

    if "DEGRADED" in facts["report_status"].upper():
        head = "\n".join(view.splitlines()[:8]).upper()
        if "DEGRADED" not in head:
            failures.append("DEGRADED_STATE_NOT_EXPLICIT")
    if "s06-dashboard" in secs.get("S06", {}).get("text", "") and "s06-dashboard" not in view:
        failures.append("PITCH_DASHBOARD_DROPPED")
    return sorted(set(failures))


def gate(body: str, *, expected_gw: int, expected_slot_wib: str) -> list[str]:
    """Convenience for producers: build the view and validate it against the canonical body."""
    try:
        return validate_view(build_view(body), canonical_body=body, expected_gw=expected_gw,
                             expected_slot_wib=expected_slot_wib)
    except Exception as exc:  # fail closed on any parser error
        return [f"PRESENTATION_ERROR={type(exc).__name__}"]
