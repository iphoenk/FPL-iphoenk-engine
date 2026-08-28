from __future__ import annotations
import json
from pathlib import Path
from src.engines.fpl_rules_2026 import CHIPS, DEFCON, MAX_CHIPS_PER_GW, RULESET_ID, SCORING, chip_allowed, chip_half, load_rules_registry, positional_defcon_actions
from src.models.v4_prediction import defcon_expected_points, project_horizon

def check(name, condition, detail=""):
    return {"name": name, "pass": bool(condition), "detail": detail}

def run_audit():
    rules = load_rules_registry()
    checks = [
        check("rules_registry_identity", RULESET_ID == "FPL-2026-27" and rules.get("ruleset") == RULESET_ID),
        check("scoring_registry_loaded", SCORING is rules["scoring"] and SCORING["assist"] == 3 and SCORING["goal_points"]["GK"] == 10),
        check("defcon_gk_veto", DEFCON["GK"]["eligible"] is False and defcon_expected_points(99, 90, 1, 1) == 0.0),
        check("defcon_def_cbit_10", DEFCON["DEF"] == {"eligible": True, "threshold": 10, "metric": "CBIT"}),
        check("defcon_mid_cbirt_12", DEFCON["MID"] == {"eligible": True, "threshold": 12, "metric": "CBIRT"}),
        check("defcon_fwd_cbirt_12", DEFCON["FWD"] == {"eligible": True, "threshold": 12, "metric": "CBIRT"}),
        check("recoveries_excluded_for_def", positional_defcon_actions("DEF",1,1,1,1,10) == 4),
        check("recoveries_included_mid_fwd", positional_defcon_actions("MID",1,1,1,1,10) == 14 and positional_defcon_actions("FWD",1,1,1,1,10) == 14),
        check("defcon_reward_capped_two", 0 <= defcon_expected_points(99,90,2,1) <= 2 and 0 <= defcon_expected_points(99,90,3,1) <= 2),
        check("one_chip_per_gw_constant", MAX_CHIPS_PER_GW == 1),
        check("chip_half_boundary", chip_half(19) == 1 and chip_half(20) == 2),
        check("free_hit_not_gw1", chip_allowed("free_hit",1,[])[0] is False),
        check("free_hit_not_consecutive", chip_allowed("free_hit",20,[{"chip":"free_hit","gw":19}])[0] is False),
        check("chip_once_per_half", chip_allowed("wildcard",10,[{"chip":"wildcard","gw":5}])[0] is False and chip_allowed("wildcard",20,[{"chip":"wildcard","gw":5}])[0] is True),
        check("wc_fh_preserve_banked_ft", CHIPS["wildcard"]["preserve_banked_ft"] is True and CHIPS["free_hit"]["preserve_banked_ft"] is True),
    ]
    p={"id":999,"web_name":"Audit DEF","status":"a","minutes":900,"starts":10,"element_type":2,"expected_goals":"0","expected_assists":"0","bps":0,"defensive_contribution":100}
    fx=[{"event":30,"difficulty":3,"home":True},{"event":30,"difficulty":3,"home":False}]
    r=project_horizon(p,fx,{"recent_starts":[1,1,1,1,1],"def_actions90_prior":20},n=2)
    dc=[x["components"]["defcon"] for x in r["fixtures"]]
    checks.append(check("dgw_defcon_per_match", len(dc)==2 and all(0<=x<=2.001 for x in dc), str(dc)))
    passed=all(x["pass"] for x in checks)
    return {"audit_version":"4.9.6","ruleset":RULESET_ID,"overall":"PASS" if passed else "FAIL","checks":checks}

def main(path="data/compliance_audit.json"):
    out=run_audit(); Path(path).parent.mkdir(parents=True,exist_ok=True); Path(path).write_text(json.dumps(out,indent=2),encoding="utf-8")
    for x in out["checks"]: print(("PASS" if x["pass"] else "FAIL"),x["name"],x["detail"])
    print("OVERALL",out["overall"])
    if out["overall"]!="PASS": raise SystemExit(2)

if __name__=="__main__": main()
