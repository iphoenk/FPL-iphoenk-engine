from src.runtime_v3.release_acceptance import integration_gates


def test_composite_release_gate_preserves_all_underlying_integrations():
    gates = integration_gates()
    names = [gate.name for gate in gates]
    assert names == [
        "full_runtime",
        "source_contract",
        "production_contract",
        "watchlist_contract",
        "report_serving_contract",
        "report_time_contract",
        "full_resource_guard",
        "fast_cold_warmup",
        "fast_runtime",
        "fast_slo_guard",
        "material_equivalence",
    ]
    commands = [" ".join(gate.command) for gate in gates]
    assert any("domain_orchestrator --mode daily --stats --profile full_refresh" in command for command in commands)
    assert any("source_contract_validate" in command for command in commands)
    assert any("production_contract_validate" in command for command in commands)
    assert any("watchlist_contract_validate" in command for command in commands)
    assert any("report_serving_validate" in command for command in commands)
    assert any("report_time_contract_validate" in command for command in commands)
    assert any("performance_guard --profile full_refresh" in command for command in commands)
    fast_commands = [command for command in commands if "domain_orchestrator --mode daily --stats --profile fast_decision" in command]
    assert len(fast_commands) == 2
    assert any("performance_guard --profile fast_decision" in command for command in commands)
    assert any("equivalence_acceptance" in command for command in commands)
