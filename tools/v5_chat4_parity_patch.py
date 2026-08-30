from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


projection_path = Path("src/v5/intelligence/projection.py")
text = projection_path.read_text()
text = replace_once(
    text,
    "from src.v5.intelligence.role_intelligence import build_role_intelligence\n",
    "from src.v5.intelligence.robust_rates import robust_attack_rate, validate_config as validate_robust_rate_config\nfrom src.v5.intelligence.role_intelligence import build_role_intelligence\n",
    "projection robust import",
)
text = replace_once(
    text,
    "    cfg = load_json_config(CONFIG)\n    strength = build_team_strength(bootstrap, fixtures)\n",
    "    cfg = load_json_config(CONFIG)\n    robust_cfg = cfg.get(\"early_season_robust_rates\") if isinstance(cfg.get(\"early_season_robust_rates\"), dict) else {}\n    validate_robust_rate_config(robust_cfg)\n    strength = build_team_strength(bootstrap, fixtures)\n",
    "projection robust config",
)
text = replace_once(
    text,
    "    players = []\n    historical_used = 0\n\n    for player in bootstrap.get(\"elements\") or []:\n",
    "    players = []\n    historical_used = 0\n    robust_winsorized_players = 0\n\n    for player in bootstrap.get(\"elements\") or []:\n",
    "projection robust counter",
)
text = replace_once(
    text,
    "        xg90, xg_source = _blended_rate(player, \"expected_goals\", xg_prior, shrink)\n        xa90, xa_source = _blended_rate(player, \"expected_assists\", xa_prior, shrink)\n",
    "        xg90, xg_source, xg_robust = robust_attack_rate(player, \"expected_goals\", xg_prior, robust_cfg)\n        xa90, xa_source, xa_robust = robust_attack_rate(player, \"expected_assists\", xa_prior, robust_cfg)\n        robust_winsorized_players += int(bool(xg_robust.get(\"winsorized\") or xa_robust.get(\"winsorized\")))\n",
    "projection robust rates",
)
text = replace_once(
    text,
    "        xmins_context = {\n            \"team_matches_played\": int((team_rows.get(team_id) or {}).get(\"matches_played\") or 0),\n            \"role_start_probability\": role.get(\"role_start_probability\"),\n            \"rotation_risk\": role.get(\"rotation_risk\"),\n        }\n",
    "        # Role intelligence remains published evidence but is not an independent\n        # quantitative xMins authority. Passing it here double-counted starter evidence.\n        xmins_context = {\n            \"team_matches_played\": int((team_rows.get(team_id) or {}).get(\"matches_played\") or 0),\n        }\n",
    "projection xmins role authority",
)
text = replace_once(
    text,
    "                set_piece_multiplier = 1.0 + _f(role_adjustment.get(\"set_piece_assist_uplift\"), 0.08) * _f(role.get(\"set_piece_share\"))\n                penalty_multiplier = 1.0 + _f(role_adjustment.get(\"penalty_goal_uplift\"), 0.18) * _f(role.get(\"penalty_share\"))\n                attack = (\n                    xg90 * penalty_multiplier * goal_points.get(element_type, 4)\n                    + xa90 * set_piece_multiplier * assist_points\n                ) * share * attack_multiplier\n",
    "                # Role/set-piece evidence is retained for reporting and close-call\n                # context only; it does not silently mutate quantitative xPts.\n                attack = (\n                    xg90 * goal_points.get(element_type, 4)\n                    + xa90 * assist_points\n                ) * share * attack_multiplier\n",
    "projection role xpts mutation",
)
text = replace_once(
    text,
    "                    \"historical_attacking_prior_weight\": round(attack_weight, 4),\n",
    "                    \"historical_attacking_prior_weight\": round(attack_weight, 4),\n                    \"robust_rate_diagnostics\": {\"xg90\": xg_robust, \"xa90\": xa_robust},\n",
    "projection robust diagnostics",
)
text = replace_once(
    text,
    "        \"team_strength\": strength,\n        \"role_intelligence\": {\n",
    "        \"team_strength\": strength,\n        \"robust_attack_rate_model\": robust_cfg.get(\"model\"),\n        \"robust_rate_winsorized_players\": robust_winsorized_players,\n        \"role_projection_governance\": {\n            \"role_evidence_is_advisory_for_quantitative_xpts\": True,\n            \"role_start_probability_not_double_counted_in_xmins\": True,\n            \"set_piece_and_penalty_role_do_not_directly_mutate_xpts\": True,\n        },\n        \"role_intelligence\": {\n",
    "projection governance metadata",
)
projection_path.write_text(text)

lineup_path = Path("src/v5/decision/lineup_optimizer.py")
text = lineup_path.read_text()
text = replace_once(text, "import itertools\n", "import itertools\nfrom collections import Counter\n", "lineup Counter import")
marker = "\ndef _enumerate_final_candidates(players: list[dict[str, Any]], gw: int, lineup_rules: dict[str, Any]) -> list[dict[str, Any]]:\n"
if text.count(marker) != 1:
    raise SystemExit("lineup helper insertion marker missing")
