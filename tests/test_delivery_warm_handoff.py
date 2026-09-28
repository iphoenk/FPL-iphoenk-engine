from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.engines.v12_dp2_p6_handoff import (
    HandoffError,
    build_handoff,
    validate_snapshot_binding,
    validate_t15_t10_window,
)

WIB = ZoneInfo("Asia/Jakarta")


def identity():
    return {
        "gw_fixture_fingerprint": "gw6",
        "model_version": "V12",
        "schema_version": "6",
        "projection_lineage_fingerprint": "proj",
        "current15_fingerprint": "our15",
        "owner_context_fingerprint": "owner-private",
        "mc_authority": "V12_MC_500K_CRN",
    }


def test_occurrence_binding_and_t10_freeze():
    visible = datetime(2026, 9, 28, 12, 30, tzinfo=WIB)
    freeze = visible - timedelta(minutes=10)
    h = build_handoff(
        report_kind="full_master",
        logical_slot=visible.isoformat(),
        freeze_target_at=freeze.isoformat(),
        production_sha="a" * 40,
        runtime_data_sha="b" * 40,
        identity=identity(),
    )
    validate_snapshot_binding(
        h,
        snapshot={
            "occurrence_id": h.occurrence_id,
            "logical_slot": h.logical_slot,
            "production_sha": h.production_sha,
            "runtime_data_sha": h.runtime_data_sha,
            "gw_fixture_fingerprint": h.gw_fixture_fingerprint,
        },
    )


def test_cross_occurrence_and_stale_runtime_rejected():
    visible = datetime(2026, 9, 28, 12, 30, tzinfo=WIB)
    h = build_handoff(
        report_kind="full_master",
        logical_slot=visible.isoformat(),
        freeze_target_at=(visible - timedelta(minutes=10)).isoformat(),
        production_sha="a" * 40,
        runtime_data_sha="b" * 40,
        identity=identity(),
    )
    with pytest.raises(HandoffError, match="cross-occurrence"):
        validate_snapshot_binding(
            h,
            snapshot={
                "occurrence_id": "wrong",
                "logical_slot": h.logical_slot,
                "production_sha": h.production_sha,
                "runtime_data_sha": h.runtime_data_sha,
                "gw_fixture_fingerprint": h.gw_fixture_fingerprint,
            },
        )
    with pytest.raises(HandoffError, match="stale/cross-occurrence"):
        validate_snapshot_binding(
            h,
            snapshot={
                "occurrence_id": h.occurrence_id,
                "logical_slot": h.logical_slot,
                "production_sha": h.production_sha,
                "runtime_data_sha": "c" * 40,
                "gw_fixture_fingerprint": h.gw_fixture_fingerprint,
            },
        )


def test_t15_t10_window_is_exact_and_fail_closed():
    validate_t15_t10_window(
        logical_slot="2026-09-28T12:30:00+07:00",
        release_at="2026-09-28T12:15:00+07:00",
        freeze_target_at="2026-09-28T12:20:00+07:00",
    )
    with pytest.raises(HandoffError, match="exact T-15/T-10"):
        validate_t15_t10_window(
            logical_slot="2026-09-28T12:30:00+07:00",
            release_at="2026-09-28T12:16:00+07:00",
            freeze_target_at="2026-09-28T12:20:00+07:00",
        )
