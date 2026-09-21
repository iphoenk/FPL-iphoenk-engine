from __future__ import annotations

from typing import Any, Mapping

from src.runtime_v6.domains.report_plane.delivery_integrity import RANK20_REQUIRED_FIELDS


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *["| " + " | ".join(row) + " |" for row in rows],
    ]


def _rank20_tables(
    *,
    direction: str,
    count: int,
    omit_field: str | None = None,
) -> list[str]:
    direction = direction.upper()
    offset = 200 if direction == "RISE" else 300
    rows: list[dict[str, str]] = []
    for rank in range(1, count + 1):
        rows.append(
            {
                "rank": str(rank),
                "element_id": str(offset + rank),
                "player_name": f"{direction}{rank:02d}",
                "current_price": "7.0",
                "ownership_percent": "12.3",
                "ownership_tag": "NON_OWNED",
                "direction": direction,
                "current_progress_percent": "95.0",
                "projection_offset_0_percent": "101.0" if direction == "RISE" else "-101.0",
                "predicted_change_cycle": "NEXT",
                "predicted_change_at": "2026-09-17T05:30:00+07:00",
                "eta_human": "05:30 WIB",
                "model_urgency": "WATCH",
                "confidence": "MEDIUM",
                "source": "V6_PRICE_MODEL",
                "observed_at": "2026-09-17T04:30:00+07:00",
                "raw_payload_hash": "a" * 64,
            }
        )

    groups = [
        [
            "rank",
            "element_id",
            "player_name",
            "current_price",
            "ownership_percent",
            "ownership_tag",
            "direction",
        ],
        [
            "rank",
            "current_progress_percent",
            "projection_offset_0_percent",
            "predicted_change_cycle",
            "predicted_change_at",
            "eta_human",
            "model_urgency",
        ],
        ["rank", "confidence", "source", "observed_at", "raw_payload_hash"],
    ]
    visible: list[str] = []
    for group in groups:
        headers = [field for field in group if field != omit_field]
        visible.extend(_table(headers, [[row[field] for field in headers] for row in rows]))
    assert set(RANK20_REQUIRED_FIELDS) == set().union(*map(set, groups))
    return visible


def _visible_weather_lines(state: str) -> list[str]:
    normalized = str(state or "MISSING").strip().upper()
    if normalized == "DIRECT_CHATGPT":
        return ["### WEATHER — DIRECT CHATGPT", "WEATHER: NO MATERIAL IMPACT"]
    if normalized == "SOURCE_DEGRADED":
        return ["WEATHER SOURCE: DEGRADED"]
    if normalized == "PRICE_NOT_IN_SCOPE":
        return ["WEATHER: NOT IN SCOPE — PRICE-ONLY CHECKPOINT"]
    if normalized == "MATCH_CURRENT":
        return ["WEATHER: MATCH CURRENT"]
    return ["WEATHER: MISSING"]


