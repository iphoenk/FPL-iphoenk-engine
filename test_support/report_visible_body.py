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
    """Build a deterministic body matching the current Canonical DEEP skeleton."""
    lines = ["# 04:30 MORNING DEEP REVIEW"]
    titles = {
        "S01": "Decision / Status",
        "S02": "OUR15",
        "S03": "DECISION DELTA",
        "S04": "Changes",
        "S05": "Fixtures / Rest / Conditions",
        "S06": "Formation / XI / Bench",
        "S07": "XI Battle",
        "S08": "C / VC",
        "S09": "Chip",
        "S10": "Actionable Price Radar",
        "S11": "Watchlist20",
        "S12": "RISE20",
        "S13": "FALL20",
        "S14": "Package Optimizer / Frontier including HOLD baseline",
        "S15": "Evidence Quality",
        "S15B": "ICON+ Mini-League",
        "S16": "ALL15 Next-GW Tactical / Probability",
        "S17": "Source Health / Freshness / Lineage",
        "S18": "WAIT / PREPARE / ACT + Trigger / Reversal",
        "S19": "Final Judgement",
        "GW_LOCK_PACKAGE": "GW LOCK PACKAGE",
    }
    section_ids = list(pre_render_qa.get("expected_section_ids", []))
    weather_state = str(
        weather_state_override
        if weather_state_override is not None
        else pre_render_qa.get("weather_contract_state") or "MISSING"
    ).strip().upper()
    required_markers = {
        str(value).upper()
        for value in pre_render_qa.get("required_visible_markers", [])
    }

    for section_id in section_ids:
        if section_id == "S15B" and not include_14b:
            continue
        if section_id == "GW_LOCK_PACKAGE":
            lines.append("## GW LOCK PACKAGE")
            lines.append(
                "Target GW 6 | transfers OUT none | transfers IN none | XI exact11 | "
                "bench GK + outfield priority | captain / vice | primary action WAIT."
            )
            continue
        display = section_id.removeprefix("S")
        lines.append(f"## {display}. {titles.get(section_id, 'Report Section')}")
        if section_id == "S01":
            lines.append("OPERATIONAL STATE: WAIT")
            lines.append("Material change: none. Next actionable trigger: fresh team news.")
        elif section_id == "S02":
            positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
            rows = [
                [str(i), str(i), f"OWN{i:02d}", pos]
                for i, pos in enumerate(positions, 1)
            ]
            lines.extend(_table(["rank", "element_id", "player_name", "position"], rows))
        elif section_id == "S03":
            lines.append("NO MATERIAL DECISION CHANGE")
        elif section_id == "S04":
            lines.append("Role, injury, price and tactical changes are reconciled here.")
        elif section_id == "S05":
            lines.append("Fixtures, rest and congestion are mapped for the decision horizon.")
            lines.extend(_visible_weather_lines(weather_state))
        elif section_id == "S06":
            lines.append("Formation: 3-5-2")
            lines.append("XI: " + ", ".join(f"OWN{i:02d}" for i in range(1, 12)))
            lines.append("BENCH: " + ", ".join(f"OWN{i:02d}" for i in range(12, 16)))
            lines.append("Bench GK: OWN12")
            lines.append("Outfield autosub priority: 1 OWN13, 2 OWN14, 3 OWN15")
        elif section_id == "S07":
            lines.append("XI BATTLE: P(start), xMins, cameo/DNP risk and expected-regret comparison.")
        elif section_id == "S08":
            lines.append("Captain: OWN09 | Vice Captain: OWN05")
        elif section_id == "S09":
            lines.append("Chip: HOLD | trigger: no material chip edge.")
        elif section_id == "S10":
            lines.append("ALL15 actionable price radar with FACT current price and MODEL price signal.")
        elif section_id == "S11":
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
        elif section_id == "S12":
            lines.extend(
                _rank20_tables(
                    direction="RISE",
                    count=rise_count,
                    omit_field=omit_rise_field,
                )
            )
        elif section_id == "S13":
            lines.extend(
                _rank20_tables(
                    direction="FALL",
                    count=20,
                    omit_field=omit_fall_field,
                )
            )
        elif section_id == "S14":
            lines.append("HOLD baseline and scan-derived legal package routes.")
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
            if include_serious_math and "UNIVERSE SCAN / OPTIMAL TEAM IMPACT" in required_markers:
                lines.extend(
                    [
                        "### UNIVERSE SCAN / OPTIMAL TEAM IMPACT",
                        "SEARCH PROOF: OUR15 15/15 | UNIVERSE 667/667 | OUTGOING 15/15 | LEGAL ROUTES 42 | HOLD True | LOSSY PRUNING False | AUTHORITY FULL",
                        "SCAN-DERIVED CHALLENGERS: Candidate A, Candidate B, Candidate C",
                        "PACKAGE FRONTIER: HOLD plus scan-derived legal routes with 1GW/3GW/5GW team-impact deltas.",
                    ]
                )
        elif section_id == "S15":
            lines.append("Authority, observed_at, freshness, status and decision-use are shown by scope.")
            if pre_render_qa.get("expected_fact_keys"):
                lines.append("FACT: Official factual evidence is separated and timestamped.")
            if pre_render_qa.get("expected_model_keys"):
                lines.append("MODEL: Projection outputs are labelled as model estimates.")
            if include_inference and pre_render_qa.get("expected_inference_keys"):
                lines.append("INFERENCE: Decision implications are labelled as inference.")
        elif section_id == "S15B":
            if str(pre_render_qa.get("mini_league_contract_state") or "COMPLETE").upper() == "DEGRADED":
                lines.append("MINI_LEAGUE SOURCE: DEGRADED")
                lines.append("Current rank/gap unavailable; healthy submitted-picks scope remains visible.")
            else:
                lines.append("MANAGER COVERAGE: COMPLETE")
                lines.append("Current rank, gap, EO, rival equation and leverage are shown.")
        elif section_id == "S16":
            lines.extend(
                _table(
                    ["rank", "element_id", "player_name", "matchup_grade"],
                    [[str(i), str(i), f"OWN{i:02d}", "B"] for i in range(1, 16)],
                )
            )
        elif section_id == "S17":
            lines.append("ENGINE / DATA STATUS")
            lines.append("V6 core: GREEN | Publication: PASS | Universe authority: FULL")
        elif section_id == "S18":
            lines.extend(
                [
                    "NOW: WAIT",
                    "TRIGGER TO ACT: material team-news or route-value threshold",
                    "ABORT / REVERSAL: challenger loses role/security or route legality",
                    "NEXT CHECKPOINT: next Canonical report occurrence",
                ]
            )
        elif section_id == "S19":
            lines.append("Final judgement: WAIT; no executable change without the stated trigger.")
        else:
            lines.append("Material section content.")
    return "\n".join(lines) + "\n"


