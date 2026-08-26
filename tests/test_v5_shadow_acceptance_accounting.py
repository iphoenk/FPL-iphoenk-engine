from __future__ import annotations

import json
from pathlib import Path

import src.v5.shadow_acceptance as accounting


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _cycle(cycle_id: str, *, v5: str, v3: str, baseline: str, sha: str, post: str = "PASS", cycle_pass: bool = True) -> dict:
    return {
        "schema_version": 4,
        "cycle_id": cycle_id,
        "generated_at": f"2026-08-27T00:0{cycle_id[-1]}:00+00:00",
        "mode": "REAL_SHADOW",
        "v3": {"engine_version": v3},
        "v5": {"engine_version": v5},
        "acceptance_context": {
            "production_baseline_version": baseline,
            "production_main_sha": sha,
        },
        "parity": {"pass": cycle_pass},
        "operational_invariants": {"pass": cycle_pass, "checks": {}},
        "acceptance_progress": {"cycle_pass": cycle_pass},
        "post_validation": {"status": post, "validated_at": "2026-08-27T00:10:00+00:00"},
    }


def test_accounting_counts_only_postvalidated_cycles_for_current_version_and_baseline(tmp_path, monkeypatch):
    baseline = "v3.17.1"
    sha = "abc123"
    monkeypatch.setattr(accounting, "V5_VERSION", "5.0.0-beta.2")
    monkeypatch.setattr(accounting, "_baseline", lambda: (baseline, sha))
    monkeypatch.setattr(accounting, "_required_cycles", lambda: 3)
    monkeypatch.setattr(accounting, "_accounting_policy", lambda: {
        "require_post_validation_pass": True,
        "require_same_v5_version": True,
        "require_same_production_baseline": True,
    })

    cycles = tmp_path / "cycles"
    _write(cycles / "c1.json", _cycle("c1", v5="5.0.0-beta.2", v3="3.17.1", baseline=baseline, sha=sha))
    _write(cycles / "c2.json", _cycle("c2", v5="5.0.0-beta.2", v3="3.17.1", baseline=baseline, sha=sha, post="PENDING"))
    _write(cycles / "c3.json", _cycle("c3", v5="5.0.0-beta.1", v3="3.17.1", baseline=baseline, sha=sha))
    _write(cycles / "c4.json", _cycle("c4", v5="5.0.0-beta.2", v3="3.17.0", baseline=baseline, sha=sha))

    rows = accounting._validated_cycles(cycles)
    assert [row["cycle_id"] for row in rows] == ["c1"]


def test_finalize_marks_cycle_validated_and_computes_three_of_three(tmp_path, monkeypatch):
    baseline = "v3.17.1"
    sha = "abc123"
    monkeypatch.setattr(accounting, "V5_VERSION", "5.0.0-beta.2")
    monkeypatch.setattr(accounting, "_baseline", lambda: (baseline, sha))
    monkeypatch.setattr(accounting, "_required_cycles", lambda: 3)
    monkeypatch.setattr(accounting, "_accounting_policy", lambda: {
        "require_post_validation_pass": True,
        "require_same_v5_version": True,
        "require_same_production_baseline": True,
    })

    cycles = tmp_path / "cycles"
    _write(cycles / "c1.json", _cycle("c1", v5="5.0.0-beta.2", v3="3.17.1", baseline=baseline, sha=sha))
    _write(cycles / "c2.json", _cycle("c2", v5="5.0.0-beta.2", v3="3.17.1", baseline=baseline, sha=sha))
    current = _cycle("c3", v5="5.0.0-beta.2", v3="3.17.1", baseline=baseline, sha=sha, post="PENDING")
    latest = tmp_path / "latest_shadow_cycle.json"
    _write(latest, current)
    _write(cycles / "c3.json", current)

    summary = accounting.finalize(str(latest), str(tmp_path))
    persisted = json.loads(latest.read_text(encoding="utf-8"))

    assert summary["validated_successful_cycles"] == 3
    assert summary["remaining_validated_cycles"] == 0
    assert summary["production_candidate_eligible"] is True
    assert summary["production_candidate_auto_promoted"] is False
    assert persisted["post_validation"]["status"] == "PASS"
    assert persisted["acceptance_progress"]["counts_as_successful_acceptance_cycle"] is True
    assert persisted["acceptance_progress"]["production_candidate_eligible"] is True
