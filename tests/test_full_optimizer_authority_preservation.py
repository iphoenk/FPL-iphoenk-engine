from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.runtime_v3 import full_authority_cache, incremental_reuse, publish_snapshot

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _valid_full_chain(data_dir: Path) -> None:
    _write(data_dir / "package_optimizer.json", {
        "generated_at": "2026-09-03T10:00:00+00:00",
        "planning_gw": 3,
        "ruleset_id": "FPL_2026_27",
        "status": "READY",
        "hold": {"id": "HOLD"},
        "packages": [],
        "search_diagnostics": {
            "search_authority": "FULL",
            "lossy_pruning": False,
            "candidate_pruning_applied": False,
            "single_budget_applied": False,
            "pair_budget_applied": False,
            "exact_package_limit_applied": False,
            "all_step_legal_packages_scored": True,
            "watchlist_used_as_optimizer_input": False,
        },
    })
    _write(data_dir / "package_decision.json", {
        "selected_package_id": "HOLD",
        "current_squad_legal": True,
        "gate0_revalidated": True,
    })
    _write(data_dir / "framework_health.json", {
        "overall": "GREEN",
        "decision_engine": "HEALTHY",
        "gate0": {"pass": True, "counts": {"PASS": 16}},
    })
    _write(data_dir / "team.json", {
        "squad": [{"element": element} for element in range(1, 16)],
    })
    positions = {}
    next_element = 100
    for position in ("GK", "DEF", "MID", "FWD"):
        positions[position] = [{"element": next_element + offset} for offset in range(5)]
        next_element += 10
    _write(data_dir / "dss_watchlist.json", {"status": "READY", "positions": positions})
    _write(data_dir / "latest.json", {
        "decision_intelligence": {
            "package_optimizer_search_authority": "FULL",
            "package_optimizer_execution_profile": "exhaustive_precompute",
        },
        "package_decision_summary": {
            "selected_package_id": "HOLD",
            "gate0_revalidated": True,
        },
    })


def _patch_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(full_authority_cache, "DATA", tmp_path)
    monkeypatch.setattr(incremental_reuse, "STATE_PATH", tmp_path / "incremental_reuse_state.json")


def test_prediction_fingerprint_includes_optimizer_config():
    prediction = _json("config/runtime/incremental_reuse.json")["services"]["prediction"]
    assert "config/intelligence/package_optimizer.json" in prediction["inputs"]


def test_full_prediction_artifacts_are_hydrated_for_exact_reuse():
    hydrate = set(_json("config/runtime/runtime_publish_registry.json")["hydrate_paths"])
    assert {"team_strength.json", "projections.json", "package_optimizer.json", "prediction_quality.json"} <= hydrate


def test_exhaustive_publication_records_attested_full_fingerprint(monkeypatch, tmp_path):
    _patch_data(monkeypatch, tmp_path)
    _valid_full_chain(tmp_path)
    monkeypatch.setattr(incremental_reuse, "fingerprint", lambda service: "a" * 64)

    result = full_authority_cache.verify_full_authority("exhaustive_precompute")

    state = json.loads((tmp_path / "incremental_reuse_state.json").read_text(encoding="utf-8"))
    row = state["services"]["prediction"]
    assert result["status"] == "PASS"
    assert result["fingerprint_recorded"] is True
    assert row["fingerprint"] == "a" * 64
    assert row["authority_registry"] == "V3_FULL_OPTIMIZER_AUTHORITY_V1"
    assert row["search_authority"] == "FULL"
    assert row["recorded_profile"] == "exhaustive_precompute"


def test_non_exhaustive_publication_requires_exact_attested_full_fingerprint(monkeypatch, tmp_path):
    _patch_data(monkeypatch, tmp_path)
    _valid_full_chain(tmp_path)
    _write(tmp_path / "incremental_reuse_state.json", {
        "schema_version": 1,
        "registry": "V3_INCREMENTAL_REUSE_STATE_V1",
        "services": {
            "prediction": {
                "fingerprint": "b" * 64,
                "authority_registry": "V3_FULL_OPTIMIZER_AUTHORITY_V1",
                "search_authority": "FULL",
            }
        },
    })
    monkeypatch.setattr(incremental_reuse, "fingerprint", lambda service: "b" * 64)

    result = full_authority_cache.verify_full_authority("fast_decision")
    assert result["status"] == "PASS"
    assert result["fingerprint_recorded"] is False


def test_non_exhaustive_publication_fails_closed_on_fingerprint_change(monkeypatch, tmp_path):
    _patch_data(monkeypatch, tmp_path)
    _valid_full_chain(tmp_path)
    _write(tmp_path / "incremental_reuse_state.json", {
        "services": {
            "prediction": {
                "fingerprint": "c" * 64,
                "authority_registry": "V3_FULL_OPTIMIZER_AUTHORITY_V1",
                "search_authority": "FULL",
            }
        }
    })
    monkeypatch.setattr(incremental_reuse, "fingerprint", lambda service: "d" * 64)

    with pytest.raises(RuntimeError, match="would downgrade FULL optimizer authority"):
        full_authority_cache.verify_full_authority("fast_decision")


def test_authority_gate_rejects_partial_optimizer_even_with_matching_fingerprint(monkeypatch, tmp_path):
    _patch_data(monkeypatch, tmp_path)
    _valid_full_chain(tmp_path)
    optimizer = json.loads((tmp_path / "package_optimizer.json").read_text(encoding="utf-8"))
    optimizer["search_diagnostics"]["search_authority"] = "PARTIAL"
    _write(tmp_path / "package_optimizer.json", optimizer)
    monkeypatch.setattr(incremental_reuse, "fingerprint", lambda service: "e" * 64)

    with pytest.raises(RuntimeError, match="not truthful FULL authority"):
        full_authority_cache.verify_full_authority("exhaustive_precompute")


def test_v3_runtime_materialization_runs_full_authority_gate_before_copy(monkeypatch, tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    _write(source / "runtime_performance.json", {"total_wall_ms": 1, "target_wall_ms": 240000})
    monkeypatch.setattr(publish_snapshot, "DATA", source)
    monkeypatch.setattr(publish_snapshot, "_runtime_workflow_identity", lambda: (123, 1))
    captured = {}

    def fake_verify(profile: str) -> dict:
        captured["profile"] = profile
        return {"status": "PASS", "search_authority": "FULL", "prediction_fingerprint_prefix": "abc123"}

    monkeypatch.setattr(publish_snapshot, "verify_full_authority", fake_verify)
    manifest = publish_snapshot.materialize(source, output, "exhaustive_precompute", "f" * 40)

    assert captured["profile"] == "exhaustive_precompute"
    assert manifest["optimizer_authority"]["search_authority"] == "FULL"
    assert manifest["publication"]["full_optimizer_authority_fail_closed"] is True


def test_v3_runtime_materialization_does_not_copy_after_authority_failure(monkeypatch, tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    monkeypatch.setattr(publish_snapshot, "DATA", source)
    monkeypatch.setattr(publish_snapshot, "_runtime_workflow_identity", lambda: (123, 1))

    def fail(_profile: str) -> dict:
        raise RuntimeError("authority failed")

    monkeypatch.setattr(publish_snapshot, "verify_full_authority", fail)
    with pytest.raises(RuntimeError, match="authority failed"):
        publish_snapshot.materialize(source, output, "fast_decision", "f" * 40)
    assert not output.exists()
