import json
from pathlib import Path

from src.runtime_v3.domain_orchestrator import _validate_domain_coverage

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_domains_cover_every_background_capability_exactly_once():
    domains = json.loads((ROOT / "config/runtime/execution_domains.json").read_text())
    services = json.loads((ROOT / "config/v3_service_registry.json").read_text())
    assert domains["registry"] == "V3_EXECUTION_DOMAINS_V2"
    assert domains["phase_count"] == 6
    assert domains["domain_count"] == 11
    assert domains["canonical_phases"] == {
        "ACQUIRE": ["official_state", "personal_team_state"],
        "ENRICH": ["football_context", "market_context"],
        "MODEL": ["prediction"],
        "DECISION": ["squad_decision", "challenger_analysis"],
        "GOVERNANCE": ["framework_governance", "prediction_validation"],
        "PUBLISH": ["reporting", "serving"],
    }
    assert list(domains["domains"]) == [
        "official_state",
        "personal_team_state",
        "football_context",
        "market_context",
        "prediction",
        "squad_decision",
        "challenger_analysis",
        "framework_governance",
        "prediction_validation",
        "reporting",
        "serving",
    ]
    _validate_domain_coverage(domains, services)
    assigned = [cap for spec in domains["domains"].values() for cap in spec["capabilities"]]
    assert len(assigned) == 22
    assert len(set(assigned)) == 22
    assert set(assigned) == set(services["services"])


def test_canonical_domain_boundaries_prevent_responsibility_leakage():
    registry = json.loads((ROOT / "config/runtime/execution_domains.json").read_text())
    domains = registry["domains"]
    assert "weather_context" in domains["football_context"]["capabilities"]
    assert "weather_context" not in domains
    assert domains["prediction"]["capabilities"] == ["prediction"]
    assert domains["squad_decision"]["capabilities"] == ["lineup_governance"]
    assert domains["challenger_analysis"]["capabilities"] == ["challenger"]
    assert "prediction_validation" in domains["framework_governance"]["depends_on"]
    assert domains["reporting"]["capabilities"] == ["watchlist", "reporting"]
    assert domains["serving"]["capabilities"] == ["report_materializer"]
    assert domains["serving"]["depends_on"] == ["reporting"]
    assert registry["policy"]["prediction_has_no_decision_or_reporting_ownership"] is True
    assert registry["policy"]["challenger_analysis_is_advisory_to_squad_decision"] is True
    assert registry["policy"]["prediction_validation_gates_publication"] is True
    assert registry["policy"]["phase_membership_is_a_responsibility_taxonomy_not_a_strict_execution_barrier"] is True
    assert registry["policy"]["dependency_dag_controls_execution_order"] is True
    assert registry["policy"]["weather_context_does_not_add_process_startup_boundary"] is True


def test_domain_dependency_dag_is_acyclic_and_covers_capability_dependencies():
    registry = json.loads((ROOT / "config/runtime/execution_domains.json").read_text())
    services = json.loads((ROOT / "config/v3_service_registry.json").read_text())
    _validate_domain_coverage(registry, services)


def test_domain_dag_reaches_every_domain_without_phase_order_assumptions():
    registry = json.loads((ROOT / "config/runtime/execution_domains.json").read_text())
    remaining = list(registry["domains"])
    completed: set[str] = set()
    waves: list[list[str]] = []
    while remaining:
        ready = [
            name
            for name in remaining
            if set(registry["domains"][name]["depends_on"]).issubset(completed)
        ]
        assert ready
        waves.append(ready)
        completed.update(ready)
        remaining = [name for name in remaining if name not in ready]

    assert completed == set(registry["domains"])
    assert waves == [
        ["official_state"],
        ["personal_team_state"],
        ["football_context"],
        ["market_context", "prediction"],
        ["squad_decision", "prediction_validation"],
        ["challenger_analysis"],
        ["framework_governance"],
        ["reporting"],
        ["serving"],
    ]


def test_domains_do_not_replace_business_capability_ownership():
    domains = json.loads((ROOT / "config/runtime/execution_domains.json").read_text())
    ownership = json.loads((ROOT / "config/v3_architecture_ownership_registry.json").read_text())
    interactive = json.loads((ROOT / "config/runtime/interactive_service_registry.json").read_text())
    assert domains["policy"]["execution_domains_are_process_orchestration_boundaries_not_business_owners"] is True
    assert domains["policy"]["capability_ownership_remains_in_v3_architecture_ownership_registry"] is True
    owner_services = {row["owner_service"] for row in ownership["responsibilities"]}
    assigned = {cap for spec in domains["domains"].values() for cap in spec["capabilities"]}
    interactive_owners = set(interactive["services"])
    assert interactive_owners == {"unified_fastpath"}
    background_owners = owner_services - interactive_owners
    assert background_owners.issubset(assigned)
    assert not (interactive_owners & assigned)


def test_unified_runtime_is_only_scheduled_v3_runtime_workflow():
    workflows = ROOT / ".github/workflows"
    runtime = (workflows / "v3-runtime.yml").read_text()
    compat = (workflows / "fpl-engine.yml").read_text()
    assert "schedule:" in runtime
    assert "schedule:" not in compat
    assert not (workflows / "v3-runtime-fast.yml").exists()
    assert not (workflows / "v3-refresh-full.yml").exists()
    assert "src.runtime_v3.domain_orchestrator" in runtime
