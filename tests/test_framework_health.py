from __future__ import annotations

from src.engines.framework_health_audit import EXPECTED_COUNTS, REGISTRIES, _gate0, _registry_integrity
from src.utils import read_json


def test_canonical_registry_counts_and_unique_ids():
    for name, expected in EXPECTED_COUNTS.items():
        obj = read_json(REGISTRIES[name], {})
        result = _registry_integrity(name, obj)
        assert result["declared"] == expected
        assert result["integrity_ok"] is True
        assert result["duplicate_ids"] == []


def test_dss_core_numbering_is_immutable_01_to_50():
    obj = read_json(REGISTRIES["dss_core"], {})
    ids = [row["id"] for row in obj["modules"]]
    assert ids == [f"DSS-{i:02d}" for i in range(1, 51)]


def test_enhancement_numbering_is_exactly_eight():
    obj = read_json(REGISTRIES["enhancements"], {})
    ids = [row["id"] for row in obj["layers"]]
    assert ids == [f"ENH-{i:02d}" for i in range(1, 9)]


def test_gate0_preflight_is_fail_closed_but_phase_aware():
    result = _gate0("preflight")
    assert result["counts"].get("FAIL", 0) == 0
    assert result["counts"].get("DEFERRED", 0) >= 1
    assert result["pass"] is True


def test_every_framework_item_declares_criticality_and_probe_for_intelligence_layers():
    for group in ("dss_core", "dss_extensions", "enhancements"):
        obj = read_json(REGISTRIES[group], {})
        key = "layers" if group == "enhancements" else "modules"
        for row in obj[key]:
            assert isinstance(row.get("critical"), bool)
            assert row.get("operational_probe"), row["id"]
