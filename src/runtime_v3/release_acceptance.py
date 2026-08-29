from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass


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
    )


def run() -> dict:
    results = []
    started = time.perf_counter()
    for gate in integration_gates():
        gate_start = time.perf_counter()
        proc = subprocess.run(gate.command, check=False)
        elapsed = round((time.perf_counter() - gate_start) * 1000.0, 3)
        results.append({"gate": gate.name, "returncode": proc.returncode, "elapsed_ms": elapsed})
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
