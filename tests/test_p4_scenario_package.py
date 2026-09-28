from copy import deepcopy
import pytest
from src.engines.v12_scenario_package import ScenarioPackageError, base_fingerprint, build_scenario_package, resolve_scenario, validate_package_for_dependencies

OWNED=list(range(1,16))
DEPS={"model_version":"v12","our15_fingerprint":"our15-a","fixture_gw_fingerprint":"gw6-a","projection_lineage_fingerprint":"proj-a","cache_schema_version":"6","mc_authority":"V12_MC_500K_CRN","owner_context_fingerprint":"owner-a"}
def base():
    return {"decision_surfaces":{"S06":{"xi":list(range(1,12)),"bench":[12,13,14,15]},"S08":{"captain":1,"vice":2},"S09":{"chip":"NONE"},"S14":{"route":"HOLD"},"S19":{"action":"WAIT"}}}
def evaluate(overrides):
    out=deepcopy(base()); e=int(next(iter(overrides)))
    out["decision_surfaces"]["S06"]={"xi":[x for x in range(1,12) if x!=e],"bench":[12,13,14,15,e]}
    if e==1: out["decision_surfaces"]["S08"]={"captain":2,"vice":3}
    out["decision_surfaces"]["S19"]={"action":"PREPARE"}; return out
def build(**kw):
    return build_scenario_package(dependencies=DEPS,base_result=base(),owned_elements=OWNED,evaluate=evaluate,generated_at="2026-09-28T02:05:00Z",captain_element=1,vice_element=2,**kw)
def test_exact_package_and_base_equality():
    p=build(); assert p["private_only"] and not p["second_model_created"]; assert p["scenario_count"]==18
    assert resolve_scenario(p,scenario_id="BASE_CURRENT15",dependencies=DEPS)["decision_surfaces"]==base()["decision_surfaces"]
    assert resolve_scenario(p,scenario_id="UNAVAILABLE_1",dependencies=DEPS)["decision_surfaces"]==evaluate({"1":{"override_type":"OWNED_UNAVAILABLE","p_available":0.0}})["decision_surfaces"]
    assert resolve_scenario(p,scenario_id="CAPTAIN_UNAVAILABLE",dependencies=DEPS)["decision_surfaces"]==evaluate({"1":{"override_type":"CAPTAIN_UNAVAILABLE","p_available":0.0}})["decision_surfaces"]
def test_deterministic_fingerprint():
    assert build()["package_fingerprint"]==build()["package_fingerprint"]
def test_every_material_dependency_invalidates():
    p=build()
    for key in DEPS:
        changed=dict(DEPS); changed[key]=changed[key]+"-changed"
        assert validate_package_for_dependencies(p,dependencies=changed)["status"]=="MISS_RECOMPUTE"
        with pytest.raises(ScenarioPackageError,match="fail closed"): resolve_scenario(p,scenario_id="BASE_CURRENT15",dependencies=changed)
def test_missing_dependency_fails_closed():
    bad=dict(DEPS); bad.pop("owner_context_fingerprint")
    with pytest.raises(ScenarioPackageError,match="missing P4 base dependencies"): base_fingerprint(bad)
def test_current15_and_gw_changes_rejected():
    p=build()
    for key in ("our15_fingerprint","fixture_gw_fingerprint","projection_lineage_fingerprint","model_version"):
        d=dict(DEPS); d[key]="different"
        assert validate_package_for_dependencies(p,dependencies=d)["current"] is False
def test_wrong_owner_context_rejected():
    p=build(); d=dict(DEPS); d["owner_context_fingerprint"]="other-owner"
    with pytest.raises(ScenarioPackageError): resolve_scenario(p,scenario_id="UNAVAILABLE_1",dependencies=d)
