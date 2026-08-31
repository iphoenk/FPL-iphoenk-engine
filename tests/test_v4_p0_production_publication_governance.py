from __future__ import annotations

import json
from pathlib import Path

from src.utils import CONFIG


def test_publication_integrity_is_canonical_governance_output():
    services = json.loads((CONFIG / "service_registry.json").read_text(encoding="utf-8"))
    contracts = json.loads((CONFIG / "service_contract_registry.json").read_text(encoding="utf-8"))
    manifest = json.loads((CONFIG / "release_manifest.json").read_text(encoding="utf-8"))

    governance = next(row for row in services["services"] if row["id"] == "governance")
    assert "publication_integrity" in governance["produces"]

    publication = contracts["contracts"]["publication_integrity"]
    assert publication["path"] == "data/publication_integrity_v4.json"
    assert publication["equals"]["status"] == "PASS"
    assert publication["equals"]["factual_gate_pass"] is True
    assert publication["equals"]["capabilities.reporting"] == "PASS"
    assert publication["equals"]["capabilities.serving"] == "PASS"

    assert manifest["registries"]["services"] == services["registry"]
    assert manifest["registries"]["contracts"] == contracts["registry"]


def test_blocked_publication_cannot_leave_visible_production_health_green():
    source = (Path(__file__).resolve().parents[1] / "src/services/governance_service.py").read_text(encoding="utf-8")
    assert 'integrity.get("status") == "BLOCKED"' in source
    assert 'maturity["production_health"] = "RED"' in source
    assert 'operational["operationally_ready"] = False' in source
    assert '"PUBLICATION_INTEGRITY_BLOCKED"' in source
    assert 'atomic_json(DATA / "framework_health_v4.json", maturity)' in source
