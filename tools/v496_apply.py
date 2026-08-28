from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, text: str) -> None:
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.rstrip() + "\n", encoding="utf-8")


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def dump(path: str, obj) -> None:
    write(path, json.dumps(obj, ensure_ascii=False, indent=2))


RELEASE = "4.9.6"

# 1) Canonical release source.
dump("config/release_manifest.json", {
    "schema_version": 1,
    "release": RELEASE,
    "track": "V4",
    "status": "ARCHITECTURE_CONSOLIDATION",
    "canonical_branch": "v4-prediction-engine",
    "architecture": "process_isolated_dag_parallel_single_host",
    "ruleset": "FPL-2026-27",
    "registries": {
        "services": "fpl_v4_9_6_microservice_registry_v9",
        "contracts": "fpl_v4_9_6_service_contracts_v7",
        "ownership": "fpl_v4_9_6_architecture_ownership_v1"
    }
})

# 2) Canonical FPL rules registry: constants live here, not copied across Python modules.
dump("config/fpl_rules_2026_27.json", {
    "schema_version": 1,
    "ruleset": "FPL-2026-27",
    "squad": {
        "size": 15,
        "positions": {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3},
        "max_per_club": 3,
        "budget_tenths": 1000,
        "legal_formations": ["3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1"]
    },
    "scoring": {
        "goal_points": {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4},
        "assist": 3,
        "clean_sheet": {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0},
        "appearance_under_60": 1,
        "appearance_60_plus": 2,
        "saves_per_point": 3,
        "penalty_save": 5,
        "bonus": [1, 2, 3],
        "yellow_card": -1,
        "red_card": -3,
        "own_goal": -2,
        "penalty_miss": -2,
        "goals_conceded_per_minus_point": 2,
        "defcon_points": 2
    },
    "defcon": {
        "GK": {"eligible": False, "threshold": None, "metric": None},
        "DEF": {"eligible": True, "threshold": 10, "metric": "CBIT"},
        "MID": {"eligible": True, "threshold": 12, "metric": "CBIRT"},
        "FWD": {"eligible": True, "threshold": 12, "metric": "CBIRT"}
    },
    "chips": {
        "wildcard": {"per_half": 1, "gw1_allowed": True, "preserve_banked_ft": True},
        "bench_boost": {"per_half": 1, "gw1_allowed": True, "preserve_banked_ft": True},
        "free_hit": {"per_half": 1, "gw1_allowed": False, "preserve_banked_ft": True},
        "triple_captain": {"per_half": 1, "gw1_allowed": True, "preserve_banked_ft": True}
    },
    "chip_policy": {"first_half_last_gw": 19, "second_half_first_gw": 20, "max_chips_per_gw": 1}
})

write("src/release.py", '''from __future__ import annotations
from functools import lru_cache
from src.utils import CONFIG, read_json

@lru_cache(maxsize=1)
def release_manifest() -> dict:
    manifest = read_json(CONFIG / "release_manifest.json", {})
    if not manifest.get("release"):
        raise RuntimeError("release manifest missing release")
    return manifest

RELEASE_VERSION = str(release_manifest()["release"])
''')

