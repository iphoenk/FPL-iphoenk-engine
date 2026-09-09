from __future__ import annotations

import argparse
import json
import resource
import subprocess
import time
from pathlib import Path

from src.utils import atomic_json


def run(command: list[str], output: Path) -> int:
    if not command:
        raise RuntimeError("measured command requires a child command")
    started = time.perf_counter()
    completed = subprocess.run(command, check=False)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    payload = {
        "schema_version": 1,
        "registry": "V3_PROCESS_RESOURCE_MEASUREMENT_V1",
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "peak_rss_kb": int(usage.ru_maxrss),
        "exit_code": int(completed.returncode),
        "command_module": command[2] if len(command) >= 3 and command[0].endswith("python") and command[1] == "-m" else command[0],
    }
    atomic_json(output, payload, compact=True)
    print(json.dumps(payload, ensure_ascii=False))
    return int(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure one bounded V3 child command without changing its semantics")
    parser.add_argument("--output", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    return run(command, Path(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