def valid_match_visible_body(
    pre_render_qa: Mapping[str, Any],
    *,
    weather_state_override: str | None = None,
) -> str:
    """Build deterministic MATCH1-MATCH13 visible body for pure Match Mode."""
    weather_state = str(
        weather_state_override
        if weather_state_override is not None
        else pre_render_qa.get("weather_contract_state") or "MATCH_CURRENT"
    ).strip().upper()
    lines = ["# LIVE MATCH CHECKPOINT"]

    for index in range(1, 14):
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
        elif section_id == "MATCH10":
            if str(pre_render_qa.get("mini_league_contract_state") or "COMPLETE").upper() == "DEGRADED":
                lines.append("MINI_LEAGUE SOURCE: DEGRADED")
            else:
                lines.append("MANAGER COVERAGE: COMPLETE")
            lines.append("Current live ICON+ leverage and denominator state.")
        elif section_id == "MATCH13":
            if pre_render_qa.get("expected_fact_keys"):
                lines.append("FACT: Live factual evidence is timestamped.")
            if pre_render_qa.get("expected_model_keys"):
                lines.append("MODEL: Live projection delta is model-labelled.")
            if pre_render_qa.get("expected_inference_keys"):
                lines.append("INFERENCE: Live decision implication is inference-labelled.")
            lines.append("ENGINE / DATA STATUS: current fixture and source freshness.")
        else:
            lines.append("Material live-match content.")
    return "\n".join(lines) + "\n"
