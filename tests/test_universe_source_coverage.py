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
