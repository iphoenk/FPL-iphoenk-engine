from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.consumer import assess_snapshot


def _write_snapshot(root: Path, generated_at: str, *, overall: str = "GREEN", integrity: str = "PASS") -> None:
    (root / "health").mkdir(parents=True)
    manifest = {
        "generated_at": generated_at,
        "overall": overall,
        "critical_failures": [],
        "control_failures": [],
        "runtime_control": {"health": "GREEN"},
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
        },
    }
    publish_integrity = {
        "status": integrity,
        "current_source_files_exact": True,
        "identity_map_consistent": True,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "health" / "publish_integrity.json").write_text(json.dumps(publish_integrity), encoding="utf-8")


def test_fresh_green_snapshot_is_usable(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(root, "2026-09-04T10:00:00+00:00")

    result = assess_snapshot(
        root,
        now=datetime(2026, 9, 4, 10, 45, tzinfo=timezone.utc),
        max_age_minutes=90,
    )

    assert result["state"] == "FRESH"
    assert result["usable"] is True
    assert result["direct_fallback_eligible"] is False


def test_static_green_snapshot_becomes_stale_at_read_time(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(root, "2026-09-04T07:14:41+00:00")

    result = assess_snapshot(
        root,
        now=datetime(2026, 9, 4, 10, 45, tzinfo=timezone.utc),
        max_age_minutes=90,
    )

    assert result["manifest_overall"] == "GREEN"
    assert result["state"] == "STALE"
    assert result["usable"] is False
    assert result["direct_fallback_eligible"] is True
    assert result["governance"]["consumer_does_not_trust_static_green_without_freshness"] is True


def test_publish_integrity_failure_is_invalid_even_when_fresh(tmp_path: Path):
    root = tmp_path / "v6"
    _write_snapshot(root, "2026-09-04T10:40:00+00:00", integrity="FAIL")

    result = assess_snapshot(
        root,
        now=datetime(2026, 9, 4, 10, 45, tzinfo=timezone.utc),
    )

    assert result["state"] == "INVALID"
    assert result["usable"] is False
    assert "PUBLISH_INTEGRITY_NOT_PASS" in result["failures"]


def test_missing_runtime_snapshot_requires_direct_fallback(tmp_path: Path):
    result = assess_snapshot(tmp_path / "missing")

    assert result["state"] == "INVALID"
    assert result["direct_fallback_eligible"] is True
    assert result["failures"] == ["MISSING_MANIFEST"]
