import json
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
