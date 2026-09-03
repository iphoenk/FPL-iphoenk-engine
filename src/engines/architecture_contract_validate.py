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
WEATHER_POLICY = ROOT / "config" / "intelligence" / "weather_context.json"
VENUE_REGISTRY = ROOT / "config" / "venues" / "premier_league_2026_27.json"
REPORT_REGISTRY = ROOT / "config" / "report_artifact_registry.json"
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
    weather_policy = _load(WEATHER_POLICY)
    venues = _load(VENUE_REGISTRY)
    report_registry = _load(REPORT_REGISTRY)
    framework_registries = {
        "dss_core": _load(DSS_CORE),
        "dss_extensions": _load(DSS_EXT),
        "enhancements": _load(ENHANCEMENTS),
        "gate0": _load(GATE0),
    }
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    if (ROOT / "config" / "sources.json").exists():
        errors.append("legacy config/sources.json must not exist")

    if sources.get("registry") != "SOURCE_REGISTRY_V4":
        errors.append("canonical source registry must be SOURCE_REGISTRY_V4")
    source_policy = sources.get("policy") or {}
    for key in (
        "source_network_locations_are_registry_owned",
        "source_ingestion_timeouts_are_registry_owned",
        "weather_is_advisory_enrichment_only",
    ):
        if source_policy.get(key) is not True:
            errors.append(f"source policy missing {key}=true")
    source_rows = {str(row.get("id")): row for row in sources.get("sources") or []}
    weather_source = source_rows.get("open_meteo") or {}
    if (
        weather_source.get("class") != "ENRICHMENT"
        or weather_source.get("critical") is not False
        or weather_source.get("adapter") != "weather_artifact"
    ):
        errors.append("open_meteo must be noncritical WEATHER_ENRICHMENT via weather_artifact")
    for row in sources.get("sources") or []:
        for path in row.get("artifact_paths") or []:
            if re.search(r"_gw\d+\.json$", str(path)):
                errors.append(f"active source artifact embeds fixed GW: {row.get('id')}:{path}")

    weather_governance = weather_policy.get("governance") or {}
    if weather_governance.get("advisory_only") is not True:
        errors.append("weather must remain advisory_only")
    for key in (
        "may_directly_change_xpts",
        "may_directly_change_xmins",
        "may_directly_change_starting_xi",
        "may_directly_change_bench_order",
        "may_directly_change_captaincy",
        "may_directly_change_vice_captaincy",
        "may_directly_change_transfer_decision",
        "may_directly_change_hit_decision",
        "may_directly_change_chip_decision",
        "may_directly_change_watchlist_membership",
    ):
        if weather_governance.get(key) is not False:
            errors.append(f"weather decision mutation must remain false: {key}")
    if weather_governance.get("rain_probability_is_not_rain_intensity") is not True:
        errors.append("weather policy must distinguish rain probability from intensity")
    if weather_governance.get("post_match_attribution_label") != "POSSIBLE_CONTRIBUTING_FACTOR":
        errors.append("weather attribution must remain POSSIBLE_CONTRIBUTING_FACTOR")
    if weather_governance.get("causal_claim_requires_calibrated_evidence") is not True:
        errors.append("weather causality must require calibrated evidence")
    venue_rows = venues.get("venues") or []
    venue_names = [str(row.get("team_name") or "") for row in venue_rows]
    if len(venue_rows) < 20 or len(venue_names) != len(set(venue_names)) or any(not name for name in venue_names):
        errors.append("venue registry must contain unique current PL team names")

    if artifact_contracts.get("registry") != "RUNTIME_ARTIFACT_CONTRACTS_V2":
        errors.append("runtime artifact contract registry must be RUNTIME_ARTIFACT_CONTRACTS_V2")
    artifact_policy = artifact_contracts.get("policy") or {}
    for key in (
        "validate_declared_json_before_acceptance",
        "validate_latest_sidecar_when_present",
        "malformed_json_is_integrity_failure",
        "valid_empty_external_observations_are_allowed",
        "valid_empty_weather_window_is_allowed",
    ):
        if artifact_policy.get(key) is not True:
            errors.append(f"runtime artifact policy missing {key}=true")
    challenger_contract = (artifact_contracts.get("contracts") or {}).get("challenger_observations.json") or {}
    if (
        (challenger_contract.get("equals") or {}).get("schema_version") != 2
        or (challenger_contract.get("equals") or {}).get("contract") != "challenger_observation_v2"
        or (challenger_contract.get("types") or {}).get("observations") != "list"
    ):
        errors.append("challenger_observations artifact contract drift")
    weather_contract = (artifact_contracts.get("contracts") or {}).get("fixture_weather.json") or {}
    if (
        (weather_contract.get("equals") or {}).get("schema_version") != 2
        or (weather_contract.get("equals") or {}).get("model") != "weather_context_governed_v2"
        or (weather_contract.get("types") or {}).get("fixtures") != "list"
    ):
        errors.append("fixture_weather artifact contract missing or invalid")
    weather_context_contract = (artifact_contracts.get("contracts") or {}).get("weather_context.json") or {}
    if (
        (weather_context_contract.get("equals") or {}).get("contract") != "WEATHER_CONTEXT_V3_V1"
        or (weather_context_contract.get("equals") or {}).get("owner") != "weather_context"
    ):
        errors.append("weather_context artifact contract missing or invalid")
    weather_health_contract = (artifact_contracts.get("contracts") or {}).get("weather_context_health.json") or {}
    if (
        (weather_health_contract.get("equals") or {}).get("contract") != "WEATHER_CONTEXT_HEALTH_V1"
        or (weather_health_contract.get("equals") or {}).get("decision_blocking") is not False
    ):
        errors.append("weather_context_health artifact contract missing or invalid")

    report_contract = report_registry.get("consumer_contract") or {}
    if report_registry.get("registry") != "REPORT_ARTIFACT_REGISTRY_V3":
        errors.append("report artifact registry must be V3")
    for key in (
        "owned_rows_require_current_gw_xpts",
        "owned_rows_require_lineup_status",
        "owned_rows_require_choice_state",
        "model_validation_required",
        "weather_context_required",
    ):
        if report_contract.get(key) is not True:
            errors.append(f"report transparency contract missing {key}=true")

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
    for key in (
        "generic_root_service_scheduling",
        "service_boundaries_follow_artifact_ownership_not_file_size",
        "single_owner_for_standard_official_network_fetches",
        "declared_json_artifacts_are_validated_before_acceptance",
        "artifact_contract_registry_owned",
        "malformed_internal_artifact_is_integrity_failure",
        "valid_empty_external_observations_remain_fail_soft",
        "weather_acquisition_lives_inside_source_layer",
        "weather_context_is_separate_governed_enrichment_capability",
        "weather_is_observational_and_advisory_only",
        "weather_never_directly_mutates_xpts_xmins_or_decisions",
        "weather_context_health_propagates_to_framework",
    ):
        if policy.get(key) is not True:
            errors.append(f"service policy missing {key}=true")

    source_service = service_map.get("source_layer") or {}
    if "official_snapshot.json" not in (source_service.get("inputs") or []) or "fixture_weather.json" not in (source_service.get("artifacts") or []):
        errors.append("source_layer must own weather acquisition while consuming Official snapshot")
    weather_service = service_map.get("weather_context") or {}
    weather_modules = [str(command.get("module")) for command in weather_service.get("commands") or [] if command.get("module")]
    if weather_modules != ["src.engines.weather_context"]:
        errors.append("weather_context capability must be materialized by src.engines.weather_context")
    if set(weather_service.get("depends_on") or []) != {"source_layer", "tactical_context"}:
        errors.append("weather_context capability dependency drift")
    if set(weather_service.get("artifacts") or []) != {"weather_context.json", "weather_context_health.json"}:
        errors.append("weather_context capability artifact ownership drift")
    if "fixture_weather.json" in (weather_service.get("artifacts") or []):
        errors.append("weather_context must consume, not reacquire, fixture_weather")
    if "fixture_weather.json" not in (weather_service.get("inputs") or []):
        errors.append("weather_context must consume governed fixture_weather evidence")

    prediction_service = service_map.get("prediction") or {}
    forbidden_weather_inputs = {"fixture_weather.json", "weather_context.json", "weather_context_health.json"}
    if forbidden_weather_inputs & set(prediction_service.get("inputs") or []):
        errors.append("prediction must not consume weather artifacts as direct xPts/xMins inputs")
    if "weather_context" not in (prediction_service.get("depends_on") or []):
        errors.append("prediction must wait for governed weather enrichment before normal model chain")
    for decision_service_name in ("lineup_governance", "watchlist"):
        if forbidden_weather_inputs & set((service_map.get(decision_service_name) or {}).get("inputs") or []):
            errors.append(f"{decision_service_name} must not consume weather artifacts directly")

    report_service = service_map.get("report_materializer") or {}
    report_modules = [str(command.get("module")) for command in report_service.get("commands") or [] if command.get("module")]
    expected_order = ["src.engines.report_materializer", "src.engines.report_transparency_overlay", "src.engines.report_serving_validate"]
    if report_modules != expected_order:
        errors.append(f"report materializer command order drift: {report_modules}")
    if not {"weather_context.json", "weather_context_health.json"}.issubset(set(report_service.get("inputs") or [])):
        errors.append("report serving must receive governed weather context and health")

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
    if re.search(r"\bmargin\s*(?:<|<=|>|>=)\s*\d+(?:\.\d+)?\b", lineup_text):
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
    if (ROOT / ".github" / "workflows" / "deep-stats.yml").exists():
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
        "report_artifact_registry": report_registry.get("registry"),
        "weather_source": weather_source.get("id"),
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()