write("src/engines/fpl_rules_2026.py", '''from __future__ import annotations
from functools import lru_cache
from src.utils import CONFIG, read_json

@lru_cache(maxsize=1)
def load_rules_registry() -> dict:
    rules = read_json(CONFIG / "fpl_rules_2026_27.json", {})
    if rules.get("ruleset") != "FPL-2026-27":
        raise RuntimeError("unexpected FPL ruleset")
    for key in ("squad", "scoring", "defcon", "chips", "chip_policy"):
        if key not in rules:
            raise RuntimeError(f"FPL rules registry missing {key}")
    return rules

_RULES = load_rules_registry()
RULESET_ID = str(_RULES["ruleset"])
SCORING = _RULES["scoring"]
DEFCON = _RULES["defcon"]
CHIPS = _RULES["chips"]
POSITION_COUNTS = _RULES["squad"]["positions"]
BUDGET_TENTHS = int(_RULES["squad"]["budget_tenths"])
MAX_PER_CLUB = int(_RULES["squad"]["max_per_club"])
LEGAL_FORMATIONS = frozenset(_RULES["squad"]["legal_formations"])
LEGAL_FORMATION_TUPLES = tuple(tuple(int(x) for x in form.split("-")) for form in _RULES["squad"]["legal_formations"])
FIRST_HALF_LAST_GW = int(_RULES["chip_policy"]["first_half_last_gw"])
SECOND_HALF_FIRST_GW = int(_RULES["chip_policy"]["second_half_first_gw"])
MAX_CHIPS_PER_GW = int(_RULES["chip_policy"]["max_chips_per_gw"])

def chip_half(gw: int) -> int:
    return 1 if int(gw) <= FIRST_HALF_LAST_GW else 2

def chip_allowed(chip: str, gw: int, used: list[dict] | None = None) -> tuple[bool, str]:
    used = used or []
    if chip not in CHIPS:
        return False, "unknown_chip"
    gw = int(gw)
    rule = CHIPS[chip]
    if gw == 1 and not rule["gw1_allowed"]:
        return False, "chip_not_allowed_gw1"
    if any(int(x.get("gw", -1)) == gw for x in used):
        return False, "one_chip_per_gw"
    half = chip_half(gw)
    same = [x for x in used if x.get("chip") == chip and chip_half(int(x.get("gw", 0))) == half]
    if len(same) >= int(rule["per_half"]):
        return False, "chip_already_used_this_half"
    if chip == "free_hit":
        fh_gws = [int(x.get("gw", -99)) for x in used if x.get("chip") == "free_hit"]
        if any(abs(gw - x) == 1 for x in fh_gws):
            return False, "free_hit_not_consecutive"
    return True, "ok"

def defcon_rule(position: str) -> dict:
    return DEFCON[position]

def positional_defcon_actions(position: str, clearances=0, blocks=0, interceptions=0, tackles=0, recoveries=0) -> float:
    base = float(clearances) + float(blocks) + float(interceptions) + float(tackles)
    if position in {"MID", "FWD"}:
        base += float(recoveries)
    if position == "GK":
        return 0.0
    return base
''')

write("src/engines/fpl_legality.py", '''from __future__ import annotations
from collections.abc import Iterable
from src.engines.fpl_rules_2026 import LEGAL_FORMATIONS

def formation_from_rows(rows: Iterable[dict]) -> str | None:
    rows = list(rows)
    counts = {p: sum(row.get("position") == p for row in rows) for p in ("DEF", "MID", "FWD")}
    formation = f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"
    return formation if formation in LEGAL_FORMATIONS else None

def plan_legality_checks(plan: dict, compliance: dict | None = None) -> dict[str, tuple[bool, str]]:
    xi = list(plan.get("starting_xi") or [])
    xi_ids = {int(row.get("element")) for row in xi if row.get("element") is not None}
    captain = int((plan.get("captain") or {}).get("element") or -1)
    vice = int((plan.get("vice_captain") or {}).get("element") or -1)
    bench = plan.get("bench") or {}
    chip = plan.get("chip_context") or {}
    formation = formation_from_rows(xi)
    declared = plan.get("formation")
    return {
        "G0-10": (len(xi) == 11 and formation is not None and declared == formation, f"formation={declared},derived={formation},xi={len(xi)}"),
        "G0-11": (sum(row.get("position") == "GK" for row in xi) == 1, "starting GK"),
        "G0-12": (captain in xi_ids and vice in xi_ids and captain != vice, f"captain={captain},vice={vice}"),
        "G0-13": (bool(bench.get("gk")) and len(bench.get("order") or []) == 3, "bench structure"),
        "G0-14": (chip.get("single_chip_rule_respected") is True and (not compliance or compliance.get("overall") == "PASS"), f"single_chip={chip.get('single_chip_rule_respected')},rules={(compliance or {}).get('overall')}"),
    }
''')

