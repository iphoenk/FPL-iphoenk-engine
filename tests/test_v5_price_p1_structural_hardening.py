from __future__ import annotations

import ast
from pathlib import Path

from src.engines import price_radar as canonical
from src.v5.price_squeeze import price_squeeze
from src.v5.services import price as price_service


ROOT = Path(__file__).resolve().parents[1]


def test_price_squeeze_scenarios_are_registry_driven():
    policy = canonical.load_policy()["squeeze_policy"]
    steps = sorted({int(value) for value in policy["scenario_steps_tenths"]})
    outgoing = {
        "element": 1,
        "name": "Owned",
        "now_cost": 54,
        "direction": "FALL",
        "model_urgency": "CRITICAL",
        "predicted_change_cycle": "NEXT_UPDATE",
    }
    incoming = {
        "element": 2,
        "name": "Target",
        "now_cost": 53,
        "direction": "RISE",
        "model_urgency": "CRITICAL",
        "predicted_change_cycle": "NEXT_UPDATE",
    }
    ledger = {
        "element": 1,
        "purchase_cost": 50,
        "sell_cost": 52,
        "finance_source": "test",
        "finance_exact": True,
    }
    result = price_squeeze(outgoing, incoming, ledger, 1)
    names = [row["scenario"] for row in result["scenarios"]]
    expected = ["BASE"]
    for step in steps:
        suffix = f"0_{step}"
        expected.extend(
            [
                f"OUTGOING_FALL_{suffix}",
                f"INCOMING_RISE_{suffix}",
                f"BOTH_SQUEEZE_{suffix}",
            ]
        )
    expected.append("WORST_REASONABLE_SHORT_HORIZON")
    assert names == expected
    governance = result["governance"]
    assert governance["scenario_policy_registry"] == "config/intelligence/price_radar.json#squeeze_policy"
    assert governance["scenario_steps_tenths"] == steps
    assert governance["material_urgency_levels"] == sorted(str(value) for value in policy["material_urgency_levels"])
    assert governance["worst_reasonable_short_horizon_tenths"] == int(
        policy["worst_reasonable_short_horizon_tenths"]
    )


def test_price_service_advertises_only_runtime_routed_price_operations():
    status = price_service.handle("status", {})
    operations = set(status["operations"])
    orchestrator = canonical.json.loads(
        (ROOT / "config" / "v5_orchestrator_registry.json").read_text(encoding="utf-8")
    )
    routed = {
        str(row["operation"])
        for row in orchestrator["routing"].values()
        if isinstance(row, dict) and row.get("service") == "price"
    }
    assert operations == routed == {"build", "bind_watchlist_evidence", "annotate_comparator"}
    assert "annotate_packages" not in operations
    assert status["governance"]["advertised_operations_are_runtime_routed"] is True


def test_price_business_implementation_has_one_v5_service_owner():
    importers = []
    for path in sorted((ROOT / "src" / "v5" / "services").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "src.v5.price_squeeze":
                importers.append(path.name)
    assert importers == ["price.py"]


def test_p1_removes_dead_package_overlay_and_hardcoded_scenario_table():
    source = (ROOT / "src" / "v5" / "price_squeeze.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assigned_names = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        if isinstance(target, ast.Name)
    }
    assert "annotate_packages" not in function_names
    assert "SCENARIOS" not in assigned_names


def test_evaluation_and_watchlist_do_not_import_price_business_logic():
    for relative in ("src/v5/services/evaluation.py", "src/v5/services/watchlist.py"):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
        modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and isinstance(node.module, str)
        }
        assert "src.v5.price_squeeze" not in modules
        assert "src.v5.price_service" not in modules
