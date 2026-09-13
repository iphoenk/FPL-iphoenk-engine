from __future__ import annotations

import pytest

from src.runtime_v6.production_validate import _validate_source_activation_transition
from src.runtime_v6.registry import EXPECTED_SOURCE_IDS


def _registry(*, reference_only: set[str] | None = None, disabled: set[str] | None = None):
    return {
        "activation": {
            "active_source_count": len(EXPECTED_SOURCE_IDS),
            "reference_only_sources": {key: "TEST" for key in (reference_only or set())},
            "disabled_sources": {key: "TEST" for key in (disabled or set())},
        }
    }


def test_current_active_source_set_is_accepted() -> None:
    manifest = {
        "source_count": len(EXPECTED_SOURCE_IDS),
        "source_ids": list(EXPECTED_SOURCE_IDS),
    }
    assert _validate_source_activation_transition(manifest, _registry(), schedule_kind="chatgpt_scheduler") == "CURRENT"


def test_report_prefetch_allows_only_reference_only_superset_transition() -> None:
    legacy = "legacy_model_source"
    manifest = {
        "source_count": len(EXPECTED_SOURCE_IDS) + 1,
        "source_ids": [*EXPECTED_SOURCE_IDS, legacy],
    }
    result = _validate_source_activation_transition(
        manifest,
        _registry(reference_only={legacy}),
        schedule_kind="report_prefetch",
    )
    assert result == "LEGACY_ACTIVE_SUPERSET_REFERENCE_ONLY_TRANSITION"


def test_non_prefetch_never_accepts_activation_mismatch() -> None:
    legacy = "legacy_model_source"
    manifest = {
        "source_count": len(EXPECTED_SOURCE_IDS) + 1,
        "source_ids": [*EXPECTED_SOURCE_IDS, legacy],
    }
    with pytest.raises(AssertionError):
        _validate_source_activation_transition(
            manifest,
            _registry(reference_only={legacy}),
            schedule_kind="chatgpt_scheduler",
        )


def test_report_prefetch_rejects_disabled_source_transition() -> None:
    legacy = "legacy_disabled_source"
    manifest = {
        "source_count": len(EXPECTED_SOURCE_IDS) + 1,
        "source_ids": [*EXPECTED_SOURCE_IDS, legacy],
    }
    with pytest.raises(AssertionError):
        _validate_source_activation_transition(
            manifest,
            _registry(disabled={legacy}),
            schedule_kind="report_prefetch",
        )


def test_report_prefetch_rejects_missing_current_active_source() -> None:
    missing = EXPECTED_SOURCE_IDS[0]
    legacy = "legacy_model_source"
    manifest_ids = [source_id for source_id in EXPECTED_SOURCE_IDS if source_id != missing]
    manifest_ids.append(legacy)
    manifest = {
        "source_count": len(manifest_ids),
        "source_ids": manifest_ids,
    }
    with pytest.raises(AssertionError):
        _validate_source_activation_transition(
            manifest,
            _registry(reference_only={legacy}),
            schedule_kind="report_prefetch",
        )
