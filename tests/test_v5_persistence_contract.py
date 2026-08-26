from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_orchestrator_artifacts_are_registered_for_persistence() -> None:
    orchestrator = _load("config/v5_orchestrator_registry.json")
    persistence = _load("config/v5_persistence_registry.json")

    mapped = set((orchestrator.get("artifact_mapping") or {}).values())
    registered = set((persistence.get("artifacts") or {}).keys())
    missing = sorted(mapped - registered)

    assert not missing, f"orchestrator artifact(s) missing from persistence registry: {missing}"


def test_persistence_artifact_files_are_unique() -> None:
    persistence = _load("config/v5_persistence_registry.json")
    artifacts = persistence.get("artifacts") or {}
    filenames = list(artifacts.values())

    assert len(filenames) == len(set(filenames)), "multiple artifact authorities target the same persistence file"


def test_source_fusion_has_persistent_authority() -> None:
    orchestrator = _load("config/v5_orchestrator_registry.json")
    persistence = _load("config/v5_persistence_registry.json")

    assert (orchestrator.get("artifact_mapping") or {}).get("source_fusion") == "source_fusion"
    assert (persistence.get("artifacts") or {}).get("source_fusion") == "source_fusion.json"
