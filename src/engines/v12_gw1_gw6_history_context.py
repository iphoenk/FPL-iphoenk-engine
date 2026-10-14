from __future__ import annotations

"""Six-GW evidence bridge, not a second fantasy scorer or source collector.

Official FPL remains authoritative for points and gameweek settlement. Only
pre-verified, source-native IDs can enrich the retrospective six-GW player and
fixture context. A provider FT observation never upgrades provisional FPL
points into FINAL, and season totals are never mislabelled per-match evidence.
"""

from collections import Counter
from datetime import datetime, timezone
import math
import re
from typing import Any, Mapping, Sequence

CONTRACT = "V12_GW1_GW6_RETROSPECTIVE_CONTEXT_V1"
POSITION = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
FIELDS_BY_POSITION = {
    "GK": ("minutes", "saves", "goals_prevented", "clean_sheets", "goals_conceded", "total_points"),
    "DEF": ("minutes", "clean_sheets", "defensive_contribution", "goals_scored", "assists", "total_points"),
    "MID": ("minutes", "goals_scored", "assists", "expected_goals", "expected_assists", "defensive_contribution", "total_points"),
    "FWD": ("minutes", "goals_scored", "assists", "expected_goals", "expected_assists", "total_points"),
}
_SCORES = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
_VERIFIED = {"VERIFIED_MANUAL", "EXACT", "VERIFIED"}


