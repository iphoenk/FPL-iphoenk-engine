from src.runtime_v3.fast_lane_contract_validate import run


def test_fast_lane_contract_is_fail_closed_and_sub3s():
    result = run()
    assert result["status"] == "PASS"
    assert result["execution_domains"] == 11
    assert result["capability_owners"] == 22
    assert result["hard_wall_ms"] == 3000
    assert result["consecutive_candidate_runs"] >= 3
    assert result["fallback_to_multi_process_allowed"] is False
