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

STAGE_CATEGORY = {
    "V12_ANALYTICS_FOUNDATION": "FOUNDATION",
    "P1_1_P1_3_FULL_UNIVERSE": "STAGE2",
    "P1_2B_PACKAGE_COMBINE": "PACKAGE_COMBINE",
    "P1_4_MONTE_CARLO": "MONTE_CARLO",
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


def _profile_rows(pstats_path: Path) -> list[dict[str, Any]]:
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
    return rows


def _stage_wall(log_path: Path | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not log_path or not log_path.exists():
        return out
    for match in STAGE_PATTERN.finditer(
        log_path.read_text(encoding="utf-8", errors="replace")
    ):
        out[match.group("name")] = {
            "status": match.group("status"),
            "elapsed_seconds": float(match.group("seconds")),
        }
    return out


def _entrypoints(
    rows: list[dict[str, Any]],
    category: str,
) -> list[dict[str, Any]]:
    names = ENTRYPOINTS.get(category, ())
    return [row for row in rows if str(row["function"]) in names]


def build_summary(pstats_path: Path, log_path: Path | None) -> dict[str, Any]:
    """Backward-compatible single-profile summary."""
    rows = _profile_rows(pstats_path)
    categories: dict[str, Any] = {}
    for category, names in ENTRYPOINTS.items():
        categories[category] = {
            "entrypoints": [
                row for row in rows if str(row["function"]) in names
            ],
            "top_functions": rows[:30],
            "note": (
                "single-process cumulative_seconds is inclusive and must not "
                "be summed across nested functions"
            ),
        }
    return {
        "schema_version": 2,
        "profiler": "cProfile",
        "profile_scope": "SINGLE_PROCESS",
        "cold_cache_contract": {
            "stage2_restore": False,
            "p17_restore": False,
            "mc_restore": False,
            "cache_persist": False,
        },
        "stage_wall_seconds": _stage_wall(log_path),
        "categories": categories,
        "global_top_functions": rows[:50],
    }


def build_stage_directory_summary(
    profile_dir: Path,
    log_path: Path | None,
) -> dict[str, Any]:
    stage_wall = _stage_wall(log_path)
    stage_profiles: dict[str, Any] = {}
    for stage, category in STAGE_CATEGORY.items():
        path = profile_dir / f"{stage}.pstats"
        if not path.exists():
            stage_profiles[stage] = {
                "status": "MISSING",
                "category": category,
                "profile_path": str(path),
                "entrypoints": [],
                "top_functions": [],
            }
            continue
        rows = _profile_rows(path)
        stage_profiles[stage] = {
            "status": "AVAILABLE",
            "category": category,
            "profile_path": str(path),
            "entrypoints": _entrypoints(rows, category),
            "top_functions": rows[:40],
            "note": (
                "cumulative_seconds is inclusive within this stage and must "
                "not be summed across nested functions"
            ),
        }

    return {
        "schema_version": 2,
        "profiler": "cProfile",
        "profile_scope": "STAGE_LOCAL_PARENT_PROCESS",
        "profiled_stages": list(STAGE_CATEGORY),
        "cold_cache_contract": {
            "stage2_restore": False,
            "p17_restore": False,
            "mc_restore": False,
            "cache_persist": False,
        },
        "stage_wall_seconds": stage_wall,
        "stage_profiles": stage_profiles,
        "limitations": {
            "multiprocessing_child_functions_profiled": False,
            "parent_entrypoint_wait_time_included": True,
            "production_latency_gate_uses_stage_wall_seconds": True,
            "profile_cumulative_times_are_diagnostic_only": True,
        },
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

    stage_profiles = summary.get("stage_profiles") or {}
    if stage_profiles:
        for stage, payload in stage_profiles.items():
            lines.extend(
                [
                    "",
                    f"## {stage} / {payload.get('category')}",
                    "",
                    f"Profile status: **{payload.get('status')}**",
                    "",
                    "| Function | File | Internal s | Cumulative s | Calls |",
                    "|---|---|---:|---:|---:|",
                ]
            )
            for row in (payload.get("top_functions") or [])[:25]:
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
                    "_Cumulative time is inclusive. Child-process internals are "
                    "not captured by parent cProfile._",
                ]
            )
    else:
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
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pstats")
    source.add_argument("--profile-dir")
    parser.add_argument("--log", required=False)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    log_path = Path(args.log) if args.log else None
    if args.profile_dir:
        profile_dir = Path(args.profile_dir)
        if not profile_dir.exists():
            raise SystemExit(f"missing profile directory: {profile_dir}")
        summary = build_stage_directory_summary(profile_dir, log_path)
    else:
        pstats_path = Path(args.pstats)
        if not pstats_path.exists():
            raise SystemExit(f"missing profiler output: {pstats_path}")
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