# 3) Canonical ownership registry documents single owners and intentionally shared primitives.
dump("config/architecture_ownership_registry.json", {
    "schema_version": 1,
    "registry": "fpl_v4_9_6_architecture_ownership_v1",
    "release": RELEASE,
    "principle": "ONE_OWNER_PER_RESPONSIBILITY_SHARED_PRIMITIVES_REUSED_NOT_REIMPLEMENTED",
    "responsibilities": [
        {"id": "OFFICIAL_FPL_ACQUISITION", "owner": "raw_snapshot", "implementation": "src.services.raw_snapshot_service"},
        {"id": "FPL_RULES_CONSTANTS", "owner": "domain_rules", "implementation": "src.engines.fpl_rules_2026"},
        {"id": "PLAN_LEGALITY", "owner": "domain_legality", "implementation": "src.engines.fpl_legality"},
        {"id": "PLAYER_PREDICTION", "owner": "prediction", "implementation": "src.services.prediction_service"},
        {"id": "VALIDATION_STORE", "owner": "validation_lifecycle", "implementation": "src.engines.v4_validation_cycle"},
        {"id": "ENGINE_RECOMMENDATION", "owner": "optimization", "implementation": "src.services.optimization_slo_service"},
        {"id": "EFFECTIVE_USER_PLAN", "owner": "user_decision_overlay", "implementation": "src.services.user_decision_overlay_service"},
        {"id": "PERSONAL_GW_SCORECARD", "owner": "personal_gw_scorecard", "implementation": "src.services.gw_scorecard_service"},
        {"id": "POSTFLIGHT_TRUTH", "owner": "framework_postflight", "implementation": "src.services.framework_postflight_truth_service"},
        {"id": "HUMAN_REPORT_DECISION", "owner": "report_governance", "implementation": "src.engines.v4_checkpoint_governance"}
    ],
    "shared_primitives": [
        {"id": "XMINS_DISTRIBUTION", "owner": "prediction", "consumers": ["DSS-05", "DSS-06", "DSS-X10", "DSS-X11"]},
        {"id": "ADVANCED_ATTACKING_EVIDENCE", "owner": "prediction", "consumers": ["DSS-12", "DSS-13", "DSS-14", "DSS-15", "DSS-16", "DSS-38"]},
        {"id": "MULTI_HORIZON_PROJECTION", "owner": "prediction", "consumers": ["DSS-25", "DSS-26", "DSS-27", "DSS-28", "ENH-04"]},
        {"id": "PRICE_MARKET_EVIDENCE", "owner": "prediction", "consumers": ["DSS-39", "DSS-40", "DSS-41", "DSS-42", "DSS-43", "DSS-X15", "ENH-05"]},
        {"id": "RECONCILIATION_EVIDENCE", "owner": "validation_lifecycle", "consumers": ["DSS-44", "DSS-X12", "ENH-03"]}
    ]
})

