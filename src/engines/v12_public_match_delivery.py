from __future__ import annotations

"""Public-first MATCH delivery from V6 Official FPL facts.

This is a presentation adapter, not a new scoring/model authority. It uses the
existing live_state_service scoring and canonical MATCH renderer. No credentials,
private current-team state, optimizer XI, or new Monte Carlo path are consulted.
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from src.engines import live_state_service
from src.engines.v12_official_public_scoring import score_entry, rank_live
from src.engines.v12_delivery_reliability import write_serving_artifacts
from src.engines.v12_report_orchestration import (
    materialize_match_report,
    render_match_text,
)
from src.engines.visible_mode_presentation_locks import validate_match_presentation_lock

CANONICAL = Path("control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt")
EXPECTED = [f"MATCH{i}" for i in range(1, 14)]


class PublicMatchError(RuntimeError):
    pass


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicMatchError(f"required public artifact invalid: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PublicMatchError(f"required public artifact is not an object: {path.name}")
    return payload


def _instant(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicMatchError("invalid public timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PublicMatchError("public timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _validated_inputs(root: Path, slot: str) -> tuple[int, int, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    public = root / "data/v6"
    # A new DEEP/PRICE prefetch may advance latest.json between the MATCH
    # acquisition and rendering. The exact stored occurrence owns the facts.
    _instant(slot)
    token = slot.replace(":", "").replace("+", "_plus_").replace("-", "").replace("T", "_")
    occurrence = public / "report_prefetch/occurrences" / f"match_mode__{token}.json"
    pref = _read(occurrence if occurrence.is_file() else public / "report_prefetch/latest.json")
    if pref.get("report_kind") != "match_mode" or pref.get("target_logical_report_slot") != slot:
        raise PublicMatchError("MATCH_PREFETCH_OCCURRENCE_MISMATCH")
    if pref.get("public_core_complete") is not True:
        raise PublicMatchError("PUBLIC_CORE_NOT_COMPLETE")
    if pref.get("live_requested") is not True or pref.get("mini_league_requested") is not True:
        raise PublicMatchError("MATCH_SCOPE_NOT_REQUESTED")
    gw = int(pref.get("gw") or 0)
    entry = int(pref.get("entry_id") or 0)
    league = int(pref.get("priority_league_id") or 0)
    if gw < 1 or entry < 1 or league < 1:
        raise PublicMatchError("MATCH_PUBLIC_IDENTITY_INCOMPLETE")
    if _instant(pref.get("generated_at")) < _instant(slot) - timedelta(minutes=35):
        raise PublicMatchError("MATCH_PREFETCH_STALE")
    base = public / "mini_leagues" / str(league)
    members = _read(base / f"gw_{gw}_manager_picks.json")
    standings = _read(base / "standings.json")
    event = _read(base / "live_state.json")
    entries = members.get("entries") or {}
    expected = int(pref.get("expected_manager_count") or members.get("expected_manager_count") or 0)
    valid_entries = all(
        len(record.get("picks") or []) == 15
        and len({int(p.get("element_id") or 0) for p in record.get("picks") or []}) == 15
        for record in entries.values()
    )
    if (
        expected < 1
        or members.get("gw") != gw
        or members.get("complete") is not True
        or int(members.get("expected_manager_count") or 0) != expected
        or int(members.get("submitted_picks_available_count") or 0) != expected
        or len(entries) != expected
        or len(standings.get("managers") or []) != expected
        or not valid_entries
        or event.get("gw") != gw
        or event.get("status") != "AVAILABLE"
        or event.get("authority") != "OFFICIAL_FPL"
    ):
        raise PublicMatchError("MATCH_PUBLIC_58_OR_LIVE_INCOMPLETE")
    if _instant(event.get("checked_at")) < _instant(slot) - timedelta(minutes=35):
        raise PublicMatchError("MATCH_LIVE_STALE")
    own = entries.get(str(entry)) or {}
    picks = list(own.get("picks") or [])
    ids = [int(p.get("element_id") or 0) for p in picks]
    if len(ids) != 15 or len(set(ids)) != 15 or min(ids) <= 0:
        raise PublicMatchError("MATCH_OFFICIAL_SUBMITTED_15_REQUIRED")
    active_chip = str(own.get("active_chip") or "").lower()
    required_scoring = 15 if active_chip in {"bboost", "bench_boost"} else 11
    if sum(int(p.get("multiplier") or 0) > 0 for p in picks) != required_scoring:
        raise PublicMatchError("MATCH_LOCKED_SCORING_COUNT_INVALID")
    return gw, entry, pref, members, standings, event


def _bootstrap(root: Path, gw: int) -> dict[str, Any]:
    public = root / "data/v6"
    players = _read(public / "normalized/canonical_players.json")
    teams = _read(public / "normalized/canonical_teams.json")
    elements = [
        {
            "id": int(row["official_fpl_element_id"]),
            "web_name": row.get("web_name"),
            "team": row.get("team_id"),
            "element_type": row.get("element_type"),
        }
        for row in players.get("players") or []
        if row.get("official_fpl_element_id") is not None
    ]
    return {
        "elements": elements,
        "teams": [
            {"id": row.get("official_fpl_team_id"), "name": row.get("name"), "short_name": row.get("short_name")}
            for row in teams.get("teams") or []
        ],
        "element_types": [
            {"id": 1, "singular_name_short": "GK"},
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
        "events": [{"id": gw, "finished": False, "data_checked": False}],
    }


def _official_snapshot(root: Path, gw: int, entry: int, members: dict[str, Any], event: dict[str, Any], slot: str) -> dict[str, Any]:
    picks = (members["entries"][str(entry)]).get("picks") or []
    fixtures = _read(root / "data/v6/normalized/canonical_fixtures.json").get("fixtures") or []
    official = _read(root / "data/v6/current/official_fpl.json").get("official") or {}
    score_by_id = {
        int(row.get("id")): row for row in official.get("fixtures") or []
        if isinstance(row, dict) and row.get("id") is not None
    }
    match_path = root / f"data/v6/report_prefetch/official_match_gw_{gw}.json"
    fresh_match = _read(match_path) if match_path.is_file() else {}
    match_api_fresh = (
        fresh_match.get("status") == "AVAILABLE"
        and fresh_match.get("gw") == gw
        and bool(fresh_match.get("fixtures"))
        and _instant(fresh_match["generated_at"]) >= _instant(slot) - timedelta(minutes=35)
    ) if fresh_match else False
    matches = []
    for row in ([] if match_api_fresh else fixtures):
        if int(row.get("event") or 0) != gw:
            continue
        fixture = dict(row)
        fixture["id"] = row.get("official_fpl_fixture_id")
        raw = score_by_id.get(int(fixture["id"] or 0), {})
        for key in ("team_h_score", "team_a_score", "finished_provisional"):
            if key in raw:
                fixture[key] = raw[key]
        matches.append(fixture)
    if match_api_fresh:
        matches = [dict(row) for row in fresh_match["fixtures"]
                   if int(row.get("event") or 0) == gw]
    bootstrap = _bootstrap(root, gw)
    official_bootstrap = official.get("bootstrap") or {}
    event_meta = fresh_match.get("event_meta") if match_api_fresh else None
    event_meta = event_meta or next(
        (row for row in official_bootstrap.get("events") or [] if int(row.get("id") or 0) == gw),
        None,
    )
    if event_meta:
        bootstrap["events"] = [event_meta]
    return {
        "bootstrap": bootstrap,
        "phase": {"scoring_gw": gw},
        "event_status": fresh_match.get("event_status") if match_api_fresh else official.get("event_status") or {},
        "match_api_fresh": match_api_fresh,
        "fixtures": matches,
        "picks": {
            "picks": [
                {
                    "element": int(p["element_id"]),
                    "position": int(p["squad_position"]),
                    "multiplier": int(p.get("multiplier") or 0),
                    "is_captain": p.get("captain") is True,
                    "is_vice_captain": p.get("vice_captain") is True,
                }
                for p in picks
            ],
            "entry_history": (members["entries"][str(entry)]).get("entry_history"),
            "automatic_subs": (members["entries"][str(entry)]).get("automatic_subs"),
            "active_chip": (members["entries"][str(entry)]).get("active_chip"),
        },
        "event_live": {
            "elements": [
                {
                    "id": row["element_id"],
                    "stats": {
                        "total_points": row.get("total_points", 0),
                        "minutes": row.get("minutes", 0),
                        "bonus": row.get("bonus", 0),
                        "bps": row.get("bps", 0),
                    },
                }
                for row in event.get("elements") or []
            ]
        },
    }


def _exposure(
    members: dict[str, Any],
    event: dict[str, Any],
    standings: dict[str, Any],
    entry: int,
    names: dict[int, str],
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """League ranking requires 58 provable public hits and previous totals."""
    snapshot = snapshot or {"bootstrap": {"elements": []}, "fixtures": []}
    points = {
        int(row["element_id"]): int(row["total_points"])
        for row in event.get("elements") or []
        if isinstance(row.get("total_points"), int)
    }
    minutes = {
        int(row["element_id"]): int(row["minutes"])
        for row in event.get("elements") or []
        if isinstance(row.get("minutes"), int)
    }
    player_teams = {
        int(p["id"]): int(p["team"])
        for p in snapshot["bootstrap"]["elements"]
        if p.get("team") is not None
    }
    finished_teams = set()
    for fixture in snapshot.get("fixtures") or []:
        if fixture.get("finished") is True:
            for side in ("team_h", "team_a"):
                if fixture.get(side) is not None:
                    finished_teams.add(int(fixture[side]))
    static = {int(r["entry_id"]): r for r in standings.get("managers") or []}
    records = members.get("entries") or {}
    n = len(records)
    counts: dict[int, dict[str, int]] = defaultdict(
        lambda: {"owned": 0, "starter": 0, "bench": 0, "captain": 0, "vice": 0, "eo": 0}
    )
    scored = []
    captains: dict[int, str] = {}
    for key, record in records.items():
        eid = int(key)
        calc = score_entry(
            record, points, published_standing=static.get(eid),
            player_teams=player_teams, finished_teams=finished_teams,
            live_minutes=minutes,
        )
        scored.append({"entry_id": eid, **calc})
        # Ownership and captaincy are Official submitted-pick facts even
        # when a particular manager's live scoring cannot be calculated.
        for p in record.get("picks") or []:
            pid = int(p["element_id"])
            multiplier = int((calc.get("multipliers") or {}).get(pid, p.get("multiplier") or 0))
            counts[pid]["owned"] += 1
            counts[pid]["starter"] += int(multiplier > 0)
            counts[pid]["bench"] += int(multiplier == 0)
            counts[pid]["captain"] += int(p.get("captain") is True)
            counts[pid]["vice"] += int(p.get("vice_captain") is True)
            counts[pid]["eo"] += multiplier
            if p.get("captain") is True:
                captains[eid] = names.get(pid, str(pid))
    complete_points = (
        n == len(static)
        and len(scored) == n
        and all(row.get("net_points") is not None
                and row.get("previous_overall_points") is not None
                and row.get("baseline_verified") is True
                and row.get("autosub_state") != "PENDING"
                for row in scored)
    )
    ordered = rank_live(scored) if complete_points else []
    by_entry = {r["entry_id"]: r for r in ordered}
    ours = by_entry.get(entry)
    own_static = static.get(entry) or {}
    own_static_rank = own_static.get("league_rank")
    rival = []
    for eid, row in static.items():
        if eid == entry:
            continue
        calc = by_entry.get(eid) or {}
        rival.append({
            "entry_id": eid,
            "rank": calc.get("live_rank"),
            "published_rank": row.get("league_rank"),
            "manager": row.get("manager_name") or row.get("team_name"),
            "live_points": calc.get("net_points"),
            "live_overall": calc.get("live_overall_points"),
            "gap": (calc.get("live_overall_points") - ours["live_overall_points"])
                if ours and calc.get("live_overall_points") is not None else None,
            "captain": captains.get(eid, "UNAVAILABLE"),
            "key_threat": "Provisional FPL scoring" if ordered else "Insufficient public net scoring evidence",
            "key_shield": "Pending fixture corrections" if ordered else "UNAVAILABLE",
            "tied_position_provisional": calc.get("tie_unresolved"),
        })
    rival.sort(key=lambda row: (
        row.get("rank") if row.get("rank") is not None else 9999,
        int(row["entry_id"]),
    ))
    def stat(value: int) -> dict[str, Any]:
        return {"numerator": value, "denominator": n,
                "percentage": round(100 * value / n, 2) if n else None}

    our_calculation = next((row for row in scored if row["entry_id"] == entry), {})
    our_ids = {int(p["element_id"]) for p in records[str(entry)]["picks"]}
    exposure = []
    for player in sorted(our_ids):
        cnt = counts[player]
        exposure.append({
            "player": names.get(player, str(player)), "denominator": n,
            **{field: stat(cnt[field]) for field in ("owned", "starter", "bench", "captain", "vice", "eo")},
            "live_consequence": f"{points.get(player, 'UNAVAILABLE')} raw pts; EO {round(100 * cnt['eo'] / n, 1)}%" if n else "UNAVAILABLE",
        })
    leader = ordered[0] if ordered else None
    by_rank = {r["live_rank"]: r for r in ordered if r.get("live_rank") is not None}
    leader_gap = (leader["live_overall_points"] - ours["live_overall_points"]) if leader and ours else None
    top3_gap = (by_rank.get(3, ordered[min(2, len(ordered) - 1)])["live_overall_points"] - ours["live_overall_points"]) if ordered and ours else None
    top5_gap = (by_rank.get(5, ordered[min(4, len(ordered) - 1)])["live_overall_points"] - ours["live_overall_points"]) if ordered and ours else None
    unresolved = sorted([
        {"entry_id": r["entry_id"], "reason": r.get("reason") or
         ("MISSING_HIT_OR_BASELINE" if r.get("hit") is None or r.get("previous_overall_points") is None else "AUTOSUB_PENDING")}
        for r in scored
        if r.get("net_points") is None or r.get("previous_overall_points") is None
        or r.get("autosub_state") == "PENDING"
    ], key=lambda r: r["entry_id"])
    return {
        "status": "COMPLETE" if ordered else "DEGRADED",
        "league_name": standings.get("league_name") or "ICON+ League",
        "expected_manager_count": n, "collected_manager_count": len(scored),
        "submitted_picks_exposure": {"state": "COMPLETE", "expected_count": n, "available_count": n},
        "live_standings_rank": {
            "state": "PROVISIONAL" if ordered else "UNAVAILABLE",
            "reason": "OFFICIAL_PUBLIC_GW_SCORING_PROVISIONAL_TIE_BREAK_PENDING" if ordered else "INCOMPLETE_HIT_AUTOSUB_BASELINE_EVIDENCE",
            "expected_count": n, "available_count": len(ordered),
        },
        "user_summary": {"rank": ours.get("live_rank") if ours else None,
                         "live_points": ours.get("net_points") if ours else None},
        "current_live_rank": ours.get("live_rank") if ours else None,
        "current_live_points": ours.get("net_points") if ours else None,
        "current_live_overall": ours.get("live_overall_points") if ours else None,
        "leader_gap": leader_gap, "top3_gap": top3_gap, "top5_gap": top5_gap,
        "own_gross_points": our_calculation.get("gross_points"),
        "own_hit": our_calculation.get("hit"),
        "own_calculation": our_calculation,
        "material_player_exposure": exposure,
        "competitive_rival_live_consequence": rival,
        "all_manager_live_rows": ordered if ordered else scored,
        "unresolved_manager_evidence": unresolved,
        "league_raw_gross_points": {str(r["entry_id"]): r.get("gross_points") for r in scored},
        "rival_live_points": {"state": "PROVISIONAL_NET" if ordered else "UNAVAILABLE"},
        "eo": {"state": "COMPLETE" if len(scored) == n else "UNAVAILABLE",
               "denominator": n, "definition": "sum of Official submitted scoring multipliers / all managers"},
        "live_rank_not_fabricated": True, "own_static_rank": own_static_rank,
        "published_versus_calculated": {
            "published_rank": own_static_rank,
            "calculated_rank": ours.get("live_rank") if ours else None,
            "calculated_rank_provisional": bool(ordered),
        },
    }


def run(runtime_data_root: Path, report_slot: str, output_dir: Path) -> dict[str, Any]:
    gw, entry, pref, members, standings, event = _validated_inputs(runtime_data_root, report_slot)
    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_snapshot = _official_snapshot(runtime_data_root, gw, entry, members, event, report_slot)
    input_file = output_dir / ".match-public-input.json"
    input_file.write_text(json.dumps(canonical_snapshot), encoding="utf-8")
    live_state_service.OFFICIAL = input_file
    live_state_service.OUT = output_dir / ".match-public-provisional.json"
    live_state_service.PREDICTION_LEDGER = output_dir / ".match-no-prediction.json"
    live = live_state_service.run()
    if live.get("submitted_picks_status") != "AVAILABLE" or len(live.get("players") or []) != 15:
        raise PublicMatchError("MATCH_SCORING_15_NOT_AVAILABLE")
    # All league captains must resolve through the full Official FPL player
    # universe, not only the 15 players owned by our entry.
    names = {
        int(p["id"]): str(p.get("web_name") or p["id"])
        for p in canonical_snapshot["bootstrap"]["elements"]
    }
    names.update({
        int(p["element"]): str(p.get("name") or names.get(int(p["element"]), p["element"]))
        for p in live.get("players") or []
    })
    icon = _exposure(members, event, standings, entry, names, canonical_snapshot)
    our_calculation = dict(icon.get("own_calculation") or {})
    live["gross_points"] = our_calculation.get("gross_points")
    live["hit"] = our_calculation.get("hit")
    live["net_points"] = our_calculation.get("net_points")
    actual_factors = our_calculation.get("multipliers") or {}
    for row in live.get("players") or []:
        pid = int(row["element"])
        factor = actual_factors.get(pid)
        row["effective_multiplier"] = factor
        if factor is not None and row.get("total_points") is not None:
            row["effective_points"] = factor * int(row["total_points"])
    personal = live.get("personalized_live_score")
    if isinstance(personal, dict):
        personal["hit"] = live["hit"]
        personal["hit_authority"] = "OFFICIAL_PUBLIC_ENTRY_HISTORY" if live["hit"] is not None else "UNAVAILABLE"
        personal["current_effective_total"] = live["gross_points"]
        personal["effective_xi_points"] = live["gross_points"]
        personal["current_net_total"] = live["net_points"]
        personal["autosub_implications"] = {
            **dict(personal.get("autosub_implications") or {}),
            "status": our_calculation.get("autosub_state") or "UNAVAILABLE",
            "official_autosub_count": our_calculation.get("official_autosub_count"),
            "vice_takeover_provisional": our_calculation.get("vice_takeover_provisional"),
        }
    report = materialize_match_report(
        canonical_text=CANONICAL.read_text(encoding="utf-8"),
        live_payload=live,
        icon_live=icon,
        source_freshness={
            "mini_league_submitted_picks": {"status": "AVAILABLE", "checked_at": members.get("generated_at")},
            "live_standings": {"status": icon["live_standings_rank"]["state"], "checked_at": standings.get("generated_at")},
            "match_evidence_feed": {"status": "OFFICIAL_FPL", "checked_at": event.get("checked_at")},
        },
    )
    teams_by_id = {
        int(team["id"]): str(team.get("name") or team["id"])
        for team in canonical_snapshot["bootstrap"]["teams"]
        if team.get("id") is not None
    }
    fixtures = []
    for fixture in canonical_snapshot["fixtures"]:
        home = teams_by_id.get(int(fixture.get("team_h") or 0), "UNKNOWN")
        away = teams_by_id.get(int(fixture.get("team_a") or 0), "UNKNOWN")
        h_score, a_score = fixture.get("team_h_score"), fixture.get("team_a_score")
        score_display = (
            f"{h_score}-{a_score}" if isinstance(h_score, int) and isinstance(a_score, int)
            else "UNAVAILABLE"
        )
        status = "FT" if fixture.get("finished") is True else (
            "LIVE" if fixture.get("started") is True else "NOT_STARTED"
        )
        fixtures.append({
            "fixture": f"{home} vs {away}", "score": score_display,
            "status": status, "kickoff": fixture.get("kickoff_time"),
        })
    for section in report.get("sections") or []:
        if section.get("section_id") == "MATCH1":
            section.setdefault("content", {})["fixture_rows"] = fixtures
    body = render_match_text(report)
    ids = [row.get("section_id") for row in report.get("sections") or []]
    if ids != EXPECTED or body.count("## MATCH ") != 13 or validate_match_presentation_lock():
        raise PublicMatchError("MATCH_13_SECTION_RENDER_CONTRACT_FAILED")
    if "## MATCH 10" not in body or "58/58" not in body or "## MATCH 13" not in body:
        raise PublicMatchError("MATCH10_OR_MATCH13_REAL_CONTENT_MISSING")
    public_complete = (
        icon.get("status") == "COMPLETE"
        and live.get("net_points") is not None
        and canonical_snapshot.get("match_api_fresh") is True
    )
    state = "PASS" if public_complete else "DEGRADED"
    pending = [r for r in ("HITS", "AUTOSUB", "PROVISIONAL_LIVE_RANK") if
               (r == "HITS" and live.get("hit") is None)
               or (r == "AUTOSUB" and our_calculation.get("autosub_state") == "PENDING")
               or (r == "PROVISIONAL_LIVE_RANK" and (icon.get("status") != "COMPLETE"
                                                    or not canonical_snapshot.get("match_api_fresh")))]
    proof = {
        "schema_version": 2, "runner": "V12_PUBLIC_MATCH_DELIVERY",
        "report_mode": "MATCH", "report_slot": report_slot, "planning_gw": gw,
        "runner_status": state, "pre_render_qa_status": "PASS",
        "post_render_qa_status": "PASS", "human_facing_qa_status": "PASS",
        "canonical_expected_section_ids": EXPECTED, "rendered_section_ids": ids,
        "public_team_id": entry, "public_league_id": int(pref["priority_league_id"]),
        "manager_coverage": n if (n := len(members["entries"])) else 0,
        "public_auth_independent": True, "authenticated_finance_claimed": False,
        "live_checked_at": event.get("checked_at"), "prefetch_identity": pref.get("report_prefetch_run_id"),
        "official_match_api_fresh": canonical_snapshot.get("match_api_fresh"),
        "unverified_scopes": pending,
        "stages": [{"stage": "MATCH_PUBLIC_FACTS", "status": "PASS"},
                   {"stage": "MATCH13_RENDER", "status": "PASS"},
                   {"stage": "LIVE_RANK", "status": state,
                    "reason": None if public_complete else "OFFICIAL_PUBLIC_EVIDENCE_INCOMPLETE"}],
    }
    bundle = {
        "schema": "FPL_MASTER_V12_PUBLIC_MATCH_BUNDLE_V1",
        "report_mode": "MATCH", "report_slot": report_slot, "planning_gw": gw,
        "runner_status": state, "root_failure": None if public_complete else "HITS_AUTOSUB_LIVE_RANK_UNVERIFIED",
        "section_manifest": [{"section_id": value, "status": "COMPLETE" if value != "MATCH10" or public_complete else "DEGRADED"} for value in ids],
        "report": report, "visible_body": body, "execution_proof": proof,
        "governance": {"private_auth_required": False, "planning_xi_authority": False,
                       "live_rank_fabricated": False, "monte_carlo_modified": False},
    }
    (output_dir / "report_body.md").write_text(body, encoding="utf-8")
    (output_dir / "stage3_acceptance.json").write_text(json.dumps({
        "contract": "V12_MATCH_STAGE3_NOT_APPLICABLE", "report_mode": "MATCH",
        "status": "NOT_APPLICABLE", "mc_pass_claimed": False,
        "engineering_closure_blocks_report": False,
    }), encoding="utf-8")
    write_serving_artifacts(bundle=bundle, output_dir=output_dir)
    return {"status": "READY_FULL" if public_complete else "READY_DEGRADED",
            "report_slot": report_slot, "sections": len(ids)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-data-root", required=True)
    parser.add_argument("--report-slot", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(run(Path(args.runtime_data_root), args.report_slot, Path(args.output_dir))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
