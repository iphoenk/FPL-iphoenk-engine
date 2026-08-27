from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.v5 import V5_VERSION
from src.v5.config_cache import load_json_config
from src.v5.release_integrity import runtime_fingerprint

MANIFEST_CONFIG="config/v5_convergence_manifest.json"; PARITY_CONFIG="config/v5_shadow_parity_registry.json"; ACCEPTANCE_CONFIG="config/v5_acceptance_registry.json"
def _load(path:Path)->dict[str,Any]:
    with open(path,encoding="utf-8") as fh:data=json.load(fh)
    if not isinstance(data,dict):raise RuntimeError(f"expected object in {path}")
    return data
def _atomic_write(path:Path,payload:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp"); tmp.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8"); tmp.replace(path)
def _baseline()->tuple[str,str]:
    b=load_json_config(MANIFEST_CONFIG).get("baselines") or {}; return str(b.get("production_truth") or ""),str(b.get("production_main_sha") or "")
def _required_cycles()->int:return int(load_json_config(PARITY_CONFIG).get("required_cycles_before_production_candidate") or 3)
def _accounting_policy()->dict[str,Any]:
    raw=load_json_config(PARITY_CONFIG).get("acceptance_accounting"); return raw if isinstance(raw,dict) else {}
def _prediction_policy()->dict[str,Any]:
    raw=load_json_config(ACCEPTANCE_CONFIG).get("prediction_calibration_gate"); return raw if isinstance(raw,dict) else {}
def _current_release_fingerprint()->str:return str(runtime_fingerprint()["fingerprint"])
def _normalized_v3(version:str)->str:return version.removeprefix("v")
def validated_cycle_eligible(payload:dict[str,Any])->bool:
    baseline_version,baseline_sha=_baseline(); policy=_accounting_policy(); acceptance=payload.get("acceptance_progress") if isinstance(payload.get("acceptance_progress"),dict) else {}; post=payload.get("post_validation") if isinstance(payload.get("post_validation"),dict) else {}; context=payload.get("acceptance_context") if isinstance(payload.get("acceptance_context"),dict) else {}; v3=payload.get("v3") if isinstance(payload.get("v3"),dict) else {}; v5=payload.get("v5") if isinstance(payload.get("v5"),dict) else {}; invariants=payload.get("operational_invariants") if isinstance(payload.get("operational_invariants"),dict) else {}; parity=payload.get("parity") if isinstance(payload.get("parity"),dict) else {}
    if str(payload.get("mode") or "")!="REAL_SHADOW" or acceptance.get("cycle_pass") is not True:return False
    if policy.get("require_post_validation_pass",True) and post.get("status")!="PASS":return False
    if invariants.get("pass") is not True or parity.get("pass") is not True:return False
    if policy.get("require_same_v5_version",True) and str(v5.get("engine_version") or "")!=V5_VERSION:return False
    if policy.get("require_same_production_baseline",True) and (str(v3.get("engine_version") or "")!=_normalized_v3(baseline_version) or str(context.get("production_baseline_version") or "")!=baseline_version or str(context.get("production_main_sha") or "")!=baseline_sha):return False
    if policy.get("require_same_release_fingerprint",True) and str(context.get("release_fingerprint") or "")!=_current_release_fingerprint():return False
    return True
def _validated_cycles(cycles_dir:Path)->list[dict[str,Any]]:
    rows=[]; seen=set()
    for path in sorted(cycles_dir.glob("*.json")):
        try:payload=_load(path)
        except Exception:continue
        cycle_id=str(payload.get("cycle_id") or path.stem)
        if cycle_id in seen or not validated_cycle_eligible(payload):continue
        seen.add(cycle_id); rows.append({"cycle_id":cycle_id,"generated_at":payload.get("generated_at"),"validated_at":(payload.get("post_validation") or {}).get("validated_at"),"v3_engine_version":(payload.get("v3") or {}).get("engine_version"),"v5_engine_version":(payload.get("v5") or {}).get("engine_version"),"release_fingerprint":(payload.get("acceptance_context") or {}).get("release_fingerprint")})
    return rows
