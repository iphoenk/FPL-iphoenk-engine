import json
from pathlib import Path

from live_service import app
from src.engine import ENGINE_VERSION as ENGINE_RUNTIME_VERSION
from src.engine import SCHEMA_VERSION as ENGINE_RUNTIME_SCHEMA
from src.version import ENGINE_VERSION, SCHEMA_VERSION, SERVICE_TITLE

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_single_source_of_truth():
    assert ENGINE_VERSION == "3.22.0"
    assert SCHEMA_VERSION == 49
    assert ENGINE_RUNTIME_VERSION == ENGINE_VERSION
    assert ENGINE_RUNTIME_SCHEMA == SCHEMA_VERSION
    assert app.version == ENGINE_VERSION
    assert app.title == SERVICE_TITLE
    assert SERVICE_TITLE == f"FPL iphoenk Engine v{ENGINE_VERSION}"


def test_release_metadata_surfaces_are_consistent():
    implementation = json.loads((ROOT / "IMPLEMENTATION_STATUS.json").read_text())
    engine_config = json.loads((ROOT / "config" / "engine.json").read_text())
    readme = (ROOT / "README.md").read_text().splitlines()
    workflow = (ROOT / ".github" / "workflows" / "fpl-engine.yml").read_text().splitlines()
    reporting = json.loads((ROOT / "config" / "intelligence" / "reporting.json").read_text())
    artifact_registry = json.loads((ROOT / "config" / "report_artifact_registry.json").read_text())
    service_registry = json.loads((ROOT / "config" / "v3_service_registry.json").read_text())
    source_registry = json.loads((ROOT / "config" / "sources" / "registry.json").read_text())
    runtime_artifact_registry = json.loads((ROOT / "config" / "runtime" / "artifact_contracts.json").read_text())

    assert implementation["version"] == ENGINE_VERSION
    assert implementation["schema_version"] == SCHEMA_VERSION
    assert implementation["release_metadata_source"] == "src/version.py"
    assert engine_config["schema_version"] == SCHEMA_VERSION
    assert readme[0] == f"# FPL iphoenk Engine v{ENGINE_VERSION}"
    assert workflow[0] == f"name: FPL iphoenk collector v{ENGINE_VERSION} microservices"
    assert reporting["model_id"] == "decision_first_report_v2"
    assert artifact_registry["registry"] == "REPORT_ARTIFACT_REGISTRY_V3"
    assert artifact_registry["consumer_contract"]["report_time_intelligence_required"] is True
    assert artifact_registry["consumer_contract"]["owned_rows_require_current_gw_xpts"] is True
    assert artifact_registry["consumer_contract"]["weather_context_required"] is True
    assert service_registry["schema_version"] == 14
    assert service_registry["production_contract"].startswith("v3.22-")
    assert len(service_registry["services"]) == 20
    assert source_registry["registry"] == "SOURCE_REGISTRY_V4"
    assert runtime_artifact_registry["registry"] == "RUNTIME_ARTIFACT_CONTRACTS_V2"


def test_master_task_governance_is_wired():
    master_path = ROOT / "MASTER_TASK_LIST_V3.md"
    assert master_path.exists()
    master = master_path.read_text()
    readme = (ROOT / "README.md").read_text()
    assert "# FPL iphoenk Engine V3 Master Task List" in master
    assert "V3.20 Architecture Hardening" in master
    assert "V3.20.1 Correctness Hardening" in master
    assert "V3.20.2 Artifact Contract Hardening" in master
    assert "V3.21 Weather Intelligence + Report Transparency" in master
    assert "V3.22 Runtime Optimization Foundation" in master

    candidate = f"Current release candidate: V{ENGINE_VERSION}" in master
    production = f"Current production release: V{ENGINE_VERSION}" in master
    assert candidate != production, "roadmap must identify exactly one current release state"
    if candidate:
        assert f"Current candidate schema: {SCHEMA_VERSION}" in master
    else:
        assert f"Current production schema: {SCHEMA_VERSION}" in master
        assert "Production acceptance: COMPLETE" in master

    assert "Definition of Done" in master
    assert "MASTER_TASK_LIST_V3.md" in readme
