from __future__ import annotations

import hashlib
import json

import pytest

from src.engines.v12_compact_private_context import (
    CompactPrivateContextError,
    DEEP_SECTION_IDS,
    build_compact_private_context,
)


def _bundle():
    return {
        "report_mode": "DEEP",
        "report_slot": "2026-09-28T21:30:00+07:00",
        "planning_gw": 6,
        "runner_status": "PASS",
        "delivery_status": "READY_FULL",
        "occurrence_id": "DEEP|2026-09-28T21:30:00+07:00",
        "section_manifest": [{"id": sid, "status": "PASS"} for sid in DEEP_SECTION_IDS],
        "report": {
            "S08": {"captain": 1, "vice": 2},
            "S15B": {"rank": 7},
            "S19": {"action": "WAIT"},
        },
        "decision_surfaces": {
            "starting_xi": [1,2,3,4,5,6,7,8,9,10,11],
            "bench_order": [12,13,14,15],
            "captain": 1,
            "vice_captain": 2,
            "transfer_action": "HOLD",
            "package_frontier": [{"route": "HOLD"}],
            "scenario_summary": {"status": "STABLE"},
            "stability_summary": {"reversal_probability": 0.1},
            "stage3_action": "WAIT",
        },
        "source_fingerprints": {"official": "abc"},
        "prefetch_binding": {"same_occurrence": True},
    }


def _sha(bundle):
    raw = json.dumps(bundle, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


def test_compact_context_is_read_only_projection_and_preserves_authority():
    bundle = _bundle()
    sha = _sha(bundle)
    out = build_compact_private_context(
        bundle=bundle,
        digest={
            "report_mode": "DEEP",
            "report_slot": bundle["report_slot"],
            "canonical_bundle_sha256": sha,
            "canonical_body_sha256": "b" * 64,
        },
        execution_private={
            "model_sha": "a" * 40,
            "runtime_sha": "b" * 40,
            "math_recomputed": False,
        },
        actual_bundle_sha256=sha,
    )
    assert out["read_only"] is True
    assert out["math_recomputed"] is False
    assert out["decision_authority"] == "CANONICAL_V12_PRIVATE_BUNDLE"
    assert out["decision"]["decision_status"] == "WAIT"
    assert out["decision"]["lineup"]["captain"] == 1
    assert out["decision"]["mini_league"] == {"rank": 7}
    assert list(out["section_status"]) == list(DEEP_SECTION_IDS)


@pytest.mark.parametrize("field,value", [
    ("report_slot", "wrong"),
    ("report_mode", "PRICE"),
])
def test_digest_lineage_mismatch_fails_closed(field, value):
    bundle = _bundle()
    sha = _sha(bundle)
    digest = {
        "report_mode": "DEEP",
        "report_slot": bundle["report_slot"],
        "canonical_bundle_sha256": sha,
    }
    digest[field] = value
    with pytest.raises(CompactPrivateContextError):
        build_compact_private_context(
            bundle=bundle,
            digest=digest,
            execution_private={"model_sha":"a"*40,"runtime_sha":"b"*40,"math_recomputed":False},
            actual_bundle_sha256=sha,
        )


def test_wrong_bundle_fingerprint_fails_closed():
    bundle = _bundle()
    with pytest.raises(CompactPrivateContextError, match="digest mismatch"):
        build_compact_private_context(
            bundle=bundle,
            digest={
                "report_mode":"DEEP",
                "report_slot":bundle["report_slot"],
                "canonical_bundle_sha256":"f"*64,
            },
            execution_private={"model_sha":"a"*40,"runtime_sha":"b"*40,"math_recomputed":False},
            actual_bundle_sha256="e"*64,
        )


def test_deep_requires_exact_23_section_order():
    bundle = _bundle()
    bundle["section_manifest"] = bundle["section_manifest"][:-1]
    sha = _sha(bundle)
    with pytest.raises(CompactPrivateContextError, match="23-section"):
        build_compact_private_context(
            bundle=bundle,
            digest={"report_mode":"DEEP","report_slot":bundle["report_slot"],"canonical_bundle_sha256":sha},
            execution_private={"model_sha":"a"*40,"runtime_sha":"b"*40,"math_recomputed":False},
            actual_bundle_sha256=sha,
        )
