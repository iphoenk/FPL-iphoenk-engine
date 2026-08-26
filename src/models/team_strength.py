from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "team_strength.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def poisson_pmf(lam: float, goals: int) -> float:
    return math.exp(-lam) * (lam ** goals) / math.factorial(goals)


def _team_recent(fixtures: list[dict[str, Any]], team_id: int, window: int) -> dict[str, float]:
    rows = []
    for fixture in fixtures:
        if not fixture.get("finished"):
            continue
        if team_id not in {fixture.get("team_h"), fixture.get("team_a")}:
            continue
        home = fixture.get("team_h") == team_id
        gf = fixture.get("team_h_score") if home else fixture.get("team_a_score")
        ga = fixture.get("team_a_score") if home else fixture.get("team_h_score")
        if gf is None or ga is None:
            continue
        rows.append((fixture.get("kickoff_time") or "", int(gf), int(ga), home))
    rows.sort(key=lambda x: x[0], reverse=True)
    rows = rows[:window]
    if not rows:
        return {"matches": 0, "gf": 0.0, "ga": 0.0, "gf_home": 0.0, "ga_home": 0.0, "gf_away": 0.0, "ga_away": 0.0}
    home_rows = [r for r in rows if r[3]]
    away_rows = [r for r in rows if not r[3]]
    avg = lambda values: sum(values) / len(values) if values else 0.0
    return {
        "matches": len(rows),
        "gf": avg([r[1] for r in rows]),
        "ga": avg([r[2] for r in rows]),
        "gf_home": avg([r[1] for r in home_rows]),
        "ga_home": avg([r[2] for r in home_rows]),
        "gf_away": avg([r[1] for r in away_rows]),
        "ga_away": avg([r[2] for r in away_rows]),
    }


def build_team_strength(bootstrap: dict[str, Any], fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = load_config()
    teams = list(bootstrap.get("teams") or [])
    finished = [f for f in fixtures if f.get("finished") and f.get("team_h_score") is not None and f.get("team_a_score") is not None]
    min_finished = int(cfg.get("minimum_finished_matches_for_league_baseline") or 10)
    if len(finished) >= min_finished:
        home_base = sum(_f(f.get("team_h_score")) for f in finished) / len(finished)
        away_base = sum(_f(f.get("team_a_score")) for f in finished) / len(finished)
        baseline_source = "current_season_finished_fixtures"
    else:
        home_base = _f(cfg.get("prior_home_goals"), 1.55)
        away_base = _f(cfg.get("prior_away_goals"), 1.25)
        baseline_source = "configured_prior_small_sample_guard"

    strength_fields = ["strength_attack_home", "strength_attack_away", "strength_defence_home", "strength_defence_away"]
    means = {}
    for field in strength_fields:
        vals = [_f(t.get(field)) for t in teams if _f(t.get(field)) > 0]
        means[field] = sum(vals) / len(vals) if vals else 1.0

    window = int(cfg.get("recent_window_matches") or 8)
    recent_full = max(1, int(cfg.get("recent_matches_for_full_weight") or 6))
    recent_max = clamp(_f(cfg.get("recent_form_weight_max"), 0.35), 0.0, 1.0)
    official_weight = clamp(_f(cfg.get("official_strength_weight"), 0.65), 0.0, 1.0)
    rows = []
    for team in teams:
        recent = _team_recent(fixtures, int(team["id"]), window)
        recent_weight = min(recent_max, recent_max * recent["matches"] / recent_full)
        base_official_weight = official_weight
        total = base_official_weight + recent_weight
        if total <= 0:
            base_official_weight, recent_weight, total = 1.0, 0.0, 1.0
        base_official_weight /= total
        recent_weight /= total

        def official_idx(field: str) -> float:
            mean = means.get(field) or 1.0
            return max(0.2, _f(team.get(field), mean) / mean)

        def recent_attack(value: float, league_base: float) -> float:
            return clamp(value / max(0.2, league_base), 0.45, 1.85) if recent["matches"] else 1.0

        def recent_defence(value: float, league_base: float) -> float:
            return clamp(league_base / max(0.2, value), 0.45, 1.85) if recent["matches"] else 1.0

        atk_home = base_official_weight * official_idx("strength_attack_home") + recent_weight * recent_attack(recent.get("gf_home") or recent["gf"], home_base)
        atk_away = base_official_weight * official_idx("strength_attack_away") + recent_weight * recent_attack(recent.get("gf_away") or recent["gf"], away_base)
        def_home = base_official_weight * official_idx("strength_defence_home") + recent_weight * recent_defence(recent.get("ga_home") or recent["ga"], away_base)
        def_away = base_official_weight * official_idx("strength_defence_away") + recent_weight * recent_defence(recent.get("ga_away") or recent["ga"], home_base)
        rows.append({
            "team_id": int(team["id"]),
            "team": team.get("name"),
            "matches_played": int(recent["matches"]),
            "attack_home_index": round(atk_home, 4),
            "attack_away_index": round(atk_away, 4),
            "defence_home_index": round(def_home, 4),
            "defence_away_index": round(def_away, 4),
            "recent": recent,
            "weights": {"official": round(base_official_weight, 4), "recent": round(recent_weight, 4)},
        })

    by_id = {r["team_id"]: r for r in rows}
    matchup_rows = []
    lam_min = _f(cfg.get("lambda_min"), 0.2)
    lam_max = _f(cfg.get("lambda_max"), 3.5)
    max_goals = int(cfg.get("poisson_max_goals") or 8)
    for fixture in fixtures:
        if fixture.get("finished"):
            continue
        h = by_id.get(int(fixture.get("team_h") or -1))
        a = by_id.get(int(fixture.get("team_a") or -1))
        if not h or not a:
            continue
        home_xg = clamp(home_base * h["attack_home_index"] / max(0.2, a["defence_away_index"]), lam_min, lam_max)
        away_xg = clamp(away_base * a["attack_away_index"] / max(0.2, h["defence_home_index"]), lam_min, lam_max)
        hp = [poisson_pmf(home_xg, g) for g in range(max_goals + 1)]
        ap = [poisson_pmf(away_xg, g) for g in range(max_goals + 1)]
        home_win = draw = away_win = 0.0
        for hg, ph in enumerate(hp):
            for ag, pa in enumerate(ap):
                if hg > ag:
                    home_win += ph * pa
                elif hg == ag:
                    draw += ph * pa
                else:
                    away_win += ph * pa
        matchup_rows.append({
            "event": fixture.get("event"),
            "kickoff_time": fixture.get("kickoff_time"),
            "team_h": h["team_id"],
            "team_a": a["team_id"],
            "home_expected_goals": round(home_xg, 4),
            "away_expected_goals": round(away_xg, 4),
            "home_clean_sheet_probability": round(math.exp(-away_xg), 4),
            "away_clean_sheet_probability": round(math.exp(-home_xg), 4),
            "home_2plus_probability": round(1 - math.exp(-home_xg) * (1 + home_xg), 4),
            "away_2plus_probability": round(1 - math.exp(-away_xg) * (1 + away_xg), 4),
            "home_win_probability": round(home_win, 4),
            "draw_probability": round(draw, 4),
            "away_win_probability": round(away_win, 4),
        })

    return {
        "model": cfg.get("model_id"),
        "baseline": {
            "home_goals": round(home_base, 4),
            "away_goals": round(away_base, 4),
            "source": baseline_source,
            "finished_matches": len(finished),
        },
        "teams": rows,
        "matchups": matchup_rows,
    }
