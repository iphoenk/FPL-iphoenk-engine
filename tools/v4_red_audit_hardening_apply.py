from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write_json(path: str, payload: dict) -> None:
    (ROOT / path).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one replacement in {path}, got {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Govern the owned-challenger policy as advisory evidence under one canonical action authority.
policy_path = "config/intelligence/owned_challenger_decision_v4.json"
policy = load_json(policy_path)
policy["schema_version"] = 2
policy["registry"] = "v4_owned_challenger_decision_policy_v2"
policy["decision_authority"] = "CANONICAL_DECISION_ARBITRATION_V1"
policy.setdefault("governance", {}).update({
    "canonical_decision_authority": "CANONICAL_DECISION_ARBITRATION_V1",
    "challenger_states_are_advisory": True,
    "overall_decision_must_equal_canonical_action": True,
})
write_json(policy_path, policy)

# 2) Register the artifact inside the existing optimization boundary. No ninth microservice.
service_path = "config/service_registry.json"
services = load_json(service_path)
services["schema_version"] = 14
services["registry"] = "fpl_v4_9_6_microservice_registry_v14"
optimization = next(row for row in services["services"] if row.get("id") == "optimization")
if "owned_challenger_decision" not in optimization["produces"]:
    optimization["produces"].append("owned_challenger_decision")
services.setdefault("guardrails", {}).update({
    "owned_challenger_inside_optimization_boundary": True,
    "owned_challenger_advisory_only": True,
    "single_canonical_decision_authority": "decision_arbitration",
})
write_json(service_path, services)

# 3) Make the challenger artifact a first-class governed service contract.
contract_path = "config/service_contract_registry.json"
contracts = load_json(contract_path)
contracts["schema_version"] = 11
contracts["registry"] = "fpl_v4_9_6_service_contracts_v11"
contracts.setdefault("contracts", {})["owned_challenger_decision"] = {
    "path": "data/owned_challenger_decision_v4.json",
    "min_schema_version": 2,
    "required_paths": [
        "contract",
        "status",
        "decision_authority",
        "challenge_signal",
        "overall_decision",
        "official_fact_completeness.owned.complete",
        "official_fact_completeness.watchlist.complete",
        "owned_count",
        "governed_watchlist_count",
        "owned_screening",
        "publication.single_canonical_decision_authority",
        "publication.challenge_signal_is_advisory",
        "governance.canonical_decision_authority",
        "governance.overall_decision_must_equal_canonical_action",
    ],
    "equals": {
        "contract": "OWNED_CHALLENGER_DECISION_ENGINE_V1",
        "decision_authority": "CANONICAL_DECISION_ARBITRATION_V1",
        "official_fact_completeness.owned.complete": True,
        "official_fact_completeness.watchlist.complete": True,
        "publication.single_canonical_decision_authority": True,
        "publication.challenge_signal_is_advisory": True,
        "governance.canonical_decision_authority": "CANONICAL_DECISION_ARBITRATION_V1",
        "governance.overall_decision_must_equal_canonical_action": True,
    },
    "min_lengths": {
        "owned_screening": 15,
    },
}
write_json(contract_path, contracts)

# 4) Ownership registry: challenger is evidence owned by optimization, canonical arbitration owns the action.
ownership_path = "config/architecture_ownership_registry.json"
ownership = load_json(ownership_path)
ownership["schema_version"] = 10
ownership["registry"] = "fpl_v4_9_6_architecture_ownership_v10"
comparator = next(row for row in ownership["capability_matrix"] if row.get("capability") == "OWNED_VS_CHALLENGER_COMPARATOR")
comparator.update({
    "input_contract": "15 owned + 20 external watchlist + emerging challenger evidence + multi-horizon predictions",
    "output_artifact": "data/tactical_serving_v4.json comparator evidence + data/owned_challenger_decision_v4.json advisory challenge evidence",
    "consumers": ["package_optimizer", "decision_arbitration", "serving_payload"],
    "duplicates_overlap": "Owned challenger may rank and classify challenge evidence; CANONICAL_DECISION_ARBITRATION alone owns final HOLD/REVIEW/CHANGE action; reporting may not recompute",
})
if not any(row.get("id") == "OWNED_CHALLENGER_EVIDENCE" for row in ownership.get("responsibilities") or []):
    ownership.setdefault("responsibilities", []).append({
        "id": "OWNED_CHALLENGER_EVIDENCE",
        "owner": "optimization",
        "execution_boundary": "optimization",
        "implementation": "src.services.owned_challenger_decision_service",
        "decision_authority": "CANONICAL_DECISION_ARBITRATION_V1",
    })
write_json(ownership_path, ownership)

# 5) Bind all registry identities into the release manifest.
manifest_path = "config/release_manifest.json"
manifest = load_json(manifest_path)
manifest.setdefault("registries", {}).update({
    "services": services["registry"],
    "contracts": contracts["registry"],
    "ownership": ownership["registry"],
    "owned_challenger_policy": policy["registry"],
})
write_json(manifest_path, manifest)

# 6) Owned-challenger runtime artifact must use canonical arbitration for final action.
owned_service = "src/services/owned_challenger_decision_service.py"
replace_once(
    owned_service,
    '    decision_pipeline = read_json(DATA / "decision_pipeline_v4.json", {})\n',
    '    decision_pipeline = read_json(DATA / "decision_pipeline_v4.json", {})\n    decision_arbitration = read_json(DATA / "decision_arbitration_v4.json", {})\n',
)
replace_once(
    owned_service,
    '    execution_authorized = bool(decision_pipeline.get("execution_authorized"))\n    return {\n',
    '    challenge_signal = overall\n    if decision_arbitration.get("contract") != "CANONICAL_DECISION_ARBITRATION_V1":\n        raise RuntimeError("owned challenger requires canonical decision arbitration artifact")\n    canonical_action = str(decision_arbitration.get("overall_action") or "").upper()\n    if canonical_action not in {"HOLD", "REVIEW", "CHANGE", "BLOCKED"}:\n        raise RuntimeError(f"invalid canonical decision action for owned challenger: {canonical_action!r}")\n\n    execution_authorized = bool(decision_pipeline.get("execution_authorized"))\n    return {\n',
)
replace_once(
    owned_service,
    '        "schema_version": 1,\n        "contract": "OWNED_CHALLENGER_DECISION_ENGINE_V1",\n',
    '        "schema_version": 2,\n        "contract": "OWNED_CHALLENGER_DECISION_ENGINE_V1",\n        "decision_authority": "CANONICAL_DECISION_ARBITRATION_V1",\n',
)
replace_once(
    owned_service,
    '        "multi_transfer_packages": multi,\n        "overall_decision": overall,\n',
    '        "multi_transfer_packages": multi,\n        "challenge_signal": challenge_signal,\n        "overall_decision": canonical_action,\n',
)
replace_once(
    owned_service,
    '            "no_false_certainty_for_price_eta": True,\n',
    '            "no_false_certainty_for_price_eta": True,\n            "single_canonical_decision_authority": True,\n            "challenge_signal_is_advisory": True,\n',
)
replace_once(
    owned_service,
    '        "multi_transfer_package_count": len(out.get("multi_transfer_packages") or []),\n        "overall_decision": out.get("overall_decision"),\n',
    '        "multi_transfer_package_count": len(out.get("multi_transfer_packages") or []),\n        "challenge_signal": out.get("challenge_signal"),\n        "overall_decision": out.get("overall_decision"),\n        "decision_authority": out.get("decision_authority"),\n',
)

# 7) Optimization summary must distinguish advisory challenge signal from canonical action.
optimization_service = "src/services/optimization_slo_service.py"
replace_once(
    optimization_service,
    '        "multi_transfer_package_count": len(challenger.get("multi_transfer_packages") or []),\n        "overall_decision": challenger.get("overall_decision"),\n',
    '        "multi_transfer_package_count": len(challenger.get("multi_transfer_packages") or []),\n        "challenge_signal": challenger.get("challenge_signal"),\n        "overall_decision": challenger.get("overall_decision"),\n        "decision_authority": challenger.get("decision_authority"),\n',
)
replace_once(
    optimization_service,
    '        "owned_challenger_status": challenger.get("status"),\n        "owned_challenger_decision": challenger.get("overall_decision"),\n',
    '        "owned_challenger_status": challenger.get("status"),\n        "owned_challenger_signal": challenger.get("challenge_signal"),\n        "canonical_decision": challenger.get("overall_decision"),\n',
)

# 8) Serving composition fails closed on any challenger/canonical disagreement.
composition = "src/engines/v4_challenger_serving_composition.py"
replace_once(
    composition,
    'def _assert_complete(payload: dict[str, Any]) -> None:\n',
    'def _assert_complete(payload: dict[str, Any], *, canonical_action: str) -> None:\n',
)
replace_once(
    composition,
    '    if len(payload.get("owned_screening") or []) != 15:\n        raise RuntimeError("owned challenger serving requires all-15 screening")\n',
    '    if len(payload.get("owned_screening") or []) != 15:\n        raise RuntimeError("owned challenger serving requires all-15 screening")\n    if payload.get("decision_authority") != "CANONICAL_DECISION_ARBITRATION_V1":\n        raise RuntimeError("owned challenger serving requires canonical decision authority")\n    if payload.get("overall_decision") != canonical_action:\n        raise RuntimeError(\n            f"owned challenger canonical action mismatch: challenger={payload.get(\'overall_decision\')} serving={canonical_action}"\n        )\n',
)
replace_once(
    composition,
    '    _assert_complete(challenger)\n\n    main_battles = list(challenger.get("main_transfer_battles") or [])\n',
    '    canonical_action = str(serving.get("overall_action") or "").upper()\n    _assert_complete(challenger, canonical_action=canonical_action)\n\n    main_battles = list(challenger.get("main_transfer_battles") or [])\n',
)
replace_once(
    composition,
    '        "status": challenger.get("status"),\n        "overall_decision": challenger.get("overall_decision"),\n',
    '        "status": challenger.get("status"),\n        "challenge_signal": challenger.get("challenge_signal"),\n        "overall_decision": canonical_action,\n        "decision_authority": challenger.get("decision_authority"),\n        "canonical_authority_consistent": True,\n',
)
replace_once(
    composition,
    '        "owned_challenger_reporting_recompute_forbidden": True,\n',
    '        "owned_challenger_reporting_recompute_forbidden": True,\n        "owned_challenger_challenge_signal_advisory_only": True,\n        "single_canonical_decision_authority": True,\n',
)
replace_once(
    composition,
    '            "main_transfer_battles_published": True,\n            "reporting_recompute": False,\n',
    '            "main_transfer_battles_published": True,\n            "reporting_recompute": False,\n            "challenge_signal": challenger.get("challenge_signal"),\n            "canonical_action": canonical_action,\n            "canonical_authority_consistent": True,\n            "decision_authority": challenger.get("decision_authority"),\n',
)
replace_once(
    composition,
    '        "multi_transfer_packages": len(multi_packages),\n        "overall_decision": challenger.get("overall_decision"),\n',
    '        "multi_transfer_packages": len(multi_packages),\n        "challenge_signal": challenger.get("challenge_signal"),\n        "overall_decision": canonical_action,\n',
)

# 9) Architecture attestation must include challenger policy and explicitly validate the single authority wiring.
arch = "src/services/architecture_guard_service.py"
replace_once(
    arch,
    '    CONFIG / "release_manifest.json",\n)\n',
    '    CONFIG / "release_manifest.json",\n    CONFIG / "intelligence/owned_challenger_decision_v4.json",\n)\n',
)
replace_once(
    arch,
    '    release = read_json(CONFIG / "release_manifest.json", {})\n    checks: dict[str, tuple[bool, list | str]] = {}\n',
    '    release = read_json(CONFIG / "release_manifest.json", {})\n    challenger_policy = read_json(CONFIG / "intelligence/owned_challenger_decision_v4.json", {})\n    checks: dict[str, tuple[bool, list | str]] = {}\n',
)
anchor = '    checks["capability_matrix_overlap_actions_governed"] = (not invalid_actions, invalid_actions)\n\n'
insert = '''    checks["capability_matrix_overlap_actions_governed"] = (not invalid_actions, invalid_actions)\n\n    optimization_row = next((row for row in service_rows if row.get("id") == "optimization"), {})\n    challenger_contract = contract_specs.get("owned_challenger_decision") or {}\n    challenger_responsibility = next((row for row in responsibilities if row.get("id") == "OWNED_CHALLENGER_EVIDENCE"), {})\n    challenger_authority_ok = (\n        challenger_policy.get("decision_authority") == "CANONICAL_DECISION_ARBITRATION_V1"\n        and (challenger_policy.get("governance") or {}).get("canonical_decision_authority") == "CANONICAL_DECISION_ARBITRATION_V1"\n        and "owned_challenger_decision" in (optimization_row.get("produces") or [])\n        and challenger_contract.get("path") == "data/owned_challenger_decision_v4.json"\n        and (challenger_contract.get("equals") or {}).get("decision_authority") == "CANONICAL_DECISION_ARBITRATION_V1"\n        and challenger_responsibility.get("owner") == "optimization"\n        and challenger_responsibility.get("decision_authority") == "CANONICAL_DECISION_ARBITRATION_V1"\n    )\n    checks["owned_challenger_single_decision_authority"] = (\n        challenger_authority_ok,\n        [] if challenger_authority_ok else [{\n            "policy": challenger_policy.get("decision_authority"),\n            "service_produces": optimization_row.get("produces") or [],\n            "contract": challenger_contract,\n            "responsibility": challenger_responsibility,\n        }],\n    )\n\n'''
replace_once(arch, anchor, insert)
replace_once(
    arch,
    '        and registries.get("ownership") == ownership.get("registry")\n    )\n',
    '        and registries.get("ownership") == ownership.get("registry")\n        and registries.get("owned_challenger_policy") == challenger_policy.get("registry")\n    )\n',
)
replace_once(
    arch,
    '            "moving_operational_identity_single_owner": True,\n',
    '            "moving_operational_identity_single_owner": True,\n            "owned_challenger_single_decision_authority": True,\n',
)

# 10) Production publication verification explicitly checks the challenger artifact and canonical consistency.
core = ".github/workflows/fpl-engine-core.yml"
replace_once(
    core,
    '          git cat-file -e "origin/${RUNTIME_BRANCH}:data/serving_benchmark_v4.json"\n',
    '          git cat-file -e "origin/${RUNTIME_BRANCH}:data/serving_benchmark_v4.json"\n          git cat-file -e "origin/${RUNTIME_BRANCH}:data/owned_challenger_decision_v4.json"\n',
)
replace_once(
    core,
    "          ablation=json.loads(subprocess.check_output(['git','show','origin/runtime-data-v4:data/advanced_ablation_v4.json'],text=True))\n",
    "          challenger=json.loads(subprocess.check_output(['git','show','origin/runtime-data-v4:data/owned_challenger_decision_v4.json'],text=True))\n          serving=json.loads(subprocess.check_output(['git','show','origin/runtime-data-v4:data/serving_payload_v4.json'],text=True))\n          assert challenger.get('decision_authority') == 'CANONICAL_DECISION_ARBITRATION_V1', challenger\n          assert challenger.get('overall_decision') == serving.get('overall_action'), (challenger, serving.get('overall_action'))\n          assert (challenger.get('publication') or {}).get('single_canonical_decision_authority') is True, challenger\n          assert ((serving.get('owned_challenger_decision') or {}).get('canonical_authority_consistent')) is True, serving.get('owned_challenger_decision')\n          ablation=json.loads(subprocess.check_output(['git','show','origin/runtime-data-v4:data/advanced_ablation_v4.json'],text=True))\n",
)

# 11) Dedicated QA/QC regression suite for the two audit-red conditions.
test_path = ROOT / "tests/test_v4_owned_challenger_authority_governance.py"
test_path.write_text('''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\nimport pytest\n\nfrom src.engines.v4_challenger_serving_composition import _assert_complete\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef _load(path: str) -> dict:\n    return json.loads((ROOT / path).read_text(encoding="utf-8"))\n\n\ndef _complete_payload(**overrides):\n    payload = {\n        "contract": "OWNED_CHALLENGER_DECISION_ENGINE_V1",\n        "status": "READY",\n        "decision_authority": "CANONICAL_DECISION_ARBITRATION_V1",\n        "overall_decision": "REVIEW",\n        "official_fact_completeness": {\n            "owned": {"actual": 15, "complete": True},\n            "watchlist": {"actual": 20, "complete": True},\n        },\n        "owned_screening": [{"element": index + 1} for index in range(15)],\n    }\n    payload.update(overrides)\n    return payload\n\n\ndef test_serving_rejects_second_decision_authority():\n    _assert_complete(_complete_payload(), canonical_action="REVIEW")\n    with pytest.raises(RuntimeError, match="canonical action mismatch"):\n        _assert_complete(_complete_payload(overall_decision="REVIEW_NOW"), canonical_action="REVIEW")\n    with pytest.raises(RuntimeError, match="canonical decision authority"):\n        _assert_complete(_complete_payload(decision_authority="OWNED_CHALLENGER"), canonical_action="REVIEW")\n\n\ndef test_owned_challenger_policy_is_release_and_attestation_governed():\n    policy = _load("config/intelligence/owned_challenger_decision_v4.json")\n    manifest = _load("config/release_manifest.json")\n    services = _load("config/service_registry.json")\n    contracts = _load("config/service_contract_registry.json")\n    ownership = _load("config/architecture_ownership_registry.json")\n    assert manifest["registries"]["owned_challenger_policy"] == policy["registry"]\n    optimization = next(row for row in services["services"] if row["id"] == "optimization")\n    assert "owned_challenger_decision" in optimization["produces"]\n    contract = contracts["contracts"]["owned_challenger_decision"]\n    assert contract["path"] == "data/owned_challenger_decision_v4.json"\n    assert contract["equals"]["decision_authority"] == "CANONICAL_DECISION_ARBITRATION_V1"\n    responsibility = next(row for row in ownership["responsibilities"] if row["id"] == "OWNED_CHALLENGER_EVIDENCE")\n    assert responsibility["decision_authority"] == "CANONICAL_DECISION_ARBITRATION_V1"\n    architecture_source = (ROOT / "src/services/architecture_guard_service.py").read_text(encoding="utf-8")\n    assert 'CONFIG / "intelligence/owned_challenger_decision_v4.json"' in architecture_source\n    assert 'checks["owned_challenger_single_decision_authority"]' in architecture_source\n''', encoding="utf-8")

print("V4 red-audit hardening migration applied")
