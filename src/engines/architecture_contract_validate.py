from __future__ import annotations

import json
import re
from pathlib import Path

from src.utils import ROOT

SERVICE_REGISTRY = ROOT / "config" / "v3_service_registry.json"
SOURCE_REGISTRY = ROOT / "config" / "sources" / "registry.json"
COLLECTOR_POLICY = ROOT / "config" / "runtime" / "collector_policy.json"
PROJECTION_POLICY = ROOT / "config" / "intelligence" / "projection.json"
DSS_CORE = ROOT / "config" / "dss_core_registry.json"
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


def run() -> dict:
    errors: list[str] = []
    services = _load(SERVICE_REGISTRY)
    sources = _load(SOURCE_REGISTRY)
    collector = _load(COLLECTOR_POLICY)
    projection = _load(PROJECTION_POLICY)
    dss = _load(DSS_CORE)
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

    service_map = services.get("services") or {}
    if "collector" in service_map:
        errors.append("monolithic collector service is forbidden")
    required_base = {"official_snapshot", "team_state", "market_state", "live_state", "advanced_stats", "base_snapshot"}
    missing_base = sorted(required_base - set(service_map))
    if missing_base:
        errors.append(f"missing owned base services: {missing_base}")
    if (services.get("policy") or {}).get("generic_root_service_scheduling") is not True:
        errors.append("generic root scheduling policy must be enabled")
    if (services.get("policy") or {}).get("service_boundaries_follow_artifact_ownership_not_file_size") is not True:
        errors.append("service-boundary ownership policy missing")

    active_modules: list[str] = []
    for service_name, spec in service_map.items():
        for command in spec.get("commands") or []:
            if "code" in command:
                errors.append(f"inline Python command forbidden: {service_name}")
            module = command.get("module")
            if module:
                active_modules.append(str(module))
    forbidden_active = {"src.engine", "src.reliability_overlay", "src.engines.decision_intelligence_v313"}
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

    dss_rows = dss.get("modules") or []
    if int(dss.get("expected_count") or 0) != len(dss_rows):
        errors.append("DSS core expected_count must match declared modules")
    for row in dss_rows:
        for required in row.get("required_files") or []:
            if re.search(r"data/stats/.+_gw\d+\.json$", str(required)):
                errors.append(f"DSS active evidence path embeds fixed GW: {row.get('id')}:{required}")

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

    orchestrator_text = (ROOT / "src" / "runtime_v3" / "orchestrator.py").read_text(encoding="utf-8")
    if 'services["collector"]' in orchestrator_text or "critical collector service failed" in orchestrator_text:
        errors.append("orchestrator still special-cases collector")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "service_count": len(service_map),
        "root_services": sorted(name for name, spec in service_map.items() if not (spec.get("depends_on") or [])),
        "active_model_ids": _active_model_ids(),
        "source_registry": sources.get("registry"),
        "service_registry_schema": services.get("schema_version"),
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()
