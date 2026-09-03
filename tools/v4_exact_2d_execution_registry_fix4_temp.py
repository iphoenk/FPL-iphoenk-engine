from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one replacement in {relative}, found {count}: {old[:180]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


worker = "src/services/package_optimization_shard_service.py"
replace_once(
    worker,
    '''    started = perf_counter(); predictions=read_json(DATA/"predictions_v4.json",{}); universe=read_json(DATA/"universe.json",{}); locked=read_json(CONFIG/"locked_squad.json",{}); understat=read_json(DATA/"understat_v4.json",{}); prices=read_json(DATA/"prices.json",{})\n    planning = effective_planning_squad(locked, predictions); locked_for_search = dict(locked); locked_for_search["players"] = list(planning.get("players") or [])\n    for key in ("bank","free_transfers","transfer_cost_points","free_hit_active"): locked_for_search[key] = planning.get(key, locked.get(key))\n    candidates=build_candidates(predictions); tactical=build_tactical_interactions(predictions, universe, understat, team_system_evidence=read_json(DATA/"team_system_evidence_v4.json",{}), roster_events=read_json(DATA/"roster_events_v4.json",{}))\n''',
    '''    started = perf_counter()\n    predictions = read_json(DATA / "predictions_v4.json", {})\n    universe = read_json(DATA / "universe.json", {})\n    configured_lock = read_json(CONFIG / "locked_squad.json", {})\n    team = read_json(DATA / "team.json", {})\n    latest = read_json(DATA / "latest.json", {})\n    understat = read_json(DATA / "understat_tactical_v4.json", {})\n    prices = read_json(DATA / "prices.json", {})\n    locked_for_search = effective_planning_squad(team, configured_lock, latest)\n    candidates = build_candidates(predictions, universe)\n    tactical = build_tactical_interactions(predictions, universe, understat)\n''',
)
replace_once(
    worker,
    '''"semantic_fingerprint":_semantic_fingerprint(candidates, locked_for_search, predictions=predictions, universe=universe, understat=understat,tactical_interactions=tactical,prices=prices)''',
    '''"semantic_fingerprint":_semantic_fingerprint(predictions, universe, locked_for_search, understat, candidates=candidates, tactical_interactions=tactical, prices=prices)''',
)

merge = "src/services/package_optimization_merge_service.py"
replace_once(
    merge,
    '''    predictions=read_json(DATA/"predictions_v4.json",{}); universe=read_json(DATA/"universe.json",{}); locked=read_json(CONFIG/"locked_squad.json",{}); understat=read_json(DATA/"understat_v4.json",{}); prices=read_json(DATA/"prices.json",{})\n    planning=effective_planning_squad(locked,predictions); locked_for_search=dict(locked); locked_for_search["players"]=list(planning.get("players") or [])\n    for key in ("bank","free_transfers","transfer_cost_points","free_hit_active"): locked_for_search[key]=planning.get(key,locked.get(key))\n    candidates=build_candidates(predictions); tactical=build_tactical_interactions(predictions,universe,understat,team_system_evidence=read_json(DATA/"team_system_evidence_v4.json",{}),roster_events=read_json(DATA/"roster_events_v4.json",{}))\n    current=_semantic_fingerprint(candidates,locked_for_search,predictions=predictions,universe=universe,understat=understat,tactical_interactions=tactical,prices=prices)\n''',
    '''    predictions = read_json(DATA / "predictions_v4.json", {})\n    universe = read_json(DATA / "universe.json", {})\n    configured_lock = read_json(CONFIG / "locked_squad.json", {})\n    team = read_json(DATA / "team.json", {})\n    latest = read_json(DATA / "latest.json", {})\n    understat = read_json(DATA / "understat_tactical_v4.json", {})\n    prices = read_json(DATA / "prices.json", {})\n    locked_for_search = effective_planning_squad(team, configured_lock, latest)\n    candidates = build_candidates(predictions, universe)\n    tactical = build_tactical_interactions(predictions, universe, understat)\n    current = _semantic_fingerprint(\n        predictions, universe, locked_for_search, understat,\n        candidates=candidates, tactical_interactions=tactical, prices=prices,\n    )\n''',
)

print("2D package worker/fan-in aligned exactly to canonical planning, candidates, tactical and semantic contracts")

# acceptance trigger 2026-09-03: re-run exact 2D root-partition benchmark before permanent promotion