write("src/services/architecture_guard_service.py", '''from __future__ import annotations
import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from src.release import RELEASE_VERSION
from src.utils import CONFIG, DATA, atomic_json, read_json

ROOT = Path(__file__).resolve().parents[2]
OUT = DATA / "architecture_ownership_v4.json"
CANONICAL_SYMBOLS = {"SCORING", "DEFCON", "CHIPS", "POSITION_COUNTS", "BUDGET_TENTHS", "MAX_PER_CLUB", "LEGAL_FORMATIONS", "LEGAL_FORMATION_TUPLES"}
CANONICAL_RULE_MODULE = ROOT / "src/engines/fpl_rules_2026.py"
ALLOWED_OFFICIAL_FETCH = {ROOT / "src/services/raw_snapshot_service.py", ROOT / "src/sources/official_fpl.py"}
SKIP_DUP_FN_NAMES = {"main", "run", "_f", "check", "write", "load", "dump"}

def _unique(values):
    values = [str(v) for v in values if v is not None]
    return len(values) == len(set(values)), sorted(k for k, n in Counter(values).items() if n > 1)

def _assignment_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name): names.add(target.id)
    return names

def _duplicate_functions() -> list[dict]:
    seen = {}
    duplicates = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name in SKIP_DUP_FN_NAMES:
                continue
            size = sum(1 for _ in ast.walk(node))
            if size < 28:
                continue
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
            digest = hashlib.sha256(body.encode()).hexdigest()
            prior = seen.get(digest)
            current = f"{path.relative_to(ROOT)}:{node.name}"
            if prior and prior != current:
                duplicates.append({"first": prior, "second": current})
            else:
                seen[digest] = current
    return duplicates

def run() -> dict:
    services = read_json(CONFIG / "service_registry.json", {})
    contracts = read_json(CONFIG / "service_contract_registry.json", {})
    core = read_json(CONFIG / "dss_core_registry.json", {})
    ext = read_json(CONFIG / "dss_extension_registry.json", {})
    enh = read_json(CONFIG / "enhancement_layers_registry.json", {})
    gate = read_json(CONFIG / "gate0_registry.json", {})
    ownership = read_json(CONFIG / "architecture_ownership_registry.json", {})
    release = read_json(CONFIG / "release_manifest.json", {})
    checks = {}

    service_rows = services.get("services") or []
    service_ids = [row.get("id") for row in service_rows]
    checks["unique_service_ids"] = _unique(service_ids)
    produced = [name for row in service_rows for name in (row.get("produces") or [])]
    checks["unique_contract_producers"] = _unique(produced)
    contract_paths = [spec.get("path") for spec in (contracts.get("contracts") or {}).values()]
    checks["unique_contract_paths"] = _unique(contract_paths)

    registry_ids = [row.get("id") for row in core.get("modules") or []] + [row.get("id") for row in ext.get("modules") or []] + [row.get("id") for row in enh.get("layers") or []] + [row.get("id") for row in gate.get("checks") or []]
    checks["unique_registry_ids"] = _unique(registry_ids)

    responsibility_ids = [row.get("id") for row in ownership.get("responsibilities") or []]
    primitive_ids = [row.get("id") for row in ownership.get("shared_primitives") or []]
    checks["unique_responsibility_ids"] = _unique(responsibility_ids)
    checks["unique_shared_primitive_ids"] = _unique(primitive_ids)

    duplicate_rule_defs = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path == CANONICAL_RULE_MODULE:
            continue
        overlap = sorted(_assignment_names(path) & CANONICAL_SYMBOLS)
        if overlap:
            duplicate_rule_defs.append({"file": str(path.relative_to(ROOT)), "symbols": overlap})
    checks["canonical_rule_definitions_single_owner"] = (not duplicate_rule_defs, duplicate_rule_defs)

    official_fetch_violations = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path in ALLOWED_OFFICIAL_FETCH:
            continue
        text = path.read_text(encoding="utf-8")
        if "fantasy.premierleague.com/api" in text or "src.sources.official_fpl" in text:
            official_fetch_violations.append(str(path.relative_to(ROOT)))
    checks["official_fpl_fetch_single_owner"] = (not official_fetch_violations, official_fetch_violations)

    duplicate_functions = _duplicate_functions()
    checks["no_exact_nontrivial_function_clones"] = (not duplicate_functions, duplicate_functions)

    main = (ROOT / ".github/workflows/fpl-engine.yml").read_text(encoding="utf-8")
    recovery = (ROOT / ".github/workflows/fpl-engine-recovery.yml").read_text(encoding="utf-8")
    reusable = ROOT / ".github/workflows/fpl-engine-core.yml"
    workflow_ok = reusable.exists() and "uses: ./.github/workflows/fpl-engine-core.yml" in main and "uses: ./.github/workflows/fpl-engine-core.yml" in recovery and "src.services.orchestrator" not in main and "src.services.orchestrator" not in recovery
    checks["single_reusable_production_workflow"] = (workflow_ok, [] if workflow_ok else ["main/recovery must call reusable core"])

    release_ok = release.get("release") == RELEASE_VERSION == services.get("architecture_version") == ownership.get("release")
    checks["release_single_source_coherent"] = (release_ok, [] if release_ok else [release.get("release"), RELEASE_VERSION, services.get("architecture_version"), ownership.get("release")])

    normalized = {name: {"pass": bool(value[0]), "detail": value[1]} for name, value in checks.items()}
    passed = all(row["pass"] for row in normalized.values())
    out = {"schema_version": 496, "release": RELEASE_VERSION, "service": "architecture_guard", "status": "PASS" if passed else "FAIL", "checks": normalized, "guardrails": {"one_owner_per_artifact": True, "one_owner_per_rule": True, "shared_primitives_reused_not_reimplemented": True, "official_fpl_single_acquisition_owner": True, "reusable_workflow_single_pipeline": True}}
    atomic_json(OUT, out)
    print(json.dumps({"service": "architecture_guard", "status": out["status"], "checks": {k:v["pass"] for k,v in normalized.items()}}, ensure_ascii=False))
    if not passed:
        raise SystemExit(2)
    return out

if __name__ == "__main__": run()
''')

# 4) Refactor optimizer constants and lineup legality to canonical primitives.
p = ROOT / "src/engines/v4_wc_optimizer.py"
s = p.read_text(encoding="utf-8")
s = s.replace("from src.engines.team_value import sell_cost\nfrom src.utils import CONFIG, read_json\n\nPOSITION_COUNTS = {\"GK\": 2, \"DEF\": 5, \"MID\": 5, \"FWD\": 3}\nBUDGET_TENTHS = 1000\nMAX_PER_CLUB = 3\n", "from src.engines.team_value import sell_cost\nfrom src.engines.fpl_rules_2026 import POSITION_COUNTS, BUDGET_TENTHS, MAX_PER_CLUB\nfrom src.utils import CONFIG, read_json\n")
p.write_text(s, encoding="utf-8")

