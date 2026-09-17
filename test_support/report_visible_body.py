from __future__ import annotations

from typing import Any, Mapping


def _table(header: str, rows: list[tuple[str, ...]]) -> list[str]:
    columns = header.split("|")
    return [
        f"| {header} |",
        "| " + " | ".join("---" for _ in columns) + " |",
        *["| " + " | ".join(row) + " |" for row in rows],
    ]


def valid_visible_body(
    pre_render_qa: Mapping[str, Any],
    *,
    rise_count: int = 20,
    include_14b: bool = True,
    include_inference: bool = True,
    weather_state_override: str | None = None,
) -> str:
    """Build a deterministic body that satisfies the R6 visible-body contract."""
    lines = ["# 04:30 MORNING DEEP REVIEW"]
    titles = {
        "S02": "OUR15 MANUAL FPL STATE",
        "S05": "EXACT FORMATION / XI / BENCH",
        "S10": "WATCHLIST20",
        "S11": "RISE20",
        "S12": "FALL20",
        "S14": "EVIDENCE",
        "S14B": "ICON+ MINI LEAGUE",
        "S15": "ALL15 NEXT-GW TACTICAL",
        "S16": "SOURCE HEALTH",
    }
    section_ids = list(pre_render_qa.get("expected_section_ids", []))
    for section_id in section_ids:
        if section_id == "S14B" and not include_14b:
            continue
        display = section_id.removeprefix("S")
        lines.append(f"## SECTION {display} — {titles.get(section_id, 'REPORT SECTION')}")
        if section_id == "S02":
            positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
            lines.extend(
                _table(
                    "#|Player|Pos",
                    [(str(i), f"OWN{i:02d}", pos) for i, pos in enumerate(positions, 1)],
                )
            )
        elif section_id == "S05":
            lines.append("XI: " + ", ".join(f"OWN{i:02d}" for i in range(1, 12)))
            lines.append("BENCH: " + ", ".join(f"OWN{i:02d}" for i in range(12, 16)))
        elif section_id == "S10":
            positions = ["GK"] * 5 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 5
            lines.extend(
                _table(
                    "#|Player|Pos",
                    [(str(i), f"WATCH{i:02d}", pos) for i, pos in enumerate(positions, 1)],
                )
            )
        elif section_id == "S11":
            lines.extend(
                _table("#|Player", [(str(i), f"RISE{i:02d}") for i in range(1, rise_count + 1)])
            )
        elif section_id == "S12":
            lines.extend(
                _table("#|Player", [(str(i), f"FALL{i:02d}") for i in range(1, 21)])
            )
        elif section_id == "S14":
            for key in pre_render_qa.get("expected_fact_keys", []):
                lines.append(f"FACT: {key}")
            for key in pre_render_qa.get("expected_model_keys", []):
                lines.append(f"MODEL: {key}")
            if include_inference:
                for key in pre_render_qa.get("expected_inference_keys", []):
                    lines.append(f"INFERENCE: {key}")
        elif section_id == "S14B":
            lines.append("MINI_LEAGUE_DENOMINATOR: COMPLETE")
            lines.append("Current rank and direct-rival equation are shown.")
        elif section_id == "S15":
            lines.extend(
                _table(
                    "#|Player|Matchup",
                    [(str(i), f"OWN{i:02d}", "B") for i in range(1, 16)],
                )
            )
        elif section_id == "S16":
            weather_state = str(
                weather_state_override
                if weather_state_override is not None
                else pre_render_qa.get("weather_contract_state") or "MISSING"
            ).strip().upper()
            lines.append(f"WEATHER: {weather_state}")
            lines.append("Source health current.")
        else:
            lines.append("Material section content.")
    return "\n".join(lines) + "\n"
