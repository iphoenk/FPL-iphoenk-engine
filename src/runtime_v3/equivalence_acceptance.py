from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from src.utils import DATA, ROOT


def _read(data_dir: Path, name: str) -> dict[str, Any]:
    return json.loads((data_dir / name).read_text(encoding="utf-8"))


def _element(row: Any) -> Any:
    return row.get("element") if isinstance(row, dict) else None


def _lineup_signature(data_dir: Path) -> dict[str, Any]:
    row = _read(data_dir, "lineup_decision.json")
    bench = row.get("bench") or {}
    return {
        "formation": row.get("formation"),
        "starting_xi": [_element(item) for item in row.get("starting_xi") or []],
        "bench_gk": _element(bench.get("gk")),
        "bench_order": [_element(item) for item in bench.get("order") or []],
        "captain": _element(row.get("captain")),
        "vice_captain": _element(row.get("vice_captain")),
    }


def _watchlist_signature(data_dir: Path) -> dict[str, list[Any]]:
    row = _read(data_dir, "dss_watchlist.json")
    return {
        str(position): [_element(item) for item in rows or []]
        for position, rows in (row.get("positions") or {}).items()
    }


def _package_signature(data_dir: Path) -> dict[str, Any]:
    row = _read(data_dir, "package_decision.json")
    selected = row.get("selected_package") or {}
    return {
        "selected_package_id": row.get("selected_package_id"),
        "selected_outs": list(selected.get("outs") or []),
        "selected_ins": list(selected.get("ins") or []),
        "current_squad_legal": row.get("current_squad_legal"),
        "gate0_revalidated": row.get("gate0_revalidated"),
    }


def _report_signature(data_dir: Path) -> dict[str, Any]:
    row = _read(data_dir, "user_report.json")
    captaincy = row.get("captaincy") or {}
    current_team = row.get("current_team") or {}
    return {
        "decision": row.get("decision"),
        "report_mode": row.get("report_mode"),
        "owned_count": (row.get("owned_squad") or {}).get("count"),
        "watchlist_status": (row.get("external_watchlist") or {}).get("status"),
        "captain": captaincy.get("captain"),
        "vice": captaincy.get("vice"),
        "current_formation": current_team.get("formation"),
        "current_bench_order": current_team.get("bench_order"),
    }


def _framework_signature(data_dir: Path) -> dict[str, Any]:
    row = _read(data_dir, "framework_health.json")
    return {
        "overall": row.get("overall"),
        "decision_engine": row.get("decision_engine"),
        "recommendation_allowed": row.get("recommendation_allowed"),
        "go_allowed": row.get("go_allowed"),
        "gate0": (row.get("gate0") or {}).get("counts"),
        "dss_core": (row.get("dss_core") or {}).get("counts"),
        "dss_extensions": (row.get("dss_extensions") or {}).get("counts"),
        "enhancements": (row.get("enhancements") or {}).get("counts"),
    }


def _phase_signature(data_dir: Path) -> dict[str, Any]:
    row = _read(data_dir, "latest.json")
    phase = row.get("phase") or {}
    return {
        "current_gw": phase.get("current_gw"),
        "planning_gw": phase.get("planning_gw"),
        "submitted_gw": phase.get("submitted_gw"),
        "scoring_gw": phase.get("scoring_gw"),
        "deadline_time": phase.get("deadline_time"),
    }


def material_signature(data_dir: Path) -> dict[str, Any]:
    return {
        "phase": _phase_signature(data_dir),
        "lineup": _lineup_signature(data_dir),
        "watchlist": _watchlist_signature(data_dir),
        "package": _package_signature(data_dir),
        "report": _report_signature(data_dir),
        "framework": _framework_signature(data_dir),
    }


def _copy_seed(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)


def _run(module: str, data_dir: Path, cache_root: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["FPL_DATA_DIR"] = str(data_dir)
    env["FPL_RUNTIME_CACHE_DIR"] = str(cache_root)
    env["FPL_AUTH_MODE"] = "disabled"
    command = [
        sys.executable,
        "-m",
        module,
        "--mode",
        "daily",
        "--stats",
        "--profile",
        "fast_decision",
    ]
    proc = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    result = {
        "module": module,
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }
    if proc.returncode != 0:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="fpl-v3-equivalence-") as tmp:
        root = Path(tmp)
        legacy_data = root / "legacy"
        domain_data = root / "domain"
        shared_cache = root / "cache"
        _copy_seed(DATA, legacy_data)
        _copy_seed(DATA, domain_data)

        legacy_run = _run("src.runtime_v3.orchestrator", legacy_data, shared_cache)
        domain_run = _run("src.runtime_v3.domain_orchestrator", domain_data, shared_cache)
        legacy_signature = material_signature(legacy_data)
        domain_signature = material_signature(domain_data)

        if legacy_signature != domain_signature:
            differences = {
                key: {"legacy": legacy_signature.get(key), "domain": domain_signature.get(key)}
                for key in legacy_signature
                if legacy_signature.get(key) != domain_signature.get(key)
            }
            result = {
                "status": "FAIL",
                "contract": "V3_MATERIAL_DECISION_EQUIVALENCE_V1",
                "differences": differences,
                "legacy_run": legacy_run,
                "domain_run": domain_run,
            }
            print(json.dumps(result, ensure_ascii=False))
            raise SystemExit(1)

        result = {
            "status": "PASS",
            "contract": "V3_MATERIAL_DECISION_EQUIVALENCE_V1",
            "same_input_seed": True,
            "shared_official_cache": True,
            "compared": list(legacy_signature),
            "signature": domain_signature,
        }
        print(json.dumps(result, ensure_ascii=False))
        return result


def main() -> None:
    run()


if __name__ == "__main__":
    main()
