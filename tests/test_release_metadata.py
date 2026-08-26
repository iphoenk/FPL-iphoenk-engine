import json
from pathlib import Path

from live_service import app
from src.engine import ENGINE_VERSION as ENGINE_RUNTIME_VERSION
from src.engine import SCHEMA_VERSION as ENGINE_RUNTIME_SCHEMA
from src.version import ENGINE_VERSION, SCHEMA_VERSION, SERVICE_TITLE

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_single_source_of_truth():
    assert ENGINE_VERSION == "3.18.0"
    assert SCHEMA_VERSION == 47
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

    assert implementation["version"] == ENGINE_VERSION
    assert implementation["schema_version"] == SCHEMA_VERSION
    assert implementation["release_metadata_source"] == "src/version.py"
    assert engine_config["schema_version"] == SCHEMA_VERSION
    assert readme[0] == f"# FPL iphoenk Engine v{ENGINE_VERSION}"
    assert workflow[0] == f"name: FPL iphoenk collector v{ENGINE_VERSION} microservices"


def test_master_task_governance_is_wired():
    master_path = ROOT / "MASTER_TASK_LIST_V3.md"
    assert master_path.exists()
    master = master_path.read_text()
    readme = (ROOT / "README.md").read_text()
    assert "# FPL iphoenk Engine V3 Master Task List" in master
    assert "V3.18 Structured Challenger Ingestion" in master
    assert "V3.18.0" in master
    assert "Definition of Done" in master
    assert "MASTER_TASK_LIST_V3.md" in readme
