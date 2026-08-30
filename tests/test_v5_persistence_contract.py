from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.v5 import persistence as v5p

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


def test_history_is_bounded_and_explicitly_noncanonical() -> None:
    persistence = _load("config/v5_persistence_registry.json")
    retention = ((persistence.get("write_policy") or {}).get("history_retention") or {})
    storage = persistence.get("evidence_storage") or {}

    assert retention.get("canonical_evidence") is False
    assert 0 < int(retention.get("max_age_days") or 0) <= 14
    assert 0 < int(retention.get("max_records") or 0) <= 128
    assert 0 < int(retention.get("max_bytes") or 0) <= 32 * 1024 * 1024
    assert storage.get("history_jsonl_is_canonical") is False
    assert storage.get("canonical_prediction_ledger") == "prediction_ledger.json"
    assert storage.get("canonical_prediction_ledger_retention") == "CURRENT_2026_27_SEASON"


def test_history_compaction_keeps_recent_bounded_tail(tmp_path: Path) -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "history.jsonl"
    rows = [
        {"id": "old", "generated_at": (now - timedelta(days=30)).isoformat(), "payload": "old"},
        *[
            {"id": idx, "generated_at": (now - timedelta(minutes=idx)).isoformat(), "payload": "x" * 32}
            for idx in range(140)
        ],
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    result = v5p._compact_history(path, now=now)
    retained = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert result["before_records"] == 141
    assert result["after_records"] == 128
    assert len(retained) == 128
    assert all(row["id"] != "old" for row in retained)
    assert retained[-1]["id"] == 139
    assert result["after_bytes"] <= 32 * 1024 * 1024
