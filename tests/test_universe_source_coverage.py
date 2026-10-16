import pytest
from src.engines.v12_universe_source_coverage import audit_universe

def test_unmapped_provider_does_not_drop_official_player():
    out = audit_universe([{"id": 1}, {"id": 2}], [1, 2],
        [{"official_element_id": 1, "source_native_id": 100, "identity_status": "EXACT"}],
        expected_official_count=2)
    assert out["scanner_coverage"] == "PASS"
    assert out["provider_full_coverage"] == "PARTIAL"
    assert out["provider_unmapped_official_count"] == 1

def test_missing_scanner_player_is_failure():
    out = audit_universe([{"id": 1}, {"id": 2}], [1], [], expected_official_count=2)
    assert out["scanner_coverage"] == "FAIL"
    assert out["missing_official_ids"] == [2]

def test_unverified_bridge_fails_closed():
    with pytest.raises(ValueError, match="NOT_CERTIFIED"):
        audit_universe([{"id": 1}], [1],
            [{"official_element_id": 1, "source_native_id": 100, "identity_status": "UNMAPPED"}],
            expected_official_count=1)

def test_bridge_collision_fails_closed():
    with pytest.raises(ValueError, match="COLLISION"):
        audit_universe([{"id": 1}, {"id": 2}], [1, 2],
            [{"official_element_id": 1, "source_native_id": 100, "identity_status": "EXACT"},
             {"official_element_id": 2, "source_native_id": 100, "identity_status": "EXACT"}],
            expected_official_count=2)


def test_stage1_none_provider_provenance_is_not_zero_coverage():
    # This is the actual Stage C path until independent provider records
    # are supplied. Never turn missing provider input into 0/667 evidence.
    out = audit_universe([{"id": 1}, {"id": 2}], [1, 2], None,
                         expected_official_count=2)
    assert out["scanner_coverage"] == "PASS"
    assert out["provider_coverage_assessed"] is False
    assert out["verified_provider_bridges_in_universe"] is None
    assert out["provider_unmapped_official_count"] is None
    assert out["provider_full_coverage"] == "NOT_EVALUATED"
    assert out["source_fallback"] == "OFFICIAL_FPL_ONLY_FOR_UNMAPPED"


def test_stage1_explicit_empty_provider_list_is_truly_zero_verified():
    out = audit_universe([{"id": 1}, {"id": 2}], [1, 2], [],
                         expected_official_count=2)
    assert out["scanner_coverage"] == "PASS"
    assert out["provider_coverage_assessed"] is True
    assert out["verified_provider_bridges_in_universe"] == 0
    assert out["provider_unmapped_official_count"] == 2
    assert out["provider_full_coverage"] == "PARTIAL"


@pytest.mark.parametrize("n", [666, 668])
def test_stage1_official_universe_wrong_size_fails_even_when_scanner_matches(n):
    official = [{"id": i} for i in range(1, n + 1)]
    with pytest.raises(ValueError, match="OFFICIAL_UNIVERSE_SIZE_NOT_ESTABLISHED"):
        audit_universe(official, list(range(1, n + 1)), None)


def test_stage1_season_667_official_scan_admitted_without_provider():
    official = [{"id": i} for i in range(1, 668)]
    out = audit_universe(official, list(range(1, 668)), None)
    assert out["official_count"] == 667
    assert out["scanner_count"] == 667
    assert out["missing_official_ids"] == []
    assert out["foreign_scanner_ids"] == []
    assert out["scanner_coverage"] == "PASS"
    assert out["provider_full_coverage"] == "NOT_EVALUATED"


def test_stage1_provider_coverage_cannot_rescue_missing_official_member():
    official = [{"id": i} for i in range(1, 668)]
    out = audit_universe(
        official, list(range(1, 667)),
        [{"official_element_id": 1, "source_native_id": 55, "identity_status": "EXACT"}],
    )
    assert out["scanner_coverage"] == "FAIL"
    assert out["missing_official_ids"] == [667]
    assert out["provider_coverage_assessed"] is True


@pytest.mark.parametrize("count,expected", [(666, "DEGRADED"), (667, "COMPLETE"), (668, "DEGRADED")])
def test_stage1_canonical_bridge_stays_fail_closed_when_official_count_changes(
    monkeypatch, count, expected,
):
    from src.models import v12_stagec_universe_scanner as stagec

    # Stub only the candidate-analysis cost. The REAL canonical membership
    # audit is exercised, including the 667 season-wide authority contract.
    monkeypatch.setattr(
        stagec, "build_multiwindow_form_snapshot", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        stagec, "prepare_stagec_projection_copy",
        lambda projections, **_k: projections,
    )
    monkeypatch.setattr(
        stagec, "build_universe_scan",
        lambda **_k: {
            "scanner_coverage_state": "COMPLETE",
            "unique_scanned_count": count,
            "governance": {},
        },
    )
    projection = {"players": [{"element": i} for i in range(1, count + 1)]}
    bootstrap = {
        "elements": [
            {"id": i, "element_type": 3, "now_cost": 50}
            for i in range(1, count + 1)
        ]
    }
    result = stagec.build_stagec_from_canonical_inputs(
        projections=projection, bootstrap=bootstrap, match_rows=[]
    )
    scan = result["scan"]
    assert scan["official_universe_count"] == count
    assert scan["official_coverage_state"] == expected
    assert scan["governance"]["full_universe_scanned"] is (expected == "COMPLETE")
    assert scan["stageb_official_universe_gate"]["scanner_coverage"] == (
        "PASS" if expected == "COMPLETE" else "FAIL"
    )
    if count == 667:
        assert scan["stageb_official_universe_gate"]["provider_full_coverage"] == "NOT_EVALUATED"
    else:
        assert "OFFICIAL_UNIVERSE_SIZE_NOT_ESTABLISHED" in scan["coverage_reason_codes"]
