from __future__ import annotations

import argparse
import json
import runpy
import sys
from typing import Any

from src.utils import ROOT

REGISTRY_PATH = ROOT / "config" / "runtime" / "module_batches.json"


def _registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_MODULE_BATCHES_V1":
        raise RuntimeError("unexpected module batch registry")
    return payload


def _expand_args(args: list[Any], context: dict[str, str]) -> list[str]:
    out: list[str] = []
    for value in args:
        expanded = str(value)
        for key, replacement in context.items():
            expanded = expanded.replace("{" + key + "}", replacement)
        if expanded:
            out.append(expanded)
    return out


def run_batch(name: str, context: dict[str, str] | None = None) -> dict[str, Any]:
    context = dict(context or {})
    batches = _registry().get("batches") or {}
    rows = batches.get(name)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"unknown or empty module batch: {name}")

    executed: list[dict[str, Any]] = []
    original_argv = list(sys.argv)
    try:
        for row in rows:
            module = str(row.get("module") or "").strip()
            if not module:
                raise RuntimeError(f"batch {name} contains module-less entry")
            args = _expand_args(list(row.get("args") or []), context)
            sys.argv = [module, *args]
            try:
                runpy.run_module(module, run_name="__main__", alter_sys=False)
                rc = 0
            except SystemExit as exc:
                code = exc.code
                rc = int(code) if isinstance(code, int) else (0 if code in {None, ""} else 1)
            executed.append({"module": module, "args": args, "returncode": rc})
            if rc != 0:
                raise RuntimeError(f"batch {name} module {module} exited {rc}")
    finally:
        sys.argv = original_argv

    return {"batch": name, "executed": executed, "count": len(executed)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--mode", default="daily")
    parser.add_argument("--stats", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--deep-stats", action="store_true")
    args = parser.parse_args()
    out = run_batch(args.batch, {
        "mode": args.mode,
        "stats": "--stats" if args.stats else "--no-stats",
        "deep_stats": "--deep-stats" if args.deep_stats else "",
    })
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
