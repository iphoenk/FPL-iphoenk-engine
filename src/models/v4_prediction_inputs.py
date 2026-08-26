from __future__ import annotations

from collections import defaultdict

from src.models.player_identity import norm_name
from src.utils import DATA, read_json


def f(value, default=0.0):
    try:
        if value in (None, ""):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _element_id(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def aggregate_advanced(core_rows, shot_rows, match_rows):
    """Resolve community enrichment by official element ID and aggregate per-90 rates."""
    out = {}
    for row in core_rows or []:
        element = _element_id(row.get("id"))
        if element is None:
            continue
        out[element] = {
            "xg_per90": max(0.0, f(row.get("expected_goals_per_90"))),
            "xa_per90": max(0.0, f(row.get("expected_assists_per_90"))),
            "defensive_contribution_per90": max(0.0, f(row.get("defensive_contribution_per_90"))),
            "minutes": max(0.0, f(row.get("minutes"))),
            "sources": ["fpl_core_insights:players"],
            "identity_match": "official_element_id",
        }

    deep = defaultdict(lambda: {"minutes": 0.0, "xg": 0.0, "xa": 0.0, "def": 0.0, "rows": 0})
    for row in match_rows or []:
        element = _element_id(row.get("player_id"))
        if element is None:
            continue
        d = deep[element]
        d["minutes"] += max(0.0, f(row.get("minutes_played")))
        d["xg"] += max(0.0, f(row.get("xg")))
        d["xa"] += max(0.0, f(row.get("xa")))
        d["def"] += max(0.0, f(row.get("defensive_contributions")))
        d["rows"] += 1

    shot_xg = defaultdict(float)
    for row in shot_rows or []:
        element = _element_id(row.get("player_id"))
        if element is not None:
            shot_xg[element] += max(0.0, f(row.get("xg")))

    for element, d in deep.items():
        if d["minutes"] <= 0:
            continue
        base = out.setdefault(element, {"sources": [], "identity_match": "official_element_id"})
        base["xg_per90"] = min(3.0, 90 * (d["xg"] if d["xg"] > 0 else shot_xg[element]) / d["minutes"])
        base["xa_per90"] = min(2.0, 90 * d["xa"] / d["minutes"])
        if d["def"] > 0:
            base["defensive_contribution_per90"] = min(40.0, 90 * d["def"] / d["minutes"])
        base["minutes"] = d["minutes"]
        base["sources"] = list(dict.fromkeys([*base.get("sources", []), "fpl_core_insights:playermatchstats"]))
        if shot_xg[element] > 0:
            base["sources"].append("fpl_core_insights:shots")
    return out


def build_last_season_index(elements, payload):
    rows = list((payload or {}).get("rows") or [])
    by_code = {str(row.get("code")): row for row in rows if row.get("code") not in (None, "")}
    by_name = defaultdict(list)
    for row in rows:
        full = norm_name(f"{row.get('first_name', '')} {row.get('second_name', '')}")
        if full:
            by_name[full].append(row)
    result = {}
    for player in elements:
        row = by_code.get(str(player.get("code")))
        match = "stable_player_code" if row else None
        if row is None:
            full = norm_name(f"{player.get('first_name', '')} {player.get('second_name', '')}")
            candidates = by_name.get(full, [])
            if len(candidates) == 1:
                row, match = candidates[0], "unique_full_name"
        if row is None:
            continue
        minutes = max(0.0, f(row.get("minutes")))
        starts = max(0.0, f(row.get("starts")))
        if minutes <= 0:
            continue
        xg90 = f(row.get("expected_goals_per_90"), -1)
        xa90 = f(row.get("expected_assists_per_90"), -1)
        if xg90 < 0:
            xg90 = 90 * max(0.0, f(row.get("expected_goals"))) / minutes
        if xa90 < 0:
            xa90 = 90 * max(0.0, f(row.get("expected_assists"))) / minutes
        result[int(player["id"])] = {
            "minutes": minutes,
            "starts": starts,
            "xg_per90": max(0.0, xg90),
            "xa_per90": max(0.0, xa90),
            "start_rate": min(1.0, starts / 38),
            "avg_minutes_when_start": min(90.0, max(45.0, minutes / max(1.0, starts))),
            "source": f"vaastav:{payload.get('season', 'previous_season')}",
            "identity_match": match,
        }
    return result


def load_prediction_enrichment(elements, stats_gw=None):
    suffix = f"gw{int(stats_gw)}" if stats_gw else None
    core = read_json(DATA / "stats" / f"core_insights_{suffix}.json", {}) if suffix else {}
    shots = read_json(DATA / "stats" / f"shots_{suffix}.json", {}) if suffix else {}
    matches = read_json(DATA / "stats" / f"playermatchstats_{suffix}.json", {}) if suffix else {}
    previous = read_json(DATA / "stats" / "vaastav_previous_season.json", {})
    return {
        "advanced": aggregate_advanced(core.get("rows"), shots.get("rows"), matches.get("rows")),
        "last_season": build_last_season_index(elements, previous),
        "meta": {
            "stats_gw": stats_gw,
            "advanced_files": [name for name, obj in (("core_insights", core), ("shots", shots), ("playermatchstats", matches)) if obj.get("rows")],
            "last_season": previous.get("season"),
        },
    }
