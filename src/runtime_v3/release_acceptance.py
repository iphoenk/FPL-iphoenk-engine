from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass

from src.utils import DATA, read_json


@dataclass(frozen=True)
class Gate:
    name: str
    command: tuple[str, ...]


def integration_gates() -> tuple[Gate, ...]:
    py = sys.executable
    runtime = "src.runtime_v3.domain_orchestrator"
    return (
        Gate("full_runtime", (py, "-m", runtime, "--mode", "daily", "--stats", "--profile", "full_refresh")),
        Gate("source_contract", (py, "-m", "src.engines.source_contract_validate")),
        Gate("production_contract", (py, "-m", "src.engines.production_contract_validate")),
        Gate("watchlist_contract", (py, "-m", "src.engines.watchlist_contract_validate")),
        Gate("report_serving_contract", (py, "-m", "src.engines.report_serving_validate")),
        Gate("report_time_contract", (py, "-m", "src.engines.report_time_contract_validate")),
        Gate("full_resource_guard", (py, "-m", "src.runtime_v3.performance_guard", "--profile", "full_refresh")),
        Gate("fast_cold_warmup", (py, "-m", runtime, "--mode", "daily", "--stats", "--profile", "fast_decision")),
        Gate("fast_runtime", (py, "-m", runtime, "--mode", "daily", "--stats", "--profile", "fast_decision")),
        Gate("fast_slo_guard", (py, "-m", "src.runtime_v3.performance_guard", "--profile", "fast_decision")),
        Gate("material_equivalence", (py, "-m", "src.runtime_v3.equivalence_acceptance")),
        Gate("definition_of_done", (py, "-m", "src.runtime_v3.definition_of_done", "--scope", "candidate")),
    )


def _runtime_breakdown() -> dict:
    payload = read_json(DATA / "runtime_performance.json", {})
    services = payload.get("services") if isinstance(payload, dict) else {}
    if not isinstance(services, dict):
        return {}
    return {
        name: {
            "status": row.get("status"),
            "elapsed_ms": row.get("elapsed_ms"),
            "reuse_mode": row.get("reuse_mode"),
            "batched": row.get("single_process_module_batch") is True,
            "commands_ms": [command.get("elapsed_ms") for command in row.get("commands") or []],
        }
        for name, row in services.items()
    }


def run() -> dict:
    results = []
    started = time.perf_counter()
    runtime_gates = {"full_runtime", "fast_cold_warmup", "fast_runtime"}
    for gate in integration_gates():
        gate_start = time.perf_counter()
        proc = subprocess.run(gate.command, check=False)
        elapsed = round((time.perf_counter() - gate_start) * 1000.0, 3)
        row = {"gate": gate.name, "returncode": proc.returncode, "elapsed_ms": elapsed}
        if gate.name in runtime_gates:
            row["service_breakdown"] = _runtime_breakdown()
        results.append(row)
        if proc.returncode != 0:
            result = {"status": "FAIL", "failed_gate": gate.name, "gates": results, "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3)}
            print(json.dumps(result, ensure_ascii=False))
            raise SystemExit(proc.returncode or 1)
    result = {
        "status": "PASS",
        "failed_gate": None,
        "gates": results,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "policy": {
            "underlying_checks_preserved": True,
            "fail_closed_on_first_failed_gate": True,
            "full_and_fast_profiles_both_required": True,
            "cold_then_warm_fast_required": True,
            "seven_domain_runtime_required": True,
            "same_input_material_equivalence_required": True,
            "definition_of_done_candidate_required": True,
            "per_capability_timing_is_release_observable": True,
        },
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Composite V3 release integration acceptance gate")
    parser.parse_args()
    run()


if __name__ == "__main__":
    main()