p = ROOT / "src/engines/v4_lineup_optimizer.py"
s = p.read_text(encoding="utf-8")
s = s.replace("from src.utils import DATA, CONFIG, atomic_json, read_json\n\nOUTFILE", "from src.engines.fpl_rules_2026 import LEGAL_FORMATION_TUPLES\nfrom src.engines.fpl_legality import formation_from_rows\nfrom src.utils import DATA, CONFIG, atomic_json, read_json\n\nOUTFILE")
s = re.sub(r"\nLEGAL_FORMATIONS = .*?\n", "\n", s, count=1)
s = re.sub(r"def _formation\(rows\):\n(?:    | )*c=.*?\n(?:    | )*form=.*?\n(?:    | )*return .*?\n", "def _formation(rows):\n    return formation_from_rows(rows)\n", s, count=1)
s = s.replace("for d,m,f in LEGAL_FORMATIONS:", "for d,m,f in LEGAL_FORMATION_TUPLES:")
p.write_text(s, encoding="utf-8")

# 5) Framework health and postflight call the same legality primitive; validator duplication is removed.
p = ROOT / "src/engines/framework_health_audit.py"
s = p.read_text(encoding="utf-8")
s = s.replace("from src.engines.v4_wc_optimizer import MAX_PER_CLUB, POSITION_COUNTS", "from src.engines.fpl_rules_2026 import MAX_PER_CLUB, POSITION_COUNTS\nfrom src.engines.fpl_legality import plan_legality_checks")
s = re.sub(r"\nLEGAL_FORMS = \{[^\n]+\}\n", "\n", s, count=1)
start = s.index('    if phase == "postflight" and lineup:\n')
end = s.index('    totals = read_json(DATA / "team.json", {}).get("totals") or {}\n', start)
replacement = '''    if phase == "postflight" and lineup:\n        for check_id, (ok, detail) in plan_legality_checks(lineup, compliance).items():\n            checks[check_id] = ("PASS" if ok else "FAIL", detail)\n    else:\n        for check_id in ("G0-10", "G0-11", "G0-12", "G0-13", "G0-14"):\n            checks[check_id] = ("DEFERRED", "requires governed postflight lineup/chip output")\n\n'''
s = s[:start] + replacement + s[end:]
p.write_text(s, encoding="utf-8")

p = ROOT / "src/services/framework_postflight_truth_service.py"
s = p.read_text(encoding="utf-8")
s = s.replace("from src.engines import framework_health_audit as audit\n", "from src.engines import framework_health_audit as audit\nfrom src.engines.fpl_legality import plan_legality_checks\nfrom src.release import RELEASE_VERSION\n")
s = re.sub(r"\nLEGAL_FORMS = \{[^\n]+\}\n", "\n", s, count=1)
start = s.find("\ndef _plan_checks(")
if start != -1:
    end = s.index("\ndef _prediction_fixtures", start)
    s = s[:start] + s[end:]
s = s.replace("_plan_checks(engine_plan, compliance)", "plan_legality_checks(engine_plan, compliance)")
s = s.replace("_plan_checks(effective_plan, compliance)", "plan_legality_checks(effective_plan, compliance)")
s = re.sub(r'health\["release"\] = "[^"]+"', 'health["release"] = RELEASE_VERSION', s)
p.write_text(s, encoding="utf-8")

# 6) Compliance validates canonical registry instead of carrying a second scoring copy.
write("src/engines/compliance_audit.py", '''from __future__ import annotations
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
''')

# 7) Release strings use one runtime source where code emits release metadata.
p = ROOT / "src/engines/v4_validation_cycle.py"
s = p.read_text(encoding="utf-8")
s = s.replace("from src.utils import DATA, atomic_json, parse_dt, read_json, utcnow", "from src.release import RELEASE_VERSION\nfrom src.utils import DATA, atomic_json, parse_dt, read_json, utcnow")
s = re.sub(r'"release": "[^"]+"', '"release": RELEASE_VERSION', s)
p.write_text(s, encoding="utf-8")

# 8) Add architecture guard as independent microservice; no existing service ownership is merged.
registry = load("config/service_registry.json")
registry["schema_version"] = 9
registry["registry"] = "fpl_v4_9_6_microservice_registry_v9"
registry["architecture_version"] = RELEASE
services = [row for row in registry.get("services", []) if row.get("id") != "architecture_guard"]
arch = {"id":"architecture_guard","name":"Architecture Ownership Guard Service","boundary_state":"INDEPENDENT","module":"src.services.architecture_guard_service","command":["{python}","-m","src.services.architecture_guard_service"],"timeout_seconds":20,"depends_on":[],"produces":["architecture_guard"],"critical":True}
services.insert(0, arch)
for row in services:
    if row.get("id") == "framework_preflight":
        row["depends_on"] = list(dict.fromkeys([*(row.get("depends_on") or []), "architecture_guard"]))
