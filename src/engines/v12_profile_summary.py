from __future__ import annotations

"""Render deterministic cProfile evidence for controlled V12 performance runs."""

import argparse
import json
from pathlib import Path
import pstats
import re
from typing import Any

STAGE_PATTERN = re.compile(
    r"\[V12_STAGE\]\s+(?P<status>PASS|FAILED)\s+"
    r"(?P<name>[A-Z0-9_]+)\s+elapsed_seconds=(?P<seconds>[0-9.]+)"
)

CATEGORY_RULES = {
    "FOUNDATION": (
        "v12_analytics_foundation.py",
        "load_v6_analytics_foundation",
        "require_match_foundation",
    ),
    "STAGE2": (
        "v12_stage2_derived_cache.py",
        "historical_projection.py",
        "v12_stage1_analytics.py",
        "v12_contextual_dynamics.py",
        "v12_player_events.py",
        "v12_player_minutes.py",
        "v12_position_probability_components.py",
        "p0_decision_quality.py",
        "load_or_build_stage2_projections",
    ),
    "PACKAGE_COMBINE": (
        "v12_package_utility.py",
        "combine_package_utility_surfaces",
        "derive_bounded_future_frontier",
        "_frontier",
    ),
    "MONTE_CARLO": (
        "v12_monte_carlo.py",
        "run_package_monte_carlo",
    ),
}

ENTRYPOINTS = {
    "FOUNDATION": ("load_v6_analytics_foundation", "require_match_foundation"),
    "STAGE2": ("load_or_build_stage2_projections",),
    "PACKAGE_COMBINE": ("combine_package_utility_surfaces",),
    "MONTE_CARLO": ("run_package_monte_carlo",),
}


def _row(key: tuple[str, int, str], raw: tuple[Any, ...]) -> dict[str, Any]:
    filename, line, function = key
    cc, nc, tt, ct, _callers = raw
    return {
        "file": filename,
        "line": int(line),
        "function": function,
        "primitive_calls": int(cc),
        "total_calls": int(nc),
        "internal_seconds": round(float(tt), 6),
        "cumulative_seconds": round(float(ct), 6),
    }


def _matches(row: dict[str, Any], tokens: tuple[str, ...]) -> bool:
    haystack = f"{row['file']}::{row['function']}"
    return any(token in haystack for token in tokens)


def build_summary(pstats_path: Path, log_path: Path | None) -> dict[str, Any]:
    stats = pstats.Stats(str(pstats_path))
    rows = [_row(key, raw) for key, raw in stats.stats.items()]
    rows.sort(
        key=lambda item: (
            -float(item["cumulative_seconds"]),
            -float(item["internal_seconds"]),
            str(item["file"]),
            int(item["line"]),
            str(item["function"]),
        )
    )

    stage_wall: dict[str, dict[str, Any]] = {}
    if log_path and log_path.exists():
        for match in STAGE_PATTERN.finditer(
            log_path.read_text(encoding="utf-8", errors="replace")
        ):
            stage_wall[match.group("name")] = {
                "status": match.group("status"),
                "elapsed_seconds": float(match.group("seconds")),
            }

    categories: dict[str, Any] = {}
    for category, tokens in CATEGORY_RULES.items():
        matched = [row for row in rows if _matches(row, tokens)]
        entry_names = ENTRYPOINTS[category]
        entry_rows = [
            row for row in matched if str(row["function"]) in entry_names
        ]
        categories[category] = {
            "entrypoints": entry_rows,
            "top_functions": matched[:30],
            "note": (
                "cumulative_seconds is inclusive and must not be summed across "
                "nested functions"
            ),
        }

    return {
        "schema_version": 1,
        "profiler": "cProfile",
        "cold_cache_contract": {
            "stage2_restore": False,
            "p17_restore": False,
            "mc_restore": False,
            "cache_persist": False,
        },
        "stage_wall_seconds": stage_wall,
        "categories": categories,
        "global_top_functions": rows[:50],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# V12 Controlled Cold Profile",
        "",
        "This artifact is measurement-only. V6 is read-only and no compute cache "
        "is restored or persisted for this run.",
        "",
        "## Stage wall-clock",
        "",
        "| Stage | Status | Seconds |",
        "|---|---:|---:|",
    ]
    for name, row in sorted(
        (summary.get("stage_wall_seconds") or {}).items(),
        key=lambda item: -float((item[1] or {}).get("elapsed_seconds") or 0.0),
    ):
        lines.append(
            f"| {name} | {row.get('status')} | "
            f"{float(row.get('elapsed_seconds') or 0.0):.6f} |"
        )

    for category, payload in (summary.get("categories") or {}).items():
        lines.extend(
            [
                "",
                f"## {category}",
                "",
                "| Function | File | Internal s | Cumulative s | Calls |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for row in (payload.get("top_functions") or [])[:20]:
            file_name = Path(str(row.get("file") or "")).name
            lines.append(
                f"| {row.get('function')} | {file_name}:{row.get('line')} | "
                f"{float(row.get('internal_seconds') or 0.0):.6f} | "
                f"{float(row.get('cumulative_seconds') or 0.0):.6f} | "
                f"{int(row.get('total_calls') or 0)} |"
            )
        lines.extend(
            [
                "",
                "_Cumulative time is inclusive; nested cumulative rows must not "
                "be added together._",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pstats", required=True)
    parser.add_argument("--log", required=False)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    pstats_path = Path(args.pstats)
    if not pstats_path.exists():
        raise SystemExit(f"missing profiler output: {pstats_path}")
    log_path = Path(args.log) if args.log else None
    summary = build_summary(pstats_path, log_path)
    Path(args.output_json).write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    Path(args.output_md).write_text(
        render_markdown(summary),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
