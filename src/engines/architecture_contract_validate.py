from __future__ import annotations

import json
import re
from pathlib import Path

from src.utils import ROOT

SERVICE_REGISTRY = ROOT / "config" / "v3_service_registry.json"
SOURCE_REGISTRY = ROOT / "config" / "sources" / "registry.json"
COLLECTOR_POLICY = ROOT / "config" / "runtime" / "collector_policy.json"
ARTIFACT_CONTRACTS = ROOT / "config" / "runtime" / "artifact_contracts.json"
PROJECTION_POLICY = ROOT / "config" / "intelligence" / "projection.json"
LINEUP_POLICY = ROOT / "config" / "intelligence" / "lineup_governance.json"
DSS_CORE = ROOT / "config" / "dss_core_registry.json"
DSS_EXT = ROOT / "config" / "dss_extension_registry.json"
ENHANCEMENTS = ROOT / "config" / "enhancement_layers_registry.json"
GATE0 = ROOT / "config" / "gate0_registry.json"
WORKFLOW = ROOT / ".github" / "workflows" / "fpl-engine.yml"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _active_model_ids() -> dict[str, str]:
    ids: dict[str, str] = {}
    for path in sorted((ROOT / "config" / "intelligence").glob("*.json")):
        try:
            payload = _load(path)
        except Exception:
            continue
        for key in ("model_id", "historical_model_id", "model"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                ids[f"{path.name}:{key}"] = value
    return ids


def _registry_rows(payload: dict) -> list[dict]:
    for key in ("modules", "layers", "checks"):
        if isinstance(payload.get(key), list):
            return list(payload[key])
    return []


def _audit_required_paths(errors: list[str], name: str, payload: dict) -> None:
    rows = _registry_rows(payload)
    expected = int(payload.get("expected_count") or 0)
    if expected and expected != len(rows):
        errors.append(f"{name} expected_count={expected} but declared={len(rows)}")
    for row in rows:
        for required in row.get("required_files") or []:
            text = str(required)
            if text == "config/sources.json":
                errors.append(f"{name} still requires removed legacy source config: {row.get('id')}")
            if re.search(r"data/stats/.+_gw\d+\.json$", text):
                errors.append(f"{name} active evidence path embeds fixed GW: {row.get('id')}:{text}")


def run() -> dict:
    errors: list[str] = []
    services = _load(SERVICE_REGISTRY)
    sources = _load(SOURCE_REGISTRY)
    collector = _load(COLLECTOR_POLICY)
    artifact_contracts = _load(ARTIFACT_CONTRACTS)
    projection = _load(PROJECTION_POLICY)
    lineup_policy = _load(LINEUP_POLICY)
    framework_registries = {
        "dss_core": _load(DSS_CORE),
        "dss_extensions": _load(DSS_EXT),
        "enhancements": _load(ENHANCEMENTS),
        "gate0": _load(GATE0),
    }
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    if (ROOT / "config" / "sources.json").exists():
        errors.append("legacy config/sources.json must not exist")

    if sources.get("registry") != "SOURCE_REGISTRY_V3":
        errors.append("canonical source registry must be SOURCE_REGISTRY_V3")
    source_policy = sources.get("policy") or {}
    for key in ("source_network_locations_are_registry_owned", "source_ingestion_timeouts_are_registry_owned"):
        if source_policy.get(key) is not True:
            errors.append(f"source policy missing {key}=true")
    for row in sources.get("sources") or []:
        for path in row.get("artifact_paths") or []:
            if re.search(r"_gw\d+\.json$", str(path)):
                errors.append(f"active source artifact embeds fixed GW: {row.get('id')}:{path}")

    if artifact_contracts.get("registry") != "RUNTIME_ARTIFACT_CONTRACTS_V1":
        errors.append("runtime artifact contract registry must be RUNTIME_ARTIFACT_CONTRACTS_V1")
    artifact_policy = artifact_contracts.get("policy") or {}
    for key in (
        "validate_declared_json_before_acceptance",
        "validate_latest_sidecar_when_present",
        "malformed_json_is_integrity_failure",
        "valid_empty_external_observations_are_allowed",
    ):
        if artifact_policy.get(key) is not True:
            errors.append(f"runtime artifact policy missing {key}=true")
    challenger_contract = (artifact_contracts.get("contracts") or {}).get("challenger_observations.json") or {}
    if (challenger_contract.get("equals") or {}).get("schema_version") != 2:
        errors.append("challenger_observations artifact contract must require schema_version=2")
    if (challenger_contract.get("equals") or {}).get("contract") != "challenger_observation_v2":
        errors.append("challenger_observations artifact contract must require challenger_observation_v2")
    if (challenger_contract.get("types") or {}).get("observations") != "list":
        errors.append("challenger_observations artifact contract must require observations list")

    for name, registry in framework_registries.items():
        _audit_required_paths(errors, name, registry)

    service_map = services.get("services") or {}
    if "collector" in service_map:
        errors.append("monolithic collector service is forbidden")
    required_base = {"official_snapshot", "team_state", "market_state", "live_state", "advanced_stats", "base_snapshot"}
    missing_base = sorted(required_base - set(service_map))
    if missing_base:
        errors.append(f"missing owned base services: {missing_base}")
    policy = services.get("policy") or {}
    if policy.get("generic_root_service_scheduling") is not True:
        errors.append("generic root scheduling policy must be enabled")
    if policy.get("service_boundaries_follow_artifact_ownership_not_file_size") is not True:
        errors.append("service-boundary ownership policy missing")
    if policy.get("single_owner_for_standard_official_network_fetches") is not True:
        errors.append("single Official snapshot owner policy missing")
    for key in (
        "declared_json_artifacts_are_validated_before_acceptance",
        "artifact_contract_registry_owned",
        "malformed_internal_artifact_is_integrity_failure",
        "valid_empty_external_observations_remain_fail_soft",
    ):
        if policy.get(key) is not True:
            errors.append(f"service policy missing {key}=true")

    active_modules: list[str] = []
    for service_name, spec in service_map.items():
        for command in spec.get("commands") or []:
            if "code" in command:
                errors.append(f"inline Python command forbidden: {service_name}")
            module = command.get("module")
            if module:
                active_modules.append(str(module))
    forbidden_active = {"src.engine", "src.reliability_overlay", "src.engines.decision_intelligence_v313", "src.engines.framework_health_audit"}
    found_forbidden = sorted(forbidden_active & set(active_modules))
    if found_forbidden:
        errors.append(f"legacy/monolithic modules active in service registry: {found_forbidden}")
    for module in active_modules:
        if re.search(r"(?:^|\.)v3\d{2,}(?:$|\.)", module):
            errors.append(f"active service module is engine-version stamped: {module}")

    official_service = service_map.get("official_snapshot") or {}
    if [command.get("module") for command in official_service.get("commands") or []] != ["src.engines.official_snapshot_service"]:
        errors.append("official_snapshot must be owned by official_snapshot_service")
    if "official_snapshot.json" not in (official_service.get("ephemeral_artifacts") or []):
        errors.append("official_snapshot.json must be ephemeral")

    prediction = service_map.get("prediction") or {}
    if "official_snapshot.json" not in (prediction.get("inputs") or []):
        errors.append("prediction must consume official_snapshot.json rather than refetch standard Official data")
    historical = service_map.get("historical_prior") or {}
    if "official_snapshot.json" not in (historical.get("inputs") or []):
        errors.append("historical_prior must consume official_snapshot.json")

    engine_text = (ROOT / "src" / "engine.py").read_text(encoding="utf-8")
    for forbidden in ("get_json(", "atomic_json(", "sell_cost("):
        if forbidden in engine_text:
            errors.append(f"src.engine compatibility facade still owns business logic: {forbidden}")

    decision_text = (ROOT / "src" / "engines" / "decision_intelligence.py").read_text(encoding="utf-8")
    for forbidden in ("src.sources.official_fpl", "get_json(", "def build_player_projections(", "def run()"):
        if forbidden in decision_text:
            errors.append(f"legacy projection/direct-fetch path reintroduced in decision_intelligence: {forbidden}")
    historical_text = (ROOT / "src" / "models" / "historical_projection.py").read_text(encoding="utf-8")
    if "from src.models.projection_components import" not in historical_text:
        errors.append("historical projection must consume neutral projection_components")

    battle_threshold = ((lineup_policy.get("battle") or {}).get("close_margin_threshold"))
    try:
        battle_threshold_value = float(battle_threshold)
    except (TypeError, ValueError):
        battle_threshold_value = 0.0
    if battle_threshold_value <= 0:
        errors.append("lineup battle close_margin_threshold must be positive and config-owned")
    lineup_text = (ROOT / "src" / "engines" / "lineup_governance.py").read_text(encoding="utf-8")
    if 'margin < 0.75' in lineup_text:
        errors.append("lineup battle threshold is hardcoded instead of config-owned")

    orchestrator_text = (ROOT / "src" / "runtime_v3" / "orchestrator.py").read_text(encoding="utf-8")
    if "_attempt_promotion" not in orchestrator_text or "failure_stage\"] = \"promotion\"" not in orchestrator_text:
        errors.append("orchestrator promotion failures must enter service criticality handling")
    if "_clear_failed_service_outputs" not in orchestrator_text:
        errors.append("noncritical service failure must quarantine stale owned outputs")
    for required in ("validate_artifact", "validate_latest_sidecar", "artifact_validation"):
        if required not in orchestrator_text:
            errors.append(f"orchestrator artifact acceptance missing {required}")
    artifact_module_text = (ROOT / "src" / "runtime_v3" / "artifact_contracts.py").read_text(encoding="utf-8")
    if "json.loads(path.read_text" not in artifact_module_text:
        errors.append("runtime artifact validator must parse JSON strictly")

    published_horizons = projection.get("published_horizons") or []
    if not published_horizons:
        errors.append("projection published_horizons must be config-owned")
    for location, model_id in _active_model_ids().items():
        if re.search(r"_v3\d{2,}(?:_|$)", model_id):
            errors.append(f"active model id tied to old engine version: {location}={model_id}")

    schedules = collector.get("schedules") or {}
    for name, expression in schedules.items():
        if f'cron: "{expression}"' not in workflow_text:
            errors.append(f"workflow missing collector-policy schedule {name}={expression}")
    deep_workflow = ROOT / ".github" / "workflows" / "deep-stats.yml"
    if deep_workflow.exists():
        errors.append("legacy deep-stats workflow must be removed; runtime publication belongs to main workflow")
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        if "git push origin main" in text:
            errors.append(f"workflow writes runtime data directly to main: {path.name}")

    if 'services["collector"]' in orchestrator_text or "critical collector service failed" in orchestrator_text:
        errors.append("orchestrator still special-cases collector")

    framework_service_text = (ROOT / "src" / "engines" / "framework_health_service.py").read_text(encoding="utf-8")
    if "expected_count" not in framework_service_text or "NORMAL_STALE_MINUTES" not in framework_service_text:
        errors.append("active framework service must own registry-count and config-freshness activation")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "service_count": len(service_map),
        "root_services": sorted(name for name, spec in service_map.items() if not (spec.get("depends_on") or [])),
        "active_model_ids": _active_model_ids(),
        "source_registry": sources.get("registry"),
        "service_registry_schema": services.get("schema_version"),
        "artifact_contract_registry": artifact_contracts.get("registry"),
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()
