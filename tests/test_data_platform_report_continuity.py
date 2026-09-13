from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.runtime_v6.production_validate import _validate_registry_compatibility


ROOT = Path(__file__).resolve().parents[1]


def _snapshot_manifest(*, count: int = 22) -> dict:
    source_ids = [f"source_{idx}" for idx in range(count)]
    source_ids[0] = "official_fpl"
    source_ids[1] = "official_price_predictor"
    return {
        "source_count": count,
        "source_ids": source_ids,
        "activation": {
            "active_source_count": count,
            "required_active_sources": ["official_fpl", "official_price_predictor"],
        },
    }


def _current_registry(*, count: int = 14) -> dict:
    return {
        "activation": {
            "active_source_count": count,
            "required_active_sources": ["official_fpl", "official_price_predictor"],
        }
    }


def test_report_prefetch_accepts_internally_valid_last_good_registry_epoch() -> None:
    manifest = _snapshot_manifest(count=22)
    registry = _current_registry(count=14)

    result = _validate_registry_compatibility(
        manifest,
        registry,
        schedule_kind="report_prefetch",
    )

    assert result == "SNAPSHOT_REGISTRY_VALIDATED"


def test_core_publication_still_requires_current_registry() -> None:
    manifest = _snapshot_manifest(count=22)
    registry = _current_registry(count=14)

    with pytest.raises(AssertionError):
        _validate_registry_compatibility(
            manifest,
            registry,
            schedule_kind="chatgpt_scheduler",
        )


def test_report_prefetch_does_not_accept_internally_corrupt_snapshot() -> None:
    manifest = _snapshot_manifest(count=22)
    manifest["activation"]["active_source_count"] = 21

    with pytest.raises(AssertionError):
        _validate_registry_compatibility(
            manifest,
            _current_registry(count=14),
            schedule_kind="report_prefetch",
        )


def test_report_prefetch_transport_is_comment_only() -> None:
    policy = json.loads((ROOT / "config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    report_prefetch = policy["report_prefetch"]
    governance = policy["governance"]

    assert report_prefetch["issue_comment_command"] == "/v6-report-prefetch"
    assert report_prefetch["issue_title_edit_enabled"] is False
    assert report_prefetch["preferred_transport"] == "ISSUE_COMMENT"
    assert "issues:report_prefetch" not in governance["authoritative_runtime_triggers"]
    assert "issue_comment:report_prefetch" in governance["authoritative_runtime_triggers"]
    assert governance["report_prefetch_issue_title_transport_disabled"] is True
