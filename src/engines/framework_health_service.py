from __future__ import annotations

import json

from src.engines import framework_health_audit as audit_engine


def activate_registry_contract() -> dict[str, int]:
    """Make registry-declared counts authoritative for the legacy audit core."""
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
    # Compatibility injection only. Active production truth is the registry.
    audit_engine.EXPECTED_COUNTS = expected
    return expected


def _publish_gate0_registry_contract(expected: dict[str, int]) -> None:
    """Expose Gate0 expected/declared metadata consistently with DSS groups."""
    registry = json.loads(audit_engine.REGISTRIES["gate0"].read_text(encoding="utf-8"))
    declared = len(registry.get("checks") or [])
    expected_count = int(expected["gate0"])
    for path in (audit_engine.PRE_OUT, audit_engine.OUT):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        gate0 = dict(payload.get("gate0") or {})
        gate0["expected"] = expected_count
        gate0["declared"] = declared
        payload["gate0"] = gate0
        audit_engine.atomic_json(path, payload)


def run() -> None:
    expected = activate_registry_contract()
    audit_engine.run()
    _publish_gate0_registry_contract(expected)


if __name__ == "__main__":
    run()
