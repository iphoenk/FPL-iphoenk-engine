from pathlib import Path

p = Path('src/v5/decision/lineup_optimizer.py')
s = p.read_text(encoding='utf-8')

if 'from functools import lru_cache\n' not in s:
    s = s.replace(
        'from collections import Counter\nfrom typing import Any, Iterable, Mapping\n',
        'from collections import Counter\nfrom functools import lru_cache\nfrom typing import Any, Iterable, Mapping\n',
        1,
    )
if '@lru_cache(maxsize=1)\ndef _cfg()' not in s:
    if s.count('def _cfg() -> dict[str, Any]:\n') != 1:
        raise SystemExit('unexpected _cfg declaration count')
    s = s.replace('def _cfg() -> dict[str, Any]:\n', '@lru_cache(maxsize=1)\ndef _cfg() -> dict[str, Any]:\n', 1)

start = s.index('def _enumerate_final_candidates(')
end = s.index('\n\ndef best_lineup(', start)
new_function = '''def _enumerate_final_candidates(players: list[dict[str, Any]], gw: int, lineup_rules: dict[str, Any]) -> list[dict[str, Any]]:
    context = _selection_context(players, gw)
    indexed = context["players"]
    metrics = context["metrics"]
    lineup_cfg = _cfg()["lineup"]
    starting_size = _required_int(lineup_rules, "starting_xi_size", "rules.lineup")
    required_gk = _required_int(lineup_rules, "starting_goalkeepers", "rules.lineup")
    legal_formations = {str(value) for value in lineup_rules.get("legal_formations") or ()}
    candidates: list[dict[str, Any]] = []
    all_ids = {int(player["element"]) for player in indexed}

    # Enumerate the full legal XI universe using only precomputed base metrics.
    # Bounded risk arbitration is a close-call tiebreak, so computing it for
    # every distant candidate is both semantically unnecessary and expensive.
    for combo in itertools.combinations(indexed, starting_size):
        rows = list(combo)
        if sum(1 for player in rows if player.get("position") == "GK") != required_gk:
            continue
        counts = {
            position: sum(1 for player in rows if player.get("position") == position)
            for position in ("DEF", "MID", "FWD")
        }
        formation = f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"
        if formation not in legal_formations:
            continue
        starter_metrics = [metrics[int(player["element"])] for player in rows]
        base_score = sum(item["score"] for item in starter_metrics)
        candidates.append(
            {
                "formation": formation,
                "starters": rows,
                "selection_score": round(base_score, 4),
                "base_score": round(base_score, 4),
                "risk_adjustment": {
                    "enabled": False,
                    "reason": "outside_close_call_gap",
                    "adjustment": 0.0,
                    "governance": {
                        "bounded_decision_adjustment_only": True,
                        "raw_xpts_unchanged": True,
                        "no_artificial_attacking_formation_bonus": True,
                    },
                },
                "mean": round(sum(item["mean"] for item in starter_metrics), 4),
                "variance": round(sum(item["variance"] for item in starter_metrics), 4),
            }
        )

    base_sorted = sorted(candidates, key=lambda row: (row["base_score"], row["mean"], row["formation"]), reverse=True)
    risk_cfg = lineup_cfg.get("lineup_risk") if isinstance(lineup_cfg.get("lineup_risk"), dict) else {}
    if not bool(risk_cfg.get("enabled", False)) or not base_sorted:
        return base_sorted

    anchor = _f(base_sorted[0].get("base_score"))
    gap = max(0.0, _f(risk_cfg.get("close_call_rerank_gap"), 0.75))
    close: list[dict[str, Any]] = []
    distant: list[dict[str, Any]] = []
    for candidate in base_sorted:
        if anchor - _f(candidate.get("base_score")) > gap + 1e-9:
            distant.append(candidate)
            continue
        rows = candidate["starters"]
        starter_ids = {int(player["element"]) for player in rows}
        bench_rows = [player for player in indexed if int(player["element"]) in all_ids - starter_ids]
        risk = _lineup_risk_adjustment(rows, bench_rows, gw, lineup_cfg)
        enriched = dict(candidate)
        enriched["risk_adjustment"] = risk
        enriched["selection_score"] = round(_f(candidate.get("base_score")) + _f(risk.get("adjustment")), 4)
        close.append(enriched)

    close.sort(key=lambda row: (row["selection_score"], row["base_score"], row["mean"]), reverse=True)
    return close + distant
'''
s = s[:start] + new_function + s[end:]
p.write_text(s, encoding='utf-8')
