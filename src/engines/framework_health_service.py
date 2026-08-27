from __future__ import annotations

import json

from src.engines import framework_health_audit as audit_engine
from src.settings import NORMAL_STALE_MINUTES


def activate_registry_contract() -> dict[str, int]:
    """Make registry-declared counts authoritative for the compatibility audit core."""
    expected: dict[str, int] = {}
    for name, path in audit_engine.REGISTRIES.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload.get("expected_count")
        if value is None:
            raise RuntimeError(f"registry {name} missing expected_count")
        count = int(value)
        if count <= 0:
            raise RuntimeError(f"registry {name} expected_count must be positive")
        rows_key = "modules" if name in {"dss_core", "dss_extensions"} else "layers" if name == "enhancements" else "checks"
        declared = len(payload.get(rows_key) or [])
        if declared != count:
            raise RuntimeError(f"registry {name} declared {declared} rows but expected_count={count}")
        expected[name] = count
    # framework_health_audit retains old literals only as an inactive compatibility fallback.
    # The active service always injects registry truth before invoking the audit core.
    audit_engine.EXPECTED_COUNTS = expected
    return expected


def activate_freshness_contract() -> int:
    """Make engine-config freshness the active default used by the compatibility audit core."""
    configured = int(NORMAL_STALE_MINUTES)
    original = audit_engine._probe_freshness

    def configured_probe(max_age_minutes: int | None = None):
        return original(configured if max_age_minutes is None else int(max_age_minutes))

    audit_engine._probe_freshness = configured_probe
    return configured


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
    activate_freshness_contract()
    audit_engine.run()
    _publish_gate0_registry_contract(expected)


if __name__ == "__main__":
    run()
