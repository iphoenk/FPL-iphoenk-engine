from src.v5.evaluation.shadow_parity import compare


def test_shadow_parity_accepts_structurally_equivalent_decisions():
    v3 = {"starting_xi":[{"element":i} for i in range(1,12)],"captain":3,"captain_state":"LOCK","ruleset_id":"FPL_2026_27","manual_lock_authoritative":True,"legal":True}
    v5 = {"starting_xi":[{"element":i} for i in range(1,12)],"lineup":{"captain":{"element":3}},"user_report":{"captaincy":{"decision":"LOCK"}},"ruleset_id":"FPL_2026_27","squad_authority":"user_lock","framework_health":{"gate0":{"pass":True}}}
    result = compare(v3, v5)
    assert result["pass"] is True
    assert result["required_real_cycles"] >= 3


def test_shadow_parity_rejects_locked_captain_mismatch():
    v3 = {"starting_xi":[{"element":i} for i in range(1,12)],"captain":3,"captain_state":"LOCK"}
    v5 = {"starting_xi":[{"element":i} for i in range(1,12)],"lineup":{"captain":{"element":4}},"user_report":{"captaincy":{"decision":"LOCK"}}}
    assert compare(v3, v5)["pass"] is False