def _n(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def _id(value: Any) -> int | None:
    number = _n(value)
    if number is None or number <= 0 or not number.is_integer():
        return None
    return int(number)


def _aware(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo else None


def _source_is_eligible(source: Mapping[str, Any] | None, as_of: str | None) -> bool:
    if not isinstance(source, Mapping):
        return False
    if source.get("source_health") != "GREEN" or source.get("normalization_status") != "NORMALIZED":
        return False
    observed = _aware(source.get("effective_at"))
    cutoff = _aware(as_of)
    return observed is not None and (cutoff is None or observed <= cutoff)


def _source_gate_reason(source: Mapping[str, Any] | None, as_of: str | None) -> str:
    """Explain admission failure without changing the strict as-of contract."""
    if not isinstance(source, Mapping):
        return "SOURCE_NOT_PRESENT"
    if source.get("source_health") != "GREEN":
        return "SOURCE_NOT_GREEN"
    if source.get("normalization_status") != "NORMALIZED":
        return "SOURCE_NOT_NORMALIZED"
    observed, cutoff = _aware(source.get("effective_at")), _aware(as_of)
    if observed is None:
        return "SOURCE_EFFECTIVE_AT_UNVERIFIED"
    if cutoff is None:
        return "REPORT_CUTOFF_UNVERIFIED"
    if observed > cutoff:
        return "SOURCE_AFTER_REPORT_CUTOFF"
    return "PASS"


def _official_player_rows(
    bootstrap: Mapping[str, Any],
    history: Mapping[str, Any],
    historical_gws: Sequence[int],
) -> tuple[list[dict[str, Any]], int]:
    elements = [p for p in bootstrap.get("elements") or [] if isinstance(p, Mapping)]
    histories = history.get("players") or {}
    rows: list[dict[str, Any]] = []
    available = 0
    for element in elements:
        player_id = _id(element.get("id"))
        if player_id is None:
            continue
        role = POSITION.get(_id(element.get("element_type")), "UNKNOWN")
        player_history = (histories.get(str(player_id)) or {}).get("history") or {}
        gw_rows = []
        sums: dict[str, float] = {}
        for gw in historical_gws:
            slot = player_history.get(str(gw)) or {}
            status = str(slot.get("status") or "UNAVAILABLE").upper()
            metrics = dict(slot.get("aggregate") or {})
            if status != "UNAVAILABLE":
                available += 1
            # Pending fixture statistics may be seen but cannot count as FINAL.
            if status in {"FINAL", "DNP", "BLANK"}:
                for metric in FIELDS_BY_POSITION.get(role, ()):
                    value = _n(metrics.get(metric))
                    if value is not None:
                        sums[metric] = sums.get(metric, 0.0) + value
            gw_rows.append({
                "gw": gw, "official_status": status,
                "fixture_count": slot.get("fixture_count"),
                "metrics": {key: metrics[key] for key in FIELDS_BY_POSITION.get(role, ()) if key in metrics},
            })
        rows.append({
            "official_element_id": player_id,
            "name": element.get("web_name"),
            "team_id": _id(element.get("team")),
            "position": role,
            "historical_gws": gw_rows,
            "finalized_only_totals": {k: round(v, 4) for k, v in sorted(sums.items())},
            "provider_skill_observation": {"status": "UNAVAILABLE"},
            "formation_fit": {"status": "UNAVAILABLE", "reason": "MATCH_LEVEL_ROLE_AND_COACH_EVIDENCE_REQUIRED"},
            "coach_fit": {"status": "UNAVAILABLE", "reason": "NO_CAUSAL_COACH_FIT_CALIBRATION"},
        })
    return rows, available


def _attach_understat(
    player_rows: list[dict[str, Any]],
    understat: Mapping[str, Any] | None,
    as_of: str | None,
) -> dict[str, Any]:
    raw = ((understat or {}).get("record_groups") or {}).get("players") or []
    raw = raw if isinstance(raw, list) else []
    eligible = _source_is_eligible(understat, as_of)
    verified = sum(isinstance(p, Mapping) and _id(p.get("official_element_id")) is not None
                   and p.get("identity_status") in _VERIFIED for p in raw)
    gate = _source_gate_reason(understat, as_of)
    summary = {
        "source": "understat", "status": "AVAILABLE" if eligible else "UNAVAILABLE",
        "source_records": len(raw), "verified_source_identity_rows": verified,
        "eligible_verified_rows": verified if eligible else 0,
        "consumed_rows": 0, "verified_join_count": 0,
        "unmapped_provider_count": 0, "season_aggregate_only": True,
        "source_gate": gate, "source_effective_at": (understat or {}).get("effective_at"),
        "report_cutoff_at": as_of, "rejected_reasons": {},
        "decision_influence": "ADVISORY_ONLY",
    }
    if not eligible:
        summary["rejected_reasons"][gate] = len(raw)
        return summary
    by_id: dict[int, dict[str, Any]] = {}
    for p in raw:
        if not isinstance(p, Mapping):
            continue
        eid = _id(p.get("official_element_id"))
        if eid is None or p.get("identity_status") not in _VERIFIED:
            summary["unmapped_provider_count"] += 1
            reason = "SOURCE_IDENTITY_UNVERIFIED"
            summary["rejected_reasons"][reason] = summary["rejected_reasons"].get(reason, 0) + 1
            continue
        if eid in by_id:
            # Ambiguous identity collisions are not counted as a reliable join.
            by_id[eid]["_identity_conflict"] = True
        else:
            by_id[eid] = dict(p)
    for row in player_rows:
        p = by_id.get(row["official_element_id"])
        if not p or p.get("_identity_conflict"):
            continue
        minutes = _n(p.get("time"))
        xg, xa = _n(p.get("xg")), _n(p.get("xa"))
        observations = {}
        for field in ("games", "time", "goals", "assists", "shots", "key_passes",
                      "xg", "xa", "npxg", "xg_chain", "xg_buildup"):
            numeric = _n(p.get(field))
            if numeric is not None:
                observations[field] = round(numeric, 5)
        if minutes and minutes > 0:
            for field in ("xg", "xa", "shots", "key_passes"):
                value = _n(p.get(field))
                if value is not None:
                    observations[f"{field}_per90"] = round(90 * value / minutes, 5)
            if xg is not None and xa is not None:
                observations["xgi"] = round(xg + xa, 5)
                observations["xgi_per90"] = round(90 * (xg + xa) / minutes, 5)
        source_teams = [team.strip() for team in str(p.get("team_title") or "").split(",") if team.strip()]
        mixed_team_season = len(set(source_teams)) > 1
        row["provider_skill_observation"] = {
            "status": "OBSERVED_VERIFIED_ID",
            "source_team_titles": source_teams,
            "mixed_team_season": mixed_team_season,
            "club_specific_team_fit": "UNAVAILABLE_MIXED_TEAM_SEASON" if mixed_team_season else "NOT_CALIBRATED",
            "source": "UNDERSTAT_2026_27",
            "source_native_id": p.get("source_native_id"),
            "effective_at": understat.get("effective_at"),
            "season_aggregate_only": True,
            "not_independent_of_official_points": True,
            "metrics": observations,
            "interpretation": "PROCESS_PROXY_NOT_AN_ABSOLUTE_SKILL_RATING",
        }
        summary["verified_join_count"] += 1
    summary["consumed_rows"] = summary["verified_join_count"]
    summary["rejected_reasons"]["VERIFIED_BUT_NOT_CONSUMED"] = max(
        0, verified - summary["consumed_rows"]
    )
    if not summary["rejected_reasons"]["VERIFIED_BUT_NOT_CONSUMED"]:
        del summary["rejected_reasons"]["VERIFIED_BUT_NOT_CONSUMED"]
    return summary


def _fotmob_matches(
    fotmob: Mapping[str, Any] | None,
    official_fixtures: Sequence[Mapping[str, Any]],
    historical_gws: Sequence[int],
    as_of: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups = (fotmob or {}).get("record_groups") or {}
    raw = groups.get("fixtures") or []
    raw = raw if isinstance(raw, list) else []
    eligible = _source_is_eligible(fotmob, as_of)
    verified = sum(isinstance(f, Mapping) and f.get("identity_status") in _VERIFIED
                   and _id(f.get("official_fixture_id")) is not None for f in raw)
    gate = _source_gate_reason(fotmob, as_of)
    status = {
        "source": "fotmob", "status": "AVAILABLE" if eligible else "UNAVAILABLE",
        "source_records": len(raw), "verified_source_identity_rows": verified,
        "eligible_verified_rows": verified if eligible else 0,
        "historical_scope_rows": 0, "consumed_rows": 0,
        "verified_match_count": 0, "rejected_or_ambiguous": 0,
        "out_of_historical_scope": 0, "source_gate": gate,
        "source_effective_at": (fotmob or {}).get("effective_at"),
        "report_cutoff_at": as_of, "rejected_reasons": {},
        "decision_influence": "ADVISORY_ONLY",
    }
    if not eligible:
        status["rejected_reasons"][gate] = len(raw)
        return [], status
    verified_teams = {}
    for p in groups.get("teams") or []:
        if isinstance(p, Mapping) and p.get("identity_status") in _VERIFIED:
            native_id, official_id = _id(p.get("source_native_id")), _id(p.get("official_team_id"))
            if native_id and official_id:
                verified_teams[native_id] = official_id
    official_by_id = {_id(f.get("id")): f for f in official_fixtures if isinstance(f, Mapping)}
    out = []
    used = set()
    for f in raw:
        if not isinstance(f, Mapping):
            continue
        event = _id(f.get("round"))
        fixture_id = _id(f.get("official_fixture_id"))
        if event not in historical_gws:
            status["out_of_historical_scope"] += 1
            continue
        status["historical_scope_rows"] += 1
        if not fixture_id:
            status["rejected_or_ambiguous"] += 1
            reason = "OFFICIAL_FIXTURE_ID_MISSING"
            status["rejected_reasons"][reason] = status["rejected_reasons"].get(reason, 0) + 1
            continue
        info = f.get("status") or {}
        score = _SCORES.fullmatch(str(info.get("scoreStr") or ""))
        home = verified_teams.get(_id((f.get("home") or {}).get("source_native_id")))
        away = verified_teams.get(_id((f.get("away") or {}).get("source_native_id")))
        official = official_by_id.get(fixture_id)
        if (f.get("identity_status") not in _VERIFIED or fixture_id in used
                or not info.get("finished") or not score or home is None or away is None
                or not official or _id(official.get("event")) != event
                or _id(official.get("team_h")) != home or _id(official.get("team_a")) != away):
            status["rejected_or_ambiguous"] += 1
            reason = ("UNVERIFIED_OR_DUPLICATE_FIXTURE" if f.get("identity_status") not in _VERIFIED or fixture_id in used
                      else "UNFINISHED_OR_INVALID_SCORE" if not info.get("finished") or not score
                      else "TEAM_IDENTITY_UNVERIFIED" if home is None or away is None
                      else "OFFICIAL_FIXTURE_NOT_FOUND" if not official
                      else "OFFICIAL_FIXTURE_GW_OR_TEAM_MISMATCH")
            status["rejected_reasons"][reason] = status["rejected_reasons"].get(reason, 0) + 1
            continue
        used.add(fixture_id)
        gh, ga = int(score.group(1)), int(score.group(2))
        # Official may still be provisional; do not rewrite its settlement.
        out.append({
            "gw": event, "official_fixture_id": fixture_id,
            "home_team_id": home, "away_team_id": away,
            "home_name": (f.get("home") or {}).get("name"),
            "away_name": (f.get("away") or {}).get("name"),
            "home_goals": gh, "away_goals": ga,
            "source": "FOTMOB_VERIFIED_FIXTURE",
            "source_native_id": f.get("source_native_id"),
            "observed_ft": True,
            "official_fpl_final": official.get("finished") is True,
            "fpl_points_settlement": "FINAL" if official.get("finished") is True else "PENDING",
        })
        status["verified_match_count"] += 1
    status["consumed_rows"] = status["verified_match_count"]
    out.sort(key=lambda f: (f["gw"], f["official_fixture_id"]))
    return out, status


def _team_form(matches: Sequence[Mapping[str, Any]], team_id: int) -> dict[str, Any]:
    results = []
    for m in matches:
        is_home = m["home_team_id"] == team_id
        if not is_home and m["away_team_id"] != team_id:
            continue
        own = m["home_goals"] if is_home else m["away_goals"]
        opp = m["away_goals"] if is_home else m["home_goals"]
        results.append({
            "gw": m["gw"], "fixture_id": m["official_fixture_id"],
            "opponent": m["away_name"] if is_home else m["home_name"],
            "opponent_team_id": m["away_team_id"] if is_home else m["home_team_id"],
            "home": is_home, "goals_for": own, "goals_against": opp,
            "result": "W" if own > opp else ("D" if own == opp else "L"),
            "fpl_points_settlement": m["fpl_points_settlement"],
        })
    results.sort(key=lambda x: x["gw"])
    counter = Counter(row["result"] for row in results)
    return {
        "observed_match_count": len(results),
        "wins": counter["W"], "draws": counter["D"], "losses": counter["L"],
        "goals_for": sum(r["goals_for"] for r in results),
        "goals_against": sum(r["goals_against"] for r in results),
        "matches": results,
        "observed_vs_opponents": True,
        "forecast_opponent_fit_inferred": False,
    }


def build_retrospective_context(
    *,
    bootstrap: Mapping[str, Any],
    official_fixtures: Sequence[Mapping[str, Any]],
    full_history: Mapping[str, Any],
    understat: Mapping[str, Any] | None,
    fotmob: Mapping[str, Any] | None,
    report_slot: str | None,
    observation_cutoff_at: str | None = None,
    focus_team_id: int = 6,
    focus_player_ids: Sequence[int] = (154, 40, 165),
    tactical_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich GW1..6 without changing canonical projections or FPL finality."""
    if not _aware(report_slot):
        raise ValueError("report_slot must be timezone-aware to prevent future leakage")
    # Report slot identifies the immutable logical occurrence. Sources acquired
    # before that occurrence's verified prefetch completion may be later than
    # its nominal clock slot; admit them only as current-report advisory.
    if observation_cutoff_at is not None and not _aware(observation_cutoff_at):
        raise ValueError("observation_cutoff_at must be timezone-aware")
    source_cutoff = observation_cutoff_at or report_slot
    gw_ids = list(range(1, 7))
    players, available = _official_player_rows(bootstrap, full_history, gw_ids)
    understat_source = _attach_understat(players, understat, source_cutoff)
    matches, match_source = _fotmob_matches(fotmob, official_fixtures, gw_ids, source_cutoff)
    by_id = {row["official_element_id"]: row for row in players}
    focused = [by_id[player_id] for player_id in focus_player_ids if player_id in by_id]
    formation = {"status": "UNAVAILABLE", "coach_fit_score": None, "formation_fit_score": None}
    observation = dict(tactical_observation or {})
    if (observation.get("evidence_state") == "OBSERVED"
            and _id(observation.get("fixture_id")) in {x["official_fixture_id"] for x in matches}
            and _id(observation.get("team_id")) == focus_team_id
            and _id(observation.get("gw")) in gw_ids
            and observation.get("reference_url")
            and _aware(observation.get("observed_at"))
            and _aware(observation.get("observed_at")) <= _aware(report_slot)):
        formation = {
            "status": "MATCH_SPECIFIC_OBSERVED",
            "fixture_id": observation["fixture_id"],
            "gw": observation["gw"],
            "manager": observation.get("manager"),
            "formation": observation.get("formation"),
            "supporting_url": observation["reference_url"],
            "observed_player_roles": observation.get("player_roles") or {},
            "coach_fit_score": None,
            "formation_fit_score": None,
            "cross_match_generalization_allowed": False,
        }
    by_position = Counter(row["position"] for row in players)
    return {
        "contract": CONTRACT,
        "planning_target": "GW7",
        "historical_gws": gw_ids,
        "official_status": (full_history.get("coverage_gate") or {}).get("status", "UNAVAILABLE"),
        "official_players_in_universe": len(players),
        "official_gw_slots_present": available,
        "expected_official_gw_slots": len(players) * len(gw_ids),
        "official_points_finalized": (full_history.get("coverage_gate") or {}).get("all_historical_gws_finalized") is True,
        "player_position_counts": dict(by_position),
        "source_health": {"understat": understat_source, "fotmob": match_source},
        "players": players,
        "focus_players": focused,
        "focus_team": {
            "team_id": focus_team_id,
            "form_gw1_gw6": _team_form(matches, focus_team_id),
            "tactical_observation": formation,
        },
        "effect_on_projection": "NONE_ADVISORY_ONLY",
        "effect_on_fpl_finality": "NONE",
        "identity_matching": "VERIFIED_SOURCE_NATIVE_IDS_ONLY",
        "season_stats_are_not_match_stats": True,
        "coach_fit_requires_multiple_observed_role_and_manager_matches": True,
        "opponent_fit_is_retrospective_not_forward_forecast": True,
        "source_cutoff_at": source_cutoff,
        "report_logical_slot": report_slot,
        "observation_cutoff_mode": (
            "OCCURRENCE_BOUND_PREFETCH_GENERATED_AT"
            if observation_cutoff_at is not None else "LOGICAL_SLOT"
        ),
        "historical_predeadline_source_asof_admission": "NOT_ASSERTED",
    }
