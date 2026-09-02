from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "v4_precompute_reuse_guard.py"
spec = importlib.util.spec_from_file_location("v4_precompute_reuse_guard", SCRIPT)
assert spec and spec.loader
reuse_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reuse_guard)


def _provenance(*, published_at: str = "2026-09-02T00:10:00+00:00") -> dict:
    return {
        "canonical_source_sha": "a" * 40,
        "runtime_publish_at": published_at,
        "checkpoint": {
            "snapshot_role": "PRECOMPUTE_NEXT_CHECKPOINT",
            "target_checkpoint": "2026-09-02T00:30:00+00:00",
            "precomputed": True,
            "generated_before_or_at_target": True,
            "materialization_complete": True,
            "publication_proof": "PRESENCE_ON_RUNTIME_BRANCH",
        },
    }


def test_exact_precompute_is_reusable_while_operationally_fresh() -> None:
    report = reuse_guard.evaluate(
        _provenance(),
        target_checkpoint="2026-09-02T00:30:00+00:00",
        canonical_sha="a" * 40,
        observed=datetime(2026, 9, 2, 0, 45, tzinfo=timezone.utc),
        fresh_max_minutes=60,
    )
    assert report["reusable"] is True
    assert report["reason"] == "REUSABLE"
    assert report["age_minutes"] == 35.0


def test_delayed_heartbeat_recomputes_when_exact_precompute_is_no_longer_fresh() -> None:
    report = reuse_guard.evaluate(
        _provenance(),
        target_checkpoint="2026-09-02T00:30:00+00:00",
        canonical_sha="a" * 40,
        observed=datetime(2026, 9, 2, 1, 16, tzinfo=timezone.utc),
        fresh_max_minutes=60,
    )
    assert report["reusable"] is False
    assert report["reason"] == "PUBLISH_AGE_EXCEEDS_FRESH_MAX"
    assert report["age_minutes"] == 66.0


def test_reuse_fails_closed_on_canonical_mismatch() -> None:
    report = reuse_guard.evaluate(
        _provenance(),
        target_checkpoint="2026-09-02T00:30:00+00:00",
        canonical_sha="b" * 40,
        observed=datetime(2026, 9, 2, 0, 45, tzinfo=timezone.utc),
        fresh_max_minutes=60,
    )
    assert report["reusable"] is False
    assert report["reason"] == "CANONICAL_SHA_MISMATCH"


def test_reuse_accepts_exact_freshness_boundary() -> None:
    report = reuse_guard.evaluate(
        _provenance(),
        target_checkpoint="2026-09-02T00:30:00+00:00",
        canonical_sha="a" * 40,
        observed=datetime(2026, 9, 2, 1, 10, tzinfo=timezone.utc),
        fresh_max_minutes=60,
    )
    assert report["reusable"] is True
    assert report["age_minutes"] == 60.0