def valid_visible_body(
    pre_render_qa: Mapping[str, Any],
    *,
    rise_count: int = 20,
    include_14b: bool = True,
    include_inference: bool = True,
    weather_state_override: str | None = None,
    omit_rise_field: str | None = None,
    omit_fall_field: str | None = None,
    include_serious_math: bool = True,
) -> str:
    """Build a deterministic body matching the canonical visible Full skeleton."""
    lines = ["# 04:30 MORNING DEEP REVIEW"]
    titles = {
        "S01": "Keputusan / Strategic Status",
        "S02": "OUR15 Complete Current State",
        "S03": "Material Changes Since Previous Authoritative Report",
        "S04": "Fixture / Rest / Congestion / Match Conditions",
        "S05": "Exact Formation / XI / Bench",
        "S06": "Starting XI Battle / Marginal Slots",
        "S07": "Captain / Vice Captain",
        "S08": "Chip",
        "S09": "Actionable Price Radar",
        "S10": "Watchlist20",
        "S11": "RISE20",
        "S12": "FALL20",
        "S13": "Package Optimizer / Efficient Frontier / HOLD and Legal Routes",
        "S14": "Evidence Quality / Uncertainty / Provenance",
        "S14B": "ICON+ MINI LEAGUE",
        "S15": "ALL15 Next-GW Tactical / Player Style / Coach-System / Formation Fit",
        "S16": "Source Health / Freshness / Mapping / Lineage",
        "S17": "Action Board — WAIT / PREPARE / ACT",
        "S18": "Final Judgement",
    }
    section_ids = list(pre_render_qa.get("expected_section_ids", []))
    weather_state = str(
        weather_state_override
        if weather_state_override is not None
        else pre_render_qa.get("weather_contract_state") or "MISSING"
    ).strip().upper()

    for section_id in section_ids:
        if section_id == "S14B" and not include_14b:
            continue
        display = section_id.removeprefix("S")
        lines.append(f"## {display}. {titles.get(section_id, 'Report Section')}")
        if section_id == "S02":
            positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
            rows = [
                [str(i), str(i), f"OWN{i:02d}", pos]
                for i, pos in enumerate(positions, 1)
            ]
            lines.extend(_table(["rank", "element_id", "player_name", "position"], rows))
        elif section_id == "S04":
            lines.extend(_visible_weather_lines(weather_state))
        elif section_id == "S05":
            lines.append("XI: " + ", ".join(f"OWN{i:02d}" for i in range(1, 12)))
            lines.append("BENCH: " + ", ".join(f"OWN{i:02d}" for i in range(12, 16)))
        elif section_id == "S10":
            positions = ["GK"] * 5 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 5
            rows = [
                [str(i), str(100 + i), f"WATCH{i:02d}", pos, "NON_OWNED"]
                for i, pos in enumerate(positions, 1)
            ]
            lines.extend(
                _table(
                    ["rank", "element_id", "player_name", "position", "ownership_tag"],
                    rows,
                )
            )
        elif section_id == "S11":
            lines.extend(
                _rank20_tables(
                    direction="RISE",
                    count=rise_count,
                    omit_field=omit_rise_field,
                )
            )
        elif section_id == "S12":
            lines.extend(
                _rank20_tables(
                    direction="FALL",
                    count=20,
                    omit_field=omit_fall_field,
                )
            )
        elif section_id == "S13":
            lines.append("Material section content.")
            required_markers = {
                str(value).upper()
                for value in pre_render_qa.get("required_visible_markers", [])
            }
            if include_serious_math and "MATHEMATICAL DECISION STACK" in required_markers:
                lines.extend(
                    [
                        "### MATHEMATICAL DECISION STACK",
                        "BAYESIAN PRIOR -> POSTERIOR / SHRINKAGE: governed evidence",
                        "AVAILABILITY MIXTURE: P(AVAILABLE)=0.95 | P(START)=0.85 | P(BENCH)=0.10 | P(CAMEO)=0.08 | P(LATE CAMEO)=0.02 | P(DNP)=0.05",
                        "XMINS DISTRIBUTION: START/CAMEO/LATE_CAMEO/ZERO_MINUTES",
                        "EVENT PROBABILITIES: P(GOAL)=0.25 | P(ASSIST)=0.20 | P(RETURN)=0.40 | P(2+ RETURNS)=0.10 | P(HAUL)=0.12 | P(BLANK)=0.60 | P(NO ATTACK RETURN)=0.60",
                        "P1.3B POINT DISTRIBUTION: source=P1.3/P1.3B_POSTERIOR_PREDICTIVE | E[xPts]=5.8 | variance=8.4 | std=2.9 | quantiles={'p10': 2, 'p50': 5, 'p90': 10} | tails={'ge_10': 0.12}",
                        "HORIZONS 1GW / 3GW / 5GW: available",
                        "P(OUTPERFORM HOLD/COMPARATOR): 0.55",
                        "EXPECTED REGRET: 0.4",
                        "TAIL / FLOOR / CEILING: calibrated",
                        "INFORMATION VALUE OF WAITING: positive",
                        "COVARIANCE / CORRELATION: accounted",
                        "MONTE CARLO: NOT RUN — synthetic QA fixture",
                    ]
                )
        elif section_id == "S14":
            if pre_render_qa.get("expected_fact_keys"):
                lines.append("FACT: Official factual evidence is separated and timestamped.")
            if pre_render_qa.get("expected_model_keys"):
                lines.append("MODEL: Projection outputs are labelled as model estimates.")
            if include_inference and pre_render_qa.get("expected_inference_keys"):
                lines.append("INFERENCE: Decision implications are labelled as inference.")
        elif section_id == "S14B":
            if str(pre_render_qa.get("mini_league_contract_state") or "COMPLETE").upper() == "DEGRADED":
                lines.append("MINI_LEAGUE SOURCE: DEGRADED")
                lines.append("Current rank/gap unavailable; section retained truthfully without fabricated denominator.")
            else:
                lines.append("MANAGER COVERAGE: COMPLETE")
                lines.append("Current rank, gap, direct-rival equation and leverage are shown.")
        elif section_id == "S15":
            lines.extend(
                _table(
                    ["rank", "element_id", "player_name", "matchup_grade"],
                    [[str(i), str(i), f"OWN{i:02d}", "B"] for i in range(1, 16)],
                )
            )
        else:
            lines.append("Material section content.")
    return "\n".join(lines) + "\n"


def valid_match_visible_body(
    pre_render_qa: Mapping[str, Any],
    *,
    weather_state_override: str | None = None,
) -> str:
    """Build deterministic MATCH1-MATCH8 visible body for pure Match Mode."""
    weather_state = str(
        weather_state_override
        if weather_state_override is not None
        else pre_render_qa.get("weather_contract_state") or "MATCH_CURRENT"
    ).strip().upper()
    lines = ["# LIVE MATCH CHECKPOINT"]

    for index in range(1, 9):
        section_id = f"MATCH{index}"
        lines.append(f"## MATCH {index} — Live block")
        if section_id == "MATCH1":
            lines.append("Current live decision state and biggest swing.")
            lines.extend(_visible_weather_lines(weather_state))
        elif section_id == "MATCH2":
            positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
            rows = [
                [str(i), str(i), f"OWN{i:02d}", pos]
                for i, pos in enumerate(positions, 1)
            ]
            lines.extend(_table(["rank", "element_id", "player_name", "position"], rows))
            lines.append("XI: " + ", ".join(f"OWN{i:02d}" for i in range(1, 12)))
            lines.append("BENCH: " + ", ".join(f"OWN{i:02d}" for i in range(12, 16)))
        elif section_id == "MATCH5":
            if str(pre_render_qa.get("mini_league_contract_state") or "COMPLETE").upper() == "DEGRADED":
                lines.append("MINI_LEAGUE SOURCE: DEGRADED")
            else:
                lines.append("MANAGER COVERAGE: COMPLETE")
            lines.append("Current live ICON+ leverage and denominator state.")
        elif section_id == "MATCH8":
            if pre_render_qa.get("expected_fact_keys"):
                lines.append("FACT: Live factual evidence is timestamped.")
            if pre_render_qa.get("expected_model_keys"):
                lines.append("MODEL: Live projection delta is model-labelled.")
            if pre_render_qa.get("expected_inference_keys"):
                lines.append("INFERENCE: Live decision implication is inference-labelled.")
        else:
            lines.append("Material live-match content.")
    return "\n".join(lines) + "\n"