registry["services"] = services
registry.setdefault("guardrails", {}).update({
    "architecture_ownership_guard_process_isolated": True,
    "duplicate_service_ids_rejected": True,
    "duplicate_contract_producers_rejected": True,
    "duplicate_contract_paths_rejected": True,
    "duplicate_registry_ids_rejected": True,
    "canonical_rules_single_owner": True,
    "canonical_legality_single_implementation": True,
    "exact_nontrivial_function_clones_rejected": True,
    "reusable_production_workflow_single_owner": True,
    "release_manifest_single_source": True,
    "service_count": 12
})
dump("config/service_registry.json", registry)

contracts = load("config/service_contract_registry.json")
contracts["schema_version"] = 7
contracts["registry"] = "fpl_v4_9_6_service_contracts_v7"
contracts.setdefault("contracts", {})["architecture_guard"] = {
    "path":"data/architecture_ownership_v4.json",
    "min_schema_version":496,
    "version_field":"release",
    "version_prefix":RELEASE,
    "required_paths":["status","checks.unique_service_ids.pass","checks.unique_contract_producers.pass","checks.unique_contract_paths.pass","checks.unique_registry_ids.pass","checks.canonical_rule_definitions_single_owner.pass","checks.official_fpl_fetch_single_owner.pass","checks.no_exact_nontrivial_function_clones.pass","checks.single_reusable_production_workflow.pass","checks.release_single_source_coherent.pass"],
    "equals":{"status":"PASS","checks.unique_service_ids.pass":True,"checks.unique_contract_producers.pass":True,"checks.unique_contract_paths.pass":True,"checks.unique_registry_ids.pass":True,"checks.canonical_rule_definitions_single_owner.pass":True,"checks.official_fpl_fetch_single_owner.pass":True,"checks.no_exact_nontrivial_function_clones.pass":True,"checks.single_reusable_production_workflow.pass":True,"checks.release_single_source_coherent.pass":True}
}
dump("config/service_contract_registry.json", contracts)

# 9) One reusable production workflow. Main/recovery contain triggers only and call the same core.
write(".github/workflows/fpl-engine-core.yml", '''name: FPL V4 reusable production core

on:
  workflow_call:
    inputs:
      ref:
        required: true
        type: string
      publish:
        required: true
        type: boolean

permissions:
  contents: write

jobs:
  validate-v4:
    runs-on: ubuntu-latest
    timeout-minutes: 12
    env:
      PYTHONPATH: ${{ github.workspace }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          ref: ${{ inputs.ref }}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: requirements.txt
      - name: Install cached dependencies
        run: pip install --disable-pip-version-check -r requirements.txt pytest
      - name: Unit and acceptance tests
        run: python -m pytest -q
      - name: Run process-isolated DAG-parallel V4 services
        run: python -m src.services.orchestrator daily --stats --deep-stats
      - name: Centralized V4 core quality gate
        run: python -m src.engines.v4_quality_gate
      - name: Core acceptance summary
        run: |
          python - <<'PY'
          import json
          h=json.load(open('data/framework_health_v4.json'))
          o=json.load(open('data/service_orchestration_v4.json'))
          a=json.load(open('data/architecture_ownership_v4.json'))
          c=json.load(open('data/checkpoint_decision_v4.json'))
          print({'pipeline_health':h['pipeline_health'],'capability_coverage':h['capability_coverage'],'gate0':h['gate0']['counts'],'services':o['summary']['services_passed'],'orchestration_ms':o['duration_ms'],'architecture_guard':a['status'],'action':c['action_state']})
          PY
      - name: Publish core branch data
        if: inputs.publish
        shell: bash
        run: |
          git config user.name "fpl-iphoenk-bot"
          git config user.email "actions@users.noreply.github.com"
          git add data/
          if git diff --cached --quiet; then echo "No core data changes"; exit 0; fi
          git commit -m "data(v4): prediction acceptance snapshot"
          git fetch origin v4-prediction-engine
          git rebase origin/v4-prediction-engine
          git push origin HEAD:v4-prediction-engine
      - name: Advanced enrichment ablation post-publish diagnostic gate
        run: |
          python -m src.engines.v4_advanced_ablation
          python - <<'PY'
          import json
          a=json.load(open('data/advanced_ablation_v4.json'))
          assert a['status']=='PASS', a
          assert a['ablation']['full_shadow_parity']['ok'] is True, a
          assert a['interpretation']['impact_is_diagnostic_not_health_threshold'] is True, a
          PY
      - name: Publish ablation diagnostic data
        if: inputs.publish
        shell: bash
        run: |
          git config user.name "fpl-iphoenk-bot"
          git config user.email "actions@users.noreply.github.com"
          git add data/advanced_ablation_v4.json
          if git diff --cached --quiet; then echo "No ablation data changes"; exit 0; fi
          git commit -m "data(v4): advanced ablation diagnostic"
          git fetch origin v4-prediction-engine
          git rebase origin/v4-prediction-engine
          git push origin HEAD:v4-prediction-engine
''')

