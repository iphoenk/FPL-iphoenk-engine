from __future__ import annotations

"""Public-first MATCH delivery from V6 Official FPL facts.

This is a presentation adapter, not a new scoring/model authority. It uses the
existing live_state_service scoring and canonical MATCH renderer. No credentials,
private current-team state, optimizer XI, or new Monte Carlo path are consulted.
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.engines import live_state_service
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
    pref = _read(public / "report_prefetch/latest.json")
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
    if _instant(pref.get("generated_at")) < _instant(slot) - __import__("datetime").timedelta(minutes=35):
        raise PublicMatchError("MATCH_PREFETCH_STALE")
    base = public / "mini_leagues" / str(league)
    members = _read(base / f"gw_{gw}_manager_picks.json")
    standings = _read(base / "standings.json")
    event = _read(base / "live_state.json")
    entries = members.get("entries") or {}
    if (
        members.get("gw") != gw
        or members.get("complete") is not True
        or int(members.get("expected_manager_count") or 0) != 58
        or int(members.get("submitted_picks_available_count") or 0) != 58
        or len(entries) != 58
        or len(standings.get("managers") or []) != 58
        or event.get("gw") != gw
        or event.get("status") != "AVAILABLE"
        or event.get("authority") != "OFFICIAL_FPL"
    ):
        raise PublicMatchError("MATCH_PUBLIC_58_OR_LIVE_INCOMPLETE")
    if _instant(event.get("checked_at")) < _instant(slot) - __import__("datetime").timedelta(minutes=35):
        raise PublicMatchError("MATCH_LIVE_STALE")
    own = entries.get(str(entry)) or {}
    picks = list(own.get("picks") or [])
    ids = [int(p.get("element_id") or 0) for p in picks]
    if len(ids) != 15 or len(set(ids)) != 15 or min(ids) <= 0:
        raise PublicMatchError("MATCH_OFFICIAL_SUBMITTED_15_REQUIRED")
    if sum(int(p.get("multiplier") or 0) > 0 for p in picks) != 11:
        raise PublicMatchError("MATCH_LOCKED_XI_NOT_11")
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


def _official_snapshot(root: Path, gw: int, entry: int, members: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    picks = (members["entries"][str(entry)]).get("picks") or []
    fixtures = _read(root / "data/v6/normalized/canonical_fixtures.json").get("fixtures") or []
    official = _read(root / "data/v6/current/official_fpl.json").get("official") or {}
    score_by_id = {
        int(row.get("id")): row for row in official.get("fixtures") or []
        if isinstance(row, dict) and row.get("id") is not None
    }
    matches = []
    for row in fixtures:
        if int(row.get("event") or 0) != gw:
            continue
        fixture = dict(row)
        fixture["id"] = row.get("official_fpl_fixture_id")
        raw = score_by_id.get(int(fixture["id"] or 0), {})
        for key in ("team_h_score", "team_a_score", "finished_provisional"):
            if key in raw:
                fixture[key] = raw[key]
        matches.append(fixture)
    return {
        "bootstrap": _bootstrap(root, gw),
        "phase": {"scoring_gw": gw},
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
            # Transfer hits are not present in V6 normalized submitted picks.
            # Never pass an invented zero as an authenticated or Official hit.
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


def _exposure(members: dict[str, Any], event: dict[str, Any], standings: dict[str, Any], entry: int, names: dict[int, str]) -> dict[str, Any]:
    score = {int(row["element_id"]): int(row.get("total_points") or 0) for row in event.get("elements") or []}
    counts: dict[int, dict[str, int]] = defaultdict(lambda: {"owned": 0, "starter": 0, "captain": 0, "vice": 0, "eo": 0})
    gross_by_entry: dict[int, int] = {}
    captain_by_entry: dict[int, str] = {}
    for key, record in (members.get("entries") or {}).items():
        eid = int(key)
        gross = 0
        for pick in record.get("picks") or []:
            player = int(pick["element_id"])
            multiplier = int(pick.get("multiplier") or 0)
            counts[player]["owned"] += 1
            counts[player]["starter"] += int(multiplier > 0)
            counts[player]["captain"] += int(pick.get("captain") is True)
            counts[player]["vice"] += int(pick.get("vice_captain") is True)
            counts[player]["eo"] += multiplier
            gross += score.get(player, 0) * multiplier
            if pick.get("captain") is True:
                captain_by_entry[eid] = names.get(player, str(player))
        gross_by_entry[eid] = gross
    n = len(members.get("entries") or {})
    def stat(value: int) -> dict[str, Any]:
        return {"numerator": value, "denominator": n, "percentage": round(value * 100 / n, 2)}
    rows = []
    own_ids = {int(p["element_id"]) for p in members["entries"][str(entry)]["picks"]}
    for player in sorted(own_ids):
        c = counts[player]
        rows.append({
            "player": names.get(player, str(player)),
            "denominator": n,
            **{field: stat(c[field]) for field in ("owned", "starter", "captain", "vice", "eo")},
            "live_consequence": f"{score.get(player, 0)} raw pts; EO {round(c['eo'] * 100 / n, 1)}%",
        })
    static = {int(row.get("entry_id")): row for row in standings.get("managers") or []}
    own_static = static.get(entry) or {}
    own_rank = int(own_static.get("league_rank") or 0)
    rival = []
    for eid, row in static.items():
        r = int(row.get("league_rank") or 0)
        if eid == entry or not (max(1, own_rank - 9) <= r <= own_rank + 5):
            continue
        rival.append({
            "rank": r,
            "manager": row.get("manager_name") or row.get("team_name"),
            "live_points": f"{gross_by_entry.get(eid, 0)} gross (hit/autosub pending)",
            "gap": "UNVERIFIED",
            "captain": captain_by_entry.get(eid, "UNAVAILABLE"),
            "key_threat": "Pending official score finalization",
            "key_shield": "UNVERIFIED",
        })
    rival.sort(key=lambda r: r["rank"])
    return {
        "status": "DEGRADED",
        "league_name": standings.get("league_name") or "ICON+ League",
        "expected_manager_count": n,
        "collected_manager_count": n,
        "submitted_picks_exposure": {"state": "COMPLETE", "expected_count": n, "available_count": n},
        "live_standings_rank": {"state": "UNAVAILABLE", "reason": "OFFICIAL_STATIC_STANDINGS_NOT_LIVE; HIT_AUTOSUB_UNVERIFIED"},
        "user_summary": {"rank": None, "live_points": None},
        "current_live_rank": None,
        "current_live_points": None,
        "material_player_exposure": rows,
        "competitive_rival_live_consequence": rival,
        "league_raw_gross_points": gross_by_entry,
        "rival_live_points": {"state": "PROVISIONAL_GROSS_ONLY"},
        "eo": {"state": "COMPLETE", "denominator": n, "definition": "sum of submitted scoring multipliers / managers"},
        "live_rank_not_fabricated": True,
        "own_static_rank": own_rank,
    }


def run(runtime_data_root: Path, report_slot: str, output_dir: Path) -> dict[str, Any]:
    gw, entry, pref, members, standings, event = _validated_inputs(runtime_data_root, report_slot)
    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_snapshot = _official_snapshot(runtime_data_root, gw, entry, members, event)
    input_file = output_dir / ".match-public-input.json"
    input_file.write_text(json.dumps(canonical_snapshot), encoding="utf-8")
    live_state_service.OFFICIAL = input_file
    live_state_service.OUT = output_dir / ".match-public-provisional.json"
    live_state_service.PREDICTION_LEDGER = output_dir / ".match-no-prediction.json"
    live = live_state_service.run()
    if live.get("submitted_picks_status") != "AVAILABLE" or len(live.get("players") or []) != 15:
        raise PublicMatchError("MATCH_SCORING_15_NOT_AVAILABLE")
    # No transfer-hit authority in normalized picks, so the published score is
    # strictly gross and provisional; never silently make it net by treating it as 0.
    live["hit"] = None
    live["net_points"] = None
    if isinstance(live.get("personalized_live_score"), dict):
        live["personalized_live_score"]["hit"] = None
        live["personalized_live_score"]["current_net_total"] = None
        live["personalized_live_score"]["hit_authority"] = "UNAVAILABLE"
    names = {
        int(p["element"]): str(p.get("name") or p["element"])
        for p in live.get("players") or []
    }
    icon = _exposure(members, event, standings, entry, names)
    report = materialize_match_report(
        canonical_text=CANONICAL.read_text(encoding="utf-8"),
        live_payload=live,
        icon_live=icon,
        source_freshness={
            "mini_league_submitted_picks": {"status": "AVAILABLE", "checked_at": members.get("generated_at")},
            "live_standings": {"status": "UNVERIFIED", "checked_at": standings.get("generated_at")},
            "match_evidence_feed": {"status": "OFFICIAL_FPL", "checked_at": event.get("checked_at")},
        },
    )
    body = render_match_text(report)
    ids = [row.get("section_id") for row in report.get("sections") or []]
    if ids != EXPECTED or body.count("## MATCH ") != 13 or validate_match_presentation_lock():
        raise PublicMatchError("MATCH_13_SECTION_RENDER_CONTRACT_FAILED")
    if "## MATCH 10" not in body or "58/58" not in body or "## MATCH 13" not in body:
        raise PublicMatchError("MATCH10_OR_MATCH13_REAL_CONTENT_MISSING")
    proof = {
        "schema_version": 2, "runner": "V12_PUBLIC_MATCH_DELIVERY",
        "report_mode": "MATCH", "report_slot": report_slot, "planning_gw": gw,
        "runner_status": "DEGRADED", "pre_render_qa_status": "PASS",
        "post_render_qa_status": "PASS", "human_facing_qa_status": "PASS",
        "canonical_expected_section_ids": EXPECTED, "rendered_section_ids": ids,
        "public_team_id": entry, "public_league_id": int(pref["priority_league_id"]),
        "manager_coverage": n if (n := len(members["entries"])) else 0,
        "public_auth_independent": True, "authenticated_finance_claimed": False,
        "live_checked_at": event.get("checked_at"), "prefetch_identity": pref.get("report_prefetch_run_id"),
        "unverified_scopes": ["HITS", "AUTOSUB", "PROVISIONAL_LIVE_RANK"],
        "stages": [{"stage": "MATCH_PUBLIC_FACTS", "status": "PASS"},
                   {"stage": "MATCH13_RENDER", "status": "PASS"},
                   {"stage": "LIVE_RANK", "status": "DEGRADED", "reason": "HITS_AUTOSUB_UNVERIFIED"}],
    }
    bundle = {
        "schema": "FPL_MASTER_V12_PUBLIC_MATCH_BUNDLE_V1",
        "report_mode": "MATCH", "report_slot": report_slot, "planning_gw": gw,
        "runner_status": "DEGRADED", "root_failure": "HITS_AUTOSUB_LIVE_RANK_UNVERIFIED",
        "section_manifest": [{"section_id": value, "status": "COMPLETE" if value != "MATCH10" else "DEGRADED"} for value in ids],
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
    return {"status": "READY_DEGRADED", "report_slot": report_slot, "sections": len(ids)}


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
