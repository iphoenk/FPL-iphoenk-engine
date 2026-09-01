from __future__ import annotations

import importlib
import json
from pathlib import Path

from src.engines import v4_quality_gate, v4_quality_gate_legacy
from src.services import governance_live_overlay, hot_orchestrator
from src.services.contracts import file_digest

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_quality_gate_does_not_mutate_legacy_assertion_globals() -> None:
    before = (
        v4_quality_gate_legacy._assert_framework_health,
        v4_quality_gate_legacy._assert_orchestration,
        v4_quality_gate_legacy._assert_prediction_and_validation,
    )
    importlib.reload(v4_quality_gate)
    after = (
        v4_quality_gate_legacy._assert_framework_health,
        v4_quality_gate_legacy._assert_orchestration,
        v4_quality_gate_legacy._assert_prediction_and_validation,
    )
    assert after == before
    assert all(func.__module__ == "src.engines.v4_quality_gate_core" for func in after)


def test_hot_path_service_identity_is_bound_to_authoritative_registry() -> None:
    rows = hot_orchestrator._assert_registry_module_parity()
    assert len(rows) == 8
    assert rows["prediction"]["module"] == "src.services.prediction_service_price_mover"
    assert rows["personal_gw_scorecard"]["module"] == "src.services.gw_scorecard_live_overlay"
    assert rows["governance"]["module"] == "src.services.governance_live_overlay"
    assert hot_orchestrator.HOT_PRODUCTION_MODULES == {
        service_id: row["module"] for service_id, row in rows.items()
    }


def test_final_publication_integrity_hashes_post_overlay_content(monkeypatch, tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint_decision_v4.json"
    serving = tmp_path / "serving_payload_v4.json"
    integrity_path = tmp_path / "publication_integrity_v4.json"
    checkpoint.write_text(json.dumps({"checkpoint": "post-overlay"}), encoding="utf-8")
    serving.write_text(json.dumps({"serving": "post-overlay"}), encoding="utf-8")
    integrity_path.write_text(json.dumps({"status": "PASS", "contract": "test"}), encoding="utf-8")

    monkeypatch.setattr(governance_live_overlay, "CHECKPOINT", checkpoint)
    monkeypatch.setattr(governance_live_overlay, "SERVING", serving)
    monkeypatch.setattr(governance_live_overlay, "PUBLICATION_INTEGRITY", integrity_path)

    result = governance_live_overlay._finalize_publication_integrity({"status": "IDLE"})
    assert result["post_overlay_verification"]["status"] == "PASS"
    assert result["post_overlay_verification"]["checked_content_is_published_content"] is True
    assert result["final_artifacts"]["checkpoint_decision_v4"]["sha256"] == file_digest(checkpoint)
    assert result["final_artifacts"]["serving_payload_v4"]["sha256"] == file_digest(serving)

    stored = json.loads(integrity_path.read_text(encoding="utf-8"))
    assert stored["final_artifacts"] == result["final_artifacts"]

    serving.write_text(json.dumps({"serving": "tampered-after-attestation"}), encoding="utf-8")
    assert stored["final_artifacts"]["serving_payload_v4"]["sha256"] != file_digest(serving)


def test_workflow_callers_use_read_only_repository_token() -> None:
    for relative in (
        ".github/workflows/fpl-engine.yml",
        ".github/workflows/fpl-engine-recovery.yml",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "contents: write" not in text, relative
        assert text.count("contents: read") >= 2, relative
