import json
from pathlib import Path

from src.runtime_v3.domain_orchestrator import _validate_domain_coverage

ROOT = Path(__file__).resolve().parents[1]


def test_seven_domains_cover_every_background_capability_exactly_once():
    domains = json.loads((ROOT / "config/runtime/execution_domains.json").read_text())
    services = json.loads((ROOT / "config/v3_service_registry.json").read_text())
    assert domains["registry"] == "V3_EXECUTION_DOMAINS_V1"
    assert domains["domain_count"] == 7
    assert list(domains["domains"]) == ["ACQUIRE", "ENRICH", "MODEL", "MARKET", "DECISION", "GOVERNANCE", "PUBLISH"]
    _validate_domain_coverage(domains, services)
    assigned = [cap for spec in domains["domains"].values() for cap in spec["capabilities"]]
    assert len(assigned) == 21
    assert len(set(assigned)) == 21
    assert set(assigned) == set(services["services"])


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
