from src.runtime_v6.wave2_acceptance import run


def test_wave2_acceptance_green():
    result = run()
    assert result["status"] == "PASS", result
    assert result["failures"] == []
    assert set(result["exit_gate"].values()) == {"PASS"}
