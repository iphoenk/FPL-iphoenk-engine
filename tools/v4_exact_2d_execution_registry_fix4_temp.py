from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one replacement in {relative}, found {count}: {old[:180]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


worker = "src/services/package_optimization_shard_service.py"
replace_once(
    worker,
    '''    started = perf_counter(); predictions=read_json(DATA/"predictions_v4.json",{}); universe=read_json(DATA/"universe.json",{}); locked=read_json(CONFIG/"locked_squad.json",{}); understat=read_json(DATA/"understat_v4.json",{}); prices=read_json(DATA/"prices.json",{})\n    planning = effective_planning_squad(locked, predictions); locked_for_search = dict(locked); locked_for_search["players"] = list(planning.get("players") or [])\n    for key in ("bank","free_transfers","transfer_cost_points","free_hit_active"): locked_for_search[key] = planning.get(key, locked.get(key))\n    candidates=build_candidates(predictions); tactical=build_tactical_interactions(predictions, universe, understat, team_system_evidence=read_json(DATA/"team_system_evidence_v4.json",{}), roster_events=read_json(DATA/"roster_events_v4.json",{}))\n''',
    '''    started = perf_counter()\n    predictions = read_json(DATA / "predictions_v4.json", {})\n    universe = read_json(DATA / "universe.json", {})\n    configured_lock = read_json(CONFIG / "locked_squad.json", {})\n    team = read_json(DATA / "team.json", {})\n    latest = read_json(DATA / "latest.json", {})\n    understat = read_json(DATA / "understat_tactical_v4.json", {})\n    prices = read_json(DATA / "prices.json", {})\n    locked_for_search = effective_planning_squad(team, configured_lock, latest)\n    candidates = build_candidates(predictions, universe)\n    tactical = build_tactical_interactions(predictions, universe, understat)\n''',
)
path = ROOT / worker
text = path.read_text(encoding="utf-8")
replacement = '"semantic_fingerprint":_semantic_fingerprint(predictions, universe, locked_for_search, understat, candidates=candidates, tactical_interactions=tactical, prices=prices)'
if replacement not in text:
    pattern = r'"semantic_fingerprint"\s*:\s*_semantic_fingerprint\([^\n}]+\)'
    text, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise RuntimeError("unable to normalize shard semantic fingerprint call")
    path.write_text(text, encoding="utf-8")

merge = "src/services/package_optimization_merge_service.py"
replace_once(
    merge,
    '''    predictions=read_json(DATA/"predictions_v4.json",{}); universe=read_json(DATA/"universe.json",{}); locked=read_json(CONFIG/"locked_squad.json",{}); understat=read_json(DATA/"understat_v4.json",{}); prices=read_json(DATA/"prices.json",{})\n    planning=effective_planning_squad(locked,predictions); locked_for_search=dict(locked); locked_for_search["players"]=list(planning.get("players") or [])\n    for key in ("bank","free_transfers","transfer_cost_points","free_hit_active"): locked_for_search[key]=planning.get(key,locked.get(key))\n    candidates=build_candidates(predictions); tactical=build_tactical_interactions(predictions,universe,understat,team_system_evidence=read_json(DATA/"team_system_evidence_v4.json",{}),roster_events=read_json(DATA/"roster_events_v4.json",{}))\n    current=_semantic_fingerprint(candidates,locked_for_search,predictions=predictions,universe=universe,understat=understat,tactical_interactions=tactical,prices=prices)\n''',
    '''    predictions = read_json(DATA / "predictions_v4.json", {})\n    universe = read_json(DATA / "universe.json", {})\n    configured_lock = read_json(CONFIG / "locked_squad.json", {})\n    team = read_json(DATA / "team.json", {})\n    latest = read_json(DATA / "latest.json", {})\n    understat = read_json(DATA / "understat_tactical_v4.json", {})\n    prices = read_json(DATA / "prices.json", {})\n    locked_for_search = effective_planning_squad(team, configured_lock, latest)\n    candidates = build_candidates(predictions, universe)\n    tactical = build_tactical_interactions(predictions, universe, understat)\n    current = _semantic_fingerprint(\n        predictions, universe, locked_for_search, understat,\n        candidates=candidates, tactical_interactions=tactical, prices=prices,\n    )\n''',
)

# Temp generator currently emits the same _load_plan helper into both execution
# modules. Architecture guard correctly rejects that clone. Extract it once as a
# shared execution-registry primitive; do not weaken/whitelist the clone guard.
def extract_function(relative: str, name: str) -> tuple[str, str]:
    path = ROOT / relative
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    if node is None or node.end_lineno is None:
        raise RuntimeError(f"missing {name} in {relative}")
    lines = source.splitlines(keepends=True)
    start = node.lineno - 1
    end = node.end_lineno
    block = "".join(lines[start:end])
    # Remove adjacent blank lines conservatively; formatter-independent.
    while end < len(lines) and lines[end].strip() == "":
        end += 1
    new_source = "".join(lines[:start] + lines[end:])
    path.write_text(new_source, encoding="utf-8")
    return block, ast.dump(node, include_attributes=False)

worker_engine = "src/engines/v4_full_universe_shard_worker.py"
reducer_engine = "src/engines/v4_full_universe_shard_reducer.py"
worker_block, worker_ast = extract_function(worker_engine, "_load_plan")
_, reducer_ast = extract_function(reducer_engine, "_load_plan")
if worker_ast != reducer_ast:
    raise RuntimeError("worker/reducer _load_plan implementations are not semantically identical")

shared_source = '''from __future__ import annotations\n\nfrom src.utils import CONFIG, read_json\n\nSHARDING_REGISTRY_PATH = CONFIG / "intelligence" / "full_universe_package_search_sharding.json"\n\n\ndef load_sharding_plan() -> dict:\n    plan = read_json(SHARDING_REGISTRY_PATH, {})\n    if plan.get("registry") != "V4_FULL_UNIVERSE_PACKAGE_SEARCH_SHARDING_V1":\n        raise RuntimeError("invalid V4 full-universe package sharding registry")\n    return plan\n'''
shared = ROOT / "src/engines/v4_full_universe_shard_registry.py"
shared.write_text(shared_source, encoding="utf-8")

for relative in (worker_engine, reducer_engine):
    p = ROOT / relative
    source = p.read_text(encoding="utf-8")
    import_line = "from src.engines.v4_full_universe_shard_registry import load_sharding_plan\n"
    if import_line not in source:
        anchor = "from __future__ import annotations\n"
        source = source.replace(anchor, anchor + "\n" + import_line, 1)
    source = source.replace("_load_plan()", "load_sharding_plan()")
    p.write_text(source, encoding="utf-8")

# The execution-only registry is the single owner of tuning; worker/reducer must not
# carry copies of registry path/id literals after this point.
print("2D package worker/fan-in aligned to canonical inputs; shared sharding registry loader deduplicated")