def _prediction_accuracy_path(out:Path)->Path:return (out.parent if out.name=="shadow" else out)/"prediction_accuracy.json"
def _prediction_acceptance(out:Path)->dict[str,Any]:
    policy=_prediction_policy(); path=_prediction_accuracy_path(out)
    if not path.exists():return {"eligible":False,"status":"NO_PREDICTION_ACCURACY_ARTIFACT","path":str(path),"checks":{}}
    accuracy=_load(path); overall=accuracy.get("overall") if isinstance(accuracy.get("overall"),dict) else {}; settled=accuracy.get("settled_gameweeks") if isinstance(accuracy.get("settled_gameweeks"),list) else []; metrics=overall; required_metrics=[str(x) for x in policy.get("required_metrics") or []]
    checks={"settled_gameweeks":len(settled)>=int(policy.get("minimum_settled_gameweeks") or 0),"player_gw_samples":int(overall.get("sample_size") or 0)>=int(policy.get("minimum_player_gw_samples") or 0),"starter_samples":int(overall.get("starter_sample_size") or 0)>=int(policy.get("minimum_starter_samples") or 0),"clean_sheet_samples":int(overall.get("clean_sheet_sample_size") or 0)>=int(policy.get("minimum_clean_sheet_samples") or 0),"required_metrics_present":all(metrics.get(name) is not None for name in required_metrics)}
    if bool(policy.get("require_temporal_guard_pass",True)):checks["temporal_guard_pass"]=(accuracy.get("temporal_guard") or {}).get("status")=="PASS"
    if bool(policy.get("require_non_regression_vs_frozen_baseline",False)):checks["frozen_baseline_non_regression"]=(accuracy.get("baseline_comparison") or {}).get("non_regression_pass") is True
    eligible=all(checks.values()) if checks else not bool(policy.get("required_for_production_promotion",True)); return {"eligible":eligible,"status":"PASS" if eligible else "INSUFFICIENT_OR_UNPROVEN_SETTLED_EVIDENCE","path":str(path),"checks":checks,"settled_gameweeks":len(settled),"sample_size":int(overall.get("sample_size") or 0),"confidence":accuracy.get("confidence")}
def finalize(latest_path:str,output_dir:str)->dict[str,Any]:
    latest_file,out=Path(latest_path),Path(output_dir); payload=_load(latest_file); acceptance=payload.get("acceptance_progress") if isinstance(payload.get("acceptance_progress"),dict) else {}
    if acceptance.get("cycle_pass") is not True:raise RuntimeError("cannot post-validate a shadow cycle that failed core parity/invariants")
    baseline_version,baseline_sha=_baseline(); context=payload.get("acceptance_context") if isinstance(payload.get("acceptance_context"),dict) else {}; current_fingerprint=_current_release_fingerprint()
    if str((payload.get("v5") or {}).get("engine_version") or "")!=V5_VERSION:raise RuntimeError("shadow cycle V5 version does not match current package version")
    if str(context.get("production_baseline_version") or "")!=baseline_version or str(context.get("production_main_sha") or "")!=baseline_sha:raise RuntimeError("shadow cycle production baseline does not match convergence manifest")
    if str(context.get("release_fingerprint") or "")!=current_fingerprint:raise RuntimeError("shadow cycle release fingerprint does not match current runtime")
    validated_at=datetime.now(timezone.utc).isoformat(); payload["post_validation"]={"status":"PASS","validated_at":validated_at,"validator_contract":"V5_REAL_SHADOW_POSTVALIDATION_V3","workflow_run_number":os.getenv("GITHUB_RUN_NUMBER"),"workflow_run_id":os.getenv("GITHUB_RUN_ID"),"source_commit":os.getenv("GITHUB_SHA"),"release_fingerprint":current_fingerprint}; acceptance.update({"post_validation_required":True,"post_validation_status":"PASS","counts_as_successful_acceptance_cycle":True,"production_candidate_auto_promoted":False}); payload["acceptance_progress"]=acceptance; cycle_id=str(payload.get("cycle_id") or "")
    if not cycle_id:raise RuntimeError("shadow cycle_id missing")
    cycle_path=out/"cycles"/f"{cycle_id}.json"; _atomic_write(cycle_path,payload); _atomic_write(latest_file,payload); validated=_validated_cycles(out/"cycles"); required,count=_required_cycles(),len(validated); operational=count>=required; prediction=_prediction_acceptance(out); prediction_required=bool(_accounting_policy().get("require_prediction_acceptance_for_production_candidate",True)); eligible=operational and (prediction.get("eligible") is True or not prediction_required); summary={"schema_version":3,"model":"v5_postvalidated_shadow_acceptance_v3","generated_at":validated_at,"v5_version":V5_VERSION,"release_fingerprint":current_fingerprint,"production_baseline_version":baseline_version,"production_main_sha":baseline_sha,"required_validated_cycles":required,"validated_successful_cycles":count,"remaining_validated_cycles":max(0,required-count),"operational_candidate_eligible":operational,"prediction_candidate_eligible":prediction.get("eligible") is True,"prediction_acceptance":prediction,"production_candidate_eligible":eligible,"production_candidate_auto_promoted":False,"production_promotion_requires_explicit_manual_action":True,"validated_cycles":validated}; payload["acceptance_progress"].update({"validated_successful_cycles":count,"remaining_validated_cycles":max(0,required-count),"operational_candidate_eligible":operational,"prediction_candidate_eligible":prediction.get("eligible") is True,"production_candidate_eligible":eligible}); _atomic_write(cycle_path,payload); _atomic_write(latest_file,payload); _atomic_write(out/"acceptance_summary.json",summary); print(json.dumps(summary,ensure_ascii=False)); return summary
def cli()->None:
    parser=argparse.ArgumentParser(description="Finalize postvalidated V5 real-shadow acceptance accounting"); parser.add_argument("--latest",default="data/v5/shadow/latest_shadow_cycle.json"); parser.add_argument("--output-dir",default="data/v5/shadow"); args=parser.parse_args(); finalize(args.latest,args.output_dir)
if __name__=="__main__":cli()
