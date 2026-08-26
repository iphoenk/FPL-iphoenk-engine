from __future__ import annotations

import json

from src.engines import framework_health_audit as audit_engine


def activate_registry_contract() -> dict[str, int]:
    expected: dict[str, int] = {}
    for name, path in audit_engine.REGISTRIES.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload.get("expected_count")
        if value is None:
            raise RuntimeError(f"registry {name} missing expected_count")
        count = int(value)
        if count <= 0:
            raise RuntimeError(f"registry {name} expected_count must be positive")
        expected[name] = count
    audit_engine.EXPECTED_COUNTS = expected
    return expected


def run() -> None:
    activate_registry_contract()
    audit_engine.run()


if __name__ == "__main__":
    run()