write(".github/workflows/fpl-engine.yml", '''name: FPL V4 production gate

on:
  workflow_dispatch:
  schedule:
    - cron: "30 21 * * *"
    - cron: "30 5 * * *"
    - cron: "30 14 * * *"
  push:
    branches: [v4-prediction-engine]
    paths-ignore: ['data/**']
  pull_request:
    branches: [v4-prediction-engine]

permissions:
  contents: write

concurrency:
  group: fpl-iphoenk-v4-gate
  cancel-in-progress: true

jobs:
  core:
    uses: ./.github/workflows/fpl-engine-core.yml
    permissions:
      contents: write
    with:
      ref: ${{ github.event_name == 'schedule' && 'v4-prediction-engine' || github.sha }}
      publish: ${{ github.event_name != 'pull_request' }}
''')

write(".github/workflows/fpl-engine-recovery.yml", '''name: FPL V4 scheduled checkpoint recovery

on:
  workflow_dispatch:
  schedule:
    - cron: "45 21 * * *"
    - cron: "45 5 * * *"
    - cron: "45 14 * * *"

permissions:
  contents: write

concurrency:
  group: fpl-iphoenk-v4-gate
  cancel-in-progress: false

jobs:
  freshness:
    runs-on: ubuntu-latest
    outputs:
      needs_recovery: ${{ steps.check.outputs.needs_recovery }}
      age_minutes: ${{ steps.check.outputs.age_minutes }}
    steps:
      - uses: actions/checkout@v4
        with:
          ref: v4-prediction-engine
      - id: check
        shell: bash
        run: |
          python - <<'PY' >> "$GITHUB_OUTPUT"
          import json
          from datetime import datetime, timezone
          from pathlib import Path
          path=Path('data/latest.json'); fresh=False; age=None
          if path.exists():
              raw=json.loads(path.read_text()).get('generated_at')
              if raw:
                  generated=datetime.fromisoformat(raw.replace('Z','+00:00'))
                  age=max(0.0,(datetime.now(timezone.utc)-generated).total_seconds()/60.0)
                  fresh=age<=45
          print(f"needs_recovery={'false' if fresh else 'true'}")
          print(f"age_minutes={'' if age is None else round(age,2)}")
          PY
  recover:
    needs: freshness
    if: needs.freshness.outputs.needs_recovery == 'true'
    uses: ./.github/workflows/fpl-engine-core.yml
    permissions:
      contents: write
    with:
      ref: v4-prediction-engine
      publish: true
  summary:
    needs: [freshness, recover]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - run: echo "needs_recovery=${{ needs.freshness.outputs.needs_recovery }} age_minutes=${{ needs.freshness.outputs.age_minutes }}"
''')

# 10) README/version coherence without embedding release literals throughout code/workflow.
p = ROOT / "README.md"
s = p.read_text(encoding="utf-8")
s = re.sub(r"^# FPL iphoenk Engine V[^\n]+", f"# FPL iphoenk Engine V{RELEASE}", s, count=1)
section = '''\n## V4.9.6 architecture consolidation\n- 12 process-isolated microservices; Architecture Ownership Guard runs independently and fail-closes duplicate ownership.\n- One canonical FPL rules registry (`config/fpl_rules_2026_27.json`).\n- One canonical plan-legality primitive (`src/engines/fpl_legality.py`) reused by optimizer/health/postflight.\n- Main and recovery schedules call one reusable production workflow.\n- Shared DSS evidence is explicitly reused as a primitive rather than recomputed by parallel modules.\n- Release metadata is sourced from `config/release_manifest.json` and verified by the architecture guard.\n'''
if "## V4.9.6 architecture consolidation" not in s:
    s = s.rstrip() + "\n" + section
