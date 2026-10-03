from __future__ import annotations

from pathlib import Path

from src.engines.v12_deep_presentation_lock import (
    load_deep_presentation_lock,
    validate_rendered_deep_presentation,
)
from src.engines.v12_report_orchestration import _render_package_frontier_lines


def _heading(sid: str) -> str:
    suffix = "B" if sid.endswith("B") else ""
    number = int(sid[1:-1] if suffix else sid[1:])
    return f"## {number}{suffix}. TEST"


def _row_for(columns: list[str], *, index: int, sid: str) -> list[str]:
    out: list[str] = []
    ratio_columns = {
        "Coverage", "Owned", "Starter", "Bench", "Captain", "Vice", "EO",
        "Squad overlap", "XI overlap", "League C", "League EO",
        "Competitive C", "Competitive EO",
    }
    for column in columns:
        if column == "Pos" and sid == "S11":
            out.append(("GK", "DEF", "MID", "FWD")[(index - 1) // 5])
        elif column in ratio_columns:
            out.append("1/1 (100.0%)")
        elif column == "Rank" or column == "#":
            out.append(str(index))
        else:
            out.append(f"V{index}")
    return out


def _table(columns: list[str], rows: int, *, sid: str) -> list[str]:
    result = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for index in range(1, rows + 1):
        result.append("| " + " | ".join(_row_for(columns, index=index, sid=sid)) + " |")
    return result


def _valid_body(*, degraded: set[str] | None = None) -> tuple[str, dict]:
    degraded = degraded or set()
    cfg = load_deep_presentation_lock()
    blocks: list[str] = [
        "\n".join([
            "FPL MASTER V12 — DEEP REPORT",
            "Planning GW: GW6",
            "Logical report slot: 03 Oct 2026, 21:30 WIB",
            "Report: 🟢 READY_FULL · Exact occurrence",
            "Sections: 22/22 lifecycle-visible · S16B not due",
        ])
    ]
    report_sections = []
    for sid in cfg["section_order"]:
        if sid == "S16B":
            continue
        state = "DEGRADED" if sid in degraded else "COMPLETE"
        report_sections.append({"section_id": sid, "state": state, "content": {}})
        lines = [_heading(sid), f"Status: {state}"]
        spec = cfg["sections"][sid]
        if state == "COMPLETE":
            for table in spec.get("tables") or []:
                count = table.get("rows_exact")
                if count is None:
                    count = table.get("rows_exact_when_complete")
                if count is None:
                    count = table.get("rows_min")
                if count is None:
                    count = 1
                lines.extend(_table(table["columns"], int(count), sid=sid))
            if sid == "S15":
                lines.extend([
                    "Overall evidence confidence: MEDIUM-HIGH",
                    "Evidence limitations:",
                    "- Price predictor snapshot is stale; monitor only.",
                    "Decision implication: Evidence supports the current WAIT/HOLD posture.",
                    "PRIOR != CURRENT: PRIOR evidence is never represented as CURRENT.",
                ])
            if sid == "S16":
                for index in range(1, 16):
                    lines.append(f"### PLAYER {index} — P{index}")
                    lines.append("Readable player evidence.")
            if sid == "S17":
                lines.extend([
                    "Freshness: All decision-critical technical inputs are within contract.",
                    "Lineage: Visible report is bound to the exact DEEP occurrence.",
                    "Audit note: Run IDs and hashes remain in canonical audit artifacts.",
                ])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks), {"s16b_due": False, "sections": report_sections}


def test_rendered_deep_schema_lock_accepts_exact_markdown():
    body, report = _valid_body()
    assert validate_rendered_deep_presentation(body, report) == []


def test_rendered_deep_schema_lock_rejects_old_s01_two_column_renderer():
    body, report = _valid_body()
    body = body.replace(
        "| Axis | Status | Current call |",
        "| axis | state |",
        1,
    )
    failures = validate_rendered_deep_presentation(body, report)
    assert "S01_RENDERED_COLUMNS_MISMATCH=1" in failures


def test_rendered_deep_schema_lock_rejects_visible_legacy_and_machine_leaks():
    body, report = _valid_body()
    body += "\nFULL ICON+ COMPOSITION\nelement_id\nPOSITION FORMULAE:\nSCAN-DERIVED CHALLENGERS"
    failures = validate_rendered_deep_presentation(body, report)
    assert "RENDERED_FORBIDDEN_TOKEN=FULL ICON+ COMPOSITION" in failures
    assert "RENDERED_FORBIDDEN_TOKEN=ELEMENT_ID" in failures
    assert "RENDERED_FORBIDDEN_TOKEN=POSITION FORMULAE:" in failures
    assert "RENDERED_FORBIDDEN_TOKEN=SCAN-DERIVED CHALLENGERS" in failures


def test_rendered_deep_schema_lock_degraded_section_omits_malformed_placeholder_table():
    body, report = _valid_body(degraded={"S12"})
    s12 = body.split("## 12. TEST", 1)[1].split("## 13. TEST", 1)[0]
    assert "| # | Player | £ | Progress | ETA |" not in s12
    assert validate_rendered_deep_presentation(body, report) == []


def test_s14_visible_surface_is_bounded_to_one_challenger():
    payload = {
        "selected_route_id": "R1",
        "search_proof": {
            "owned_evaluated": 15,
            "owned_expected": 15,
            "eligible_universe_evaluated": 650,
            "eligible_universe_expected": 650,
            "outgoing_candidate_count": 15,
            "legal_route_count": 1965,
            "hold_included": True,
            "lossy_pruning": False,
            "search_authority": "CANONICAL",
        },
        "monte_carlo": {"actual_paths": 500000, "Q10": -2, "median": 0.2, "Q90": 3.0},
        "package_routes": [
            {"route": "HOLD", "action_verdict": "HOLD"},
            {"route": "R1", "three_gw": 2.0, "five_gw": 3.0, "p_beats_hold": 0.55, "Q90": 4.0, "action_verdict": "PREPARE"},
            {"route": "R2", "three_gw": 99.0, "five_gw": 99.0, "p_beats_hold": 0.99, "Q90": 99.0, "action_verdict": "ACT"},
        ],
    }
    visible = "\n".join(_render_package_frontier_lines(payload, section_state="COMPLETE"))
    assert "R1" in visible
    assert "R2" not in visible
    assert "SCAN-DERIVED CHALLENGERS" not in visible
    assert "### SEARCH INTEGRITY" in visible
    assert "### ACTIONABILITY CONCLUSION" in visible


def test_s04_grouping_code_no_longer_hardcodes_supported_groups_empty():
    source = (
        Path(__file__).resolve().parents[1]
        / "src" / "engines" / "v12_integrated_report_runner.py"
    ).read_text(encoding="utf-8")
    assert '"TEAM / TACTICAL": []' not in source
    assert '"OTHER MATERIAL": []' not in source
    assert '"TEAM / TACTICAL"' in source
    assert '"OTHER MATERIAL"' in source


def test_rendered_deep_schema_lock_rejects_header_overlap():
    body, report = _valid_body()
    body = body.replace(
        "Sections: 22/22 lifecycle-visible · S16B not due",
        "Sections: 22/22 lifecycle-visible · S16B not due\nMC500k: PASS",
        1,
    )
    failures = validate_rendered_deep_presentation(body, report)
    assert "HEADER_VISIBLE_LINE_COUNT=6/5" in failures
    assert "HEADER_FORBIDDEN_DETAIL=MC500" in failures


def test_rendered_deep_schema_lock_rejects_s15_technical_overlap():
    body, report = _valid_body()
    body = body.replace(
        "Decision implication: Evidence supports the current WAIT/HOLD posture.",
        "Decision implication: Evidence supports the current WAIT/HOLD posture.\nPrivate delivery: PASS",
        1,
    )
    failures = validate_rendered_deep_presentation(body, report)
    assert "S15_TECHNICAL_OVERLAP=PRIVATE DELIVERY" in failures


def test_rendered_deep_schema_lock_rejects_s17_analyst_evidence_overlap():
    body, report = _valid_body()
    body = body.replace(
        "Freshness: All decision-critical technical inputs are within contract.",
        "Freshness: All decision-critical technical inputs are within contract.\nFinance completeness: partial",
        1,
    )
    failures = validate_rendered_deep_presentation(body, report)
    assert "S17_ANALYST_EVIDENCE_OVERLAP=FINANCE COMPLETENESS" in failures
