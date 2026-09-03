from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "config/service_registry.json"
services = json.loads(path.read_text(encoding="utf-8"))

# Distributed package precompute is a capability-specific execution topology.
# It must not redefine the established global service-DAG execution contract.
services["execution_model"] = "process_isolated_dag_parallel_single_host"
services["distributed_precompute"] = {
    "package_optimization": {
        "execution_registry": "v4_package_optimization_execution_v1",
        "authority": "config/package_optimization_execution_registry.json",
        "scope": "PACKAGE_OPTIMIZATION_PRECOMPUTE_ONLY",
    }
}
path.write_text(json.dumps(services, indent=2) + "\n", encoding="utf-8")
print("global service DAG contract preserved; package distributed topology scoped to its execution registry")