p.write_text(s, encoding="utf-8")

# 11) Tests: update architecture count/dependencies and add no-duplicate assertions.
p = ROOT / "tests/test_service_orchestrator.py"
s = p.read_text(encoding="utf-8")
s = s.replace("assert len(ordered) == 11", "assert len(ordered) == 12")
s = s.replace('assert ordered[0]["id"] == "raw_snapshot"', 'assert {ordered[0]["id"], ordered[1]["id"]} == {"architecture_guard", "raw_snapshot"}')
s = s.replace('assert ids[:3] == ["raw_snapshot", "enrichment", "prediction"]', 'assert ids.index("raw_snapshot") < ids.index("enrichment") < ids.index("prediction")')
s = s.replace('assert set(by_id["framework_preflight"]["depends_on"]) == {"validation_lifecycle", "rules_compliance"}', 'assert set(by_id["framework_preflight"]["depends_on"]) == {"validation_lifecycle", "rules_compliance", "architecture_guard"}')
s = s.replace('assert any({row["id"] for row in level} == {"validation_lifecycle", "rules_compliance", "optimization"} for level in levels)', 'assert any({"validation_lifecycle", "rules_compliance", "optimization"} <= {row["id"] for row in level} for level in levels)')
s = s.replace('assert guardrails["registry_counts_unchanged"] == {', 'assert guardrails["architecture_ownership_guard_process_isolated"] is True\n    assert guardrails["duplicate_service_ids_rejected"] is True\n    assert guardrails["canonical_rules_single_owner"] is True\n    assert guardrails["service_count"] == 12\n    assert guardrails["registry_counts_unchanged"] == {')
p.write_text(s, encoding="utf-8")

write("tests/test_v496_architecture_consolidation.py", '''import json
from pathlib import Path
from src.engines.fpl_legality import formation_from_rows, plan_legality_checks
from src.engines.fpl_rules_2026 import LEGAL_FORMATIONS, POSITION_COUNTS, MAX_PER_CLUB
from src.services.architecture_guard_service import run as architecture_guard_run

ROOT = Path(__file__).resolve().parents[1]

def test_canonical_rules_and_legality_are_single_source():
    assert POSITION_COUNTS == {"GK":2,"DEF":5,"MID":5,"FWD":3}
    assert MAX_PER_CLUB == 3
    assert "3-5-2" in LEGAL_FORMATIONS
    rows=[{"position":"GK"}]+[{"position":"DEF"}]*3+[{"position":"MID"}]*5+[{"position":"FWD"}]*2
    assert formation_from_rows(rows) == "3-5-2"

def test_plan_legality_uses_derived_formation():
    xi=[{"element":1,"position":"GK"}]+[{"element":i,"position":"DEF"} for i in range(2,5)]+[{"element":i,"position":"MID"} for i in range(5,10)]+[{"element":i,"position":"FWD"} for i in range(10,12)]
    plan={"formation":"3-5-2","starting_xi":xi,"captain":{"element":5},"vice_captain":{"element":10},"bench":{"gk":{"element":20},"order":[1,2,3]},"chip_context":{"single_chip_rule_respected":True}}
    checks=plan_legality_checks(plan,{"overall":"PASS"})
    assert all(ok for ok,_ in checks.values())

def test_architecture_guard_passes_repository_ownership_contract():
    out=architecture_guard_run()
    assert out["status"] == "PASS"
    assert all(row["pass"] for row in out["checks"].values())

def test_main_and_recovery_use_one_reusable_core():
    main=(ROOT/".github/workflows/fpl-engine.yml").read_text()
    recovery=(ROOT/".github/workflows/fpl-engine-recovery.yml").read_text()
    core=(ROOT/".github/workflows/fpl-engine-core.yml").read_text()
    assert "uses: ./.github/workflows/fpl-engine-core.yml" in main
    assert "uses: ./.github/workflows/fpl-engine-core.yml" in recovery
    assert main.count("src.services.orchestrator") == 0
    assert recovery.count("src.services.orchestrator") == 0
    assert core.count("src.services.orchestrator") == 1
''')

# Remove temporary migration files in the same migration commit.
(ROOT / ".github/workflows/v496-migration.yml").unlink(missing_ok=True)
Path(__file__).unlink(missing_ok=True)
