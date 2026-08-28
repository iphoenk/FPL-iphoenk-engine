from pathlib import Path

from src.v5.architecture_guard import run_audit
from src.v5.config_cache import load_json_config
from src.v5.service_registry import get_service, module_owners
from src.v5.services.architecture_guard import handle as architecture_guard_handle

ROOT = Path(__file__).resolve().parents[1]


def test_repository_passes_architecture_ownership_no_duplicate_gate():
    out = run_audit()
    failed = {name: row["detail"] for name, row in out["checks"].items() if not row["pass"]}
    assert out["status"] == "PASS", failed
    assert not failed, failed


def test_architecture_guard_is_noncritical_and_not_hot_path_dependency():
    guard = get_service("architecture_guard")
    orchestrator = get_service("orchestrator")
    assert guard.critical is False
    assert guard.dependencies == ()
    assert "architecture_guard" not in orchestrator.dependencies
    status = architecture_guard_handle("status", {})
    assert status["critical_path"] is False
    assert status["promotion_blocking"] is True


def test_architecture_guard_module_has_exactly_one_owner():
    owners = module_owners()
    assert owners["architecture_ownership_guard"] == "architecture_guard"


def test_architecture_ownership_registry_is_release_fingerprinted():
    release = load_json_config("config/v5_release_integrity_registry.json")
    assert release["contract"] == "V5_RUNTIME_RELEASE_FINGERPRINT_V9"
    assert "config/v5_architecture_ownership_registry.json" in release["include_files"]
    assert release["governance"]["architecture_ownership_policy_change_resets_acceptance"] is True
    assert release["governance"]["no_duplicate_gate_must_pass_for_promotion"] is True


def test_architecture_guard_service_is_deployed_but_not_orchestrator_dependency():
    compose = (ROOT / "deploy/v5/docker-compose.yml").read_text(encoding="utf-8")
    assert "  architecture_guard:" in compose
    assert "V5_SERVICE_ID: architecture_guard" in compose
    orchestrator_block = compose.split("  orchestrator:", 1)[1]
    assert "V5_SERVICE_ARCHITECTURE_GUARD_URL" not in orchestrator_block
    assert "architecture_guard: {condition: service_healthy}" not in orchestrator_block


def test_guard_contract_matches_v4_consolidation_principle_without_copying_v4_runtime():
    cfg = load_json_config("config/v5_architecture_ownership_registry.json")
    assert cfg["principle"] == "ONE_OWNER_PER_RESPONSIBILITY_SHARED_PRIMITIVES_REUSED_NOT_REIMPLEMENTED"
    assert cfg["governance"]["fail_closed_on_duplicate_identity"] is True
    assert cfg["governance"]["fail_closed_on_duplicate_business_authority"] is True
    assert cfg["governance"]["fail_closed_on_exact_nontrivial_function_clone"] is True
    assert cfg["governance"]["guard_must_not_join_user_hot_path"] is True