helpers = '''
def _defensive_route_proxy(player: dict[str, Any], gw: int) -> float:
    for row in player.get("xpts_by_gw") or []:
        if not isinstance(row, dict) or int(row.get("gw") or -1) != int(gw):
            continue
        total = 0.0
        for fixture in row.get("fixtures") or []:
            components = fixture.get("components") if isinstance(fixture.get("components"), dict) else {}
            total += _f(components.get("clean_sheet"))
            total += _f(components.get("saves"))
            total += _f(components.get("defensive_contribution"))
        return max(0.0, total)
    return 0.0


def _lineup_risk_adjustment(
    starters: list[dict[str, Any]],
    bench_rows: list[dict[str, Any]],
    gw: int,
    lineup_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    cfg = lineup_cfg.get("lineup_risk") if isinstance(lineup_cfg.get("lineup_risk"), dict) else {}
    if not bool(cfg.get("enabled", False)):
        return {"adjustment": 0.0, "enabled": False}

    defensive = [row for row in starters if row.get("position") in {"GK", "DEF"}]
    team_counts = Counter(int(row.get("team_id") or -1) for row in defensive if int(row.get("team_id") or -1) > 0)
    clustered_extras = sum(max(0, count - 1) for count in team_counts.values())
    cluster_penalty = clustered_extras * _f(cfg.get("same_team_defensive_cluster_penalty"), 0.08)

    defensive_route_points = sum(_defensive_route_proxy(row, gw) for row in starters)
    total_points = sum(max(0.0, _cached_metrics(row, gw, "player_score", lineup_cfg)["mean"]) for row in starters)
    route_share = defensive_route_points / total_points if total_points > 1e-9 else 0.0
    concentration_penalty = max(0.0, route_share - 0.50) * _f(cfg.get("defensive_route_concentration_penalty"), 0.06)

    usable_bench = [row for row in bench_rows if row.get("position") != "GK"]
    bench_scores = [max(0.0, _cached_metrics(row, gw, "bench_score", lineup_cfg)["score"]) for row in usable_bench[:3]]
    bench_utility = sum(bench_scores) / max(1, len(bench_scores))
    bench_bonus = min(0.12, _f(cfg.get("bench_utility_weight"), 0.03) * bench_utility / 5.0)

    raw_adjustment = -cluster_penalty - concentration_penalty + bench_bonus
    limit = max(0.0, _f(cfg.get("maximum_close_call_adjustment"), 0.30))
    adjustment = max(-limit, min(limit, raw_adjustment))
    return {
        "enabled": True,
        "adjustment": round(adjustment, 4),
        "defensive_cluster_penalty": round(cluster_penalty, 4),
        "defensive_route_concentration_penalty": round(concentration_penalty, 4),
        "bench_utility_bonus": round(bench_bonus, 4),
        "same_team_defensive_cluster_extras": clustered_extras,
        "defensive_route_share": round(route_share, 4),
        "bench_utility_proxy": round(bench_utility, 4),
        "governance": {
            "bounded_decision_adjustment_only": True,
            "raw_xpts_unchanged": True,
            "no_artificial_attacking_formation_bonus": True,
        },
    }

'''
text = text.replace(marker, "\n" + helpers + marker.lstrip("\n"), 1)

old = '''def _enumerate_final_candidates(players: list[dict[str, Any]], gw: int, lineup_rules: dict[str, Any]) -> list[dict[str, Any]]:
    context = _selection_context(players, gw)
    indexed = context["players"]
    metrics = context["metrics"]
    starting_size = _required_int(lineup_rules, "starting_xi_size", "rules.lineup")
    required_gk = _required_int(lineup_rules, "starting_goalkeepers", "rules.lineup")
    legal_formations = {str(value) for value in lineup_rules.get("legal_formations") or ()}
    candidates: list[dict[str, Any]] = []
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
        candidates.append(
            {
                "formation": formation,
                "starters": rows,
                "selection_score": round(sum(item["score"] for item in starter_metrics), 4),
                "mean": round(sum(item["mean"] for item in starter_metrics), 4),
                "variance": round(sum(item["variance"] for item in starter_metrics), 4),
            }
        )
    candidates.sort(key=lambda row: (row["selection_score"], row["mean"], row["formation"]), reverse=True)
    return candidates
'''
new = '''def _enumerate_final_candidates(players: list[dict[str, Any]], gw: int, lineup_rules: dict[str, Any]) -> list[dict[str, Any]]:
    context = _selection_context(players, gw)
    indexed = context["players"]
    metrics = context["metrics"]
    lineup_cfg = _cfg()["lineup"]
    starting_size = _required_int(lineup_rules, "starting_xi_size", "rules.lineup")
    required_gk = _required_int(lineup_rules, "starting_goalkeepers", "rules.lineup")
    legal_formations = {str(value) for value in lineup_rules.get("legal_formations") or ()}
    candidates: list[dict[str, Any]] = []
    all_ids = {int(player["element"]) for player in indexed}
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
        starter_ids = {int(player["element"]) for player in rows}
        bench_rows = [player for player in indexed if int(player["element"]) in all_ids - starter_ids]
        risk = _lineup_risk_adjustment(rows, bench_rows, gw, lineup_cfg)
        decision_score = base_score + _f(risk.get("adjustment"))
        candidates.append(
            {
                "formation": formation,
                "starters": rows,
                "selection_score": round(decision_score, 4),
                "base_score": round(base_score, 4),
                "risk_adjustment": risk,
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
    close = [row for row in base_sorted if anchor - _f(row.get("base_score")) <= gap + 1e-9]
    distant = [row for row in base_sorted if row not in close]
    close.sort(key=lambda row: (row["selection_score"], row["base_score"], row["mean"]), reverse=True)
    return close + distant
'''
text = replace_once(text, old, new, "lineup final candidate risk rerank")
lineup_path.write_text(text)
