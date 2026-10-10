from __future__ import annotations

"""Public-first MATCH bridge for canonical V12 rendering.

Only Official V6 submitted picks and current-GW live points are authoritative.
This bridge never uses the private authenticated team or optimizer lineup.
Until net scoring/hits/autosubs are separately proven, rank remains unavailable.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.engines.v12_report_orchestration import materialize_match_report, render_match_text


class PublicMatchError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicMatchError(f"PUBLIC_FACT_MISSING_OR_INVALID:{path.name}") from exc
    if not isinstance(value, dict):
        raise PublicMatchError(f"PUBLIC_FACT_SCHEMA_INVALID:{path.name}")
    return value


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build_public_match(
    *,
    runtime_data_root: Path,
    report_slot: str,
    canonical_text: str,
) -> dict[str, Any]:
    root = runtime_data_root / "data" / "v6"
    # Exact occurrence file is authority. A later DEEP/PRICE run may overwrite
    # the convenience latest pointer before MATCH is dispatched.
    slot_token = (
        report_slot.replace(":", "").replace("+", "_plus_")
        .replace("-", "").replace("T", "_")
    )
    pf = _load(root / "report_prefetch" / "occurrences" / f"match_mode__{slot_token}.json")
    # Never promote a prior or future scope into an exact MATCH occurrence.
    if (
        pf.get("report_kind") != "match_mode"
        or pf.get("target_logical_report_slot") != report_slot
        or pf.get("public_core_complete") is not True
        or pf.get("mini_league_status") != "AVAILABLE"
        or pf.get("live_status") != "AVAILABLE"
    ):
        raise PublicMatchError("MATCH_PREFETCH_EXACT_PUBLIC_SCOPE_NOT_READY")
    gw = _as_int(pf.get("gw"))
    entry_id = _as_int(pf.get("entry_id"))
    league_id = _as_int(pf.get("priority_league_id"))
    if min(gw, entry_id, league_id) <= 0:
        raise PublicMatchError("MATCH_IDENTITY_GW_UNAVAILABLE")
    base = root / "mini_leagues" / str(league_id)
    submitted = _load(base / f"gw_{gw}_manager_picks.json")
    live = _load(base / "live_state.json")
    standings = _load(base / "standings.json")
    players_doc = _load(root / "normalized" / "canonical_players.json")
    fixtures_doc = _load(root / "normalized" / "canonical_fixtures.json")
    teams_doc = _load(root / "normalized" / "canonical_teams.json")
    managers = list(standings.get("managers") or [])
    entries = dict(submitted.get("entries") or {})
    denominator = _as_int(pf.get("expected_manager_count"))
    if (
        live.get("gw") != gw
        or submitted.get("gw") != gw
        or submitted.get("complete") is not True
        or standings.get("complete") is not True
        or denominator != 58
        or len(managers) != denominator
        or len(entries) != denominator
        or submitted.get("submitted_picks_missing_count") != 0
        or live.get("status") != "AVAILABLE"
    ):
        raise PublicMatchError("MATCH_PUBLIC_COVERAGE_INCOMPLETE")
    own = dict(entries.get(str(entry_id)) or {})
    picks = [dict(row) for row in own.get("picks") or []]
    ids = [_as_int(row.get("element_id")) for row in picks]
    if (
        own.get("status") != "AVAILABLE"
        or len(picks) != 15
        or len(set(ids)) != 15
        or sum(_as_int(row.get("multiplier")) > 0 for row in picks) != 11
        or sum(_as_int(row.get("multiplier")) == 0 for row in picks) != 4
        or sum(row.get("captain") is True for row in picks) != 1
        or sum(row.get("vice_captain") is True for row in picks) != 1
    ):
        raise PublicMatchError("MATCH_LOCKED_XI_INCOMPLETE")
    player_map = {
        _as_int(row.get("official_fpl_element_id")): row
        for row in players_doc.get("players") or []
    }
    points_map = {
        _as_int(row.get("element_id")): row
        for row in live.get("elements") or []
    }
    teams = {
        _as_int(row.get("official_fpl_team_id")): row
        for row in teams_doc.get("teams") or []
    }
    fixtures = [
        row for row in fixtures_doc.get("fixtures") or []
        if _as_int(row.get("event")) == gw
    ]

    def fixture_status(team_id: int) -> str:
        rows = [
            row for row in fixtures
            if team_id in {_as_int(row.get("team_h")), _as_int(row.get("team_a"))}
        ]
        if any(row.get("started") is True and row.get("finished") is not True for row in rows):
            return "LIVE"
        if rows and all(row.get("finished") is True for row in rows):
            return "FT"
        return "NOT_STARTED"

    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    detail = []
    missing_names = []
    for pick in sorted(picks, key=lambda row: _as_int(row.get("squad_position"))):
        eid = _as_int(pick.get("element_id"))
        official = player_map.get(eid) or {}
        raw = points_map.get(eid)
        if raw is None:
            raise PublicMatchError("MATCH_LIVE_ELEMENT_MISSING")
        name = official.get("web_name")
        if not name:
            missing_names.append(eid)
            name = f"Player {eid}"
        mult = _as_int(pick.get("multiplier"))
        team_id = _as_int(official.get("team_id"))
        detail.append({
            "element": eid,
            "name": name,
            "team": (teams.get(team_id) or {}).get("name"),
            "team_id": team_id,
            "position": positions.get(_as_int(official.get("element_type")), "UNKNOWN"),
            "pick_position": _as_int(pick.get("squad_position")),
            "multiplier": mult,
            "captain": pick.get("captain") is True,
            "vice_captain": pick.get("vice_captain") is True,
            "minutes": _as_int(raw.get("minutes")),
            "total_points": _as_int(raw.get("total_points")),
            "effective_points": mult * _as_int(raw.get("total_points")),
            "bonus": _as_int(raw.get("bonus")),
            "bps": _as_int(raw.get("bps")),
            "fixture_status": fixture_status(team_id),
        })
    xi = [row for row in detail if row["multiplier"] > 0]
    bench = [row for row in detail if row["multiplier"] == 0]
    captain = next(row for row in detail if row["captain"])
    vice = next(row for row in detail if row["vice_captain"])
    started = sum(row.get("started") is True for row in fixtures)
    finished = sum(row.get("finished") is True for row in fixtures)
    life = {
        "primary_mode": "POST_ALL_MATCH" if fixtures and finished == len(fixtures)
        else "MATCH" if started else "PRE_DEADLINE",
        "transition": "OFFICIAL_FPL_SNAPSHOT",
        "fixtures_live": sum(row.get("started") is True and row.get("finished") is not True for row in fixtures),
        "fixtures_ft": finished,
        "fixtures_not_started": len(fixtures) - started,
    }
    gross = sum(row["effective_points"] for row in detail)
    exposure = []
    for eid in sorted(set(ids)):
        collected = []
        for entry in entries.values():
            collected.extend(
                [dict(p) for p in entry.get("picks") or [] if _as_int(p.get("element_id")) == eid]
            )
        exposure.append({
            "player": (player_map.get(eid) or {}).get("web_name") or f"Player {eid}",
            "owned": len(collected),
            "starter": sum(_as_int(row.get("multiplier")) > 0 for row in collected),
            "captain": sum(row.get("captain") is True for row in collected),
            "vice": sum(row.get("vice_captain") is True for row in collected),
            "eo": sum(_as_int(row.get("multiplier")) for row in collected),
            "denominator": denominator,
            "live_consequence": f"{_as_int((points_map.get(eid) or {}).get('total_points'))} raw points",
        })
    as_of = str(live.get("checked_at") or live.get("generated_at") or "")
    live_payload = {
        "generated_at": as_of,
        "scoring_gw": gw,
        "submitted_picks_status": "AVAILABLE",
        "event_live_status": "AVAILABLE",
        "players": detail,
        "lifecycle": life,
        "match_checkpoint": {**life, "generated_at": as_of},
        "bench_presentation": {
            "bench_gk": next((row for row in bench if row["position"] == "GK"), None),
            "outfield_autosub_priority": [
                row for row in bench if row["position"] != "GK"
            ],
        },
        "personalized_live_score": {
            "current_effective_total": gross,
            "current_net_total": None,
            "net_status": "UNAVAILABLE_UNTIL_TRANSFER_HITS_AND_AUTOSUB_VERIFIED",
            "provisional_bonus_total": sum(row["bonus"] for row in detail),
            "autosub_implications": {"status": "PROVISIONAL", "potential_out": [], "bench_candidates": []},
        },
        "captain_vice_consequence": {
            "captain": captain, "vice": vice,
            "vice_takeover_state": "PENDING_OFFICIAL_FINALIZATION",
            "final_consequence": "PENDING_OFFICIAL_FINALIZATION",
        },
        "bonus_bps": {"status": "PROVISIONAL", "provisional": True},
        "prediction_snapshot": {"status": "UNAVAILABLE"},
    }
    icon = {
        "status": "DEGRADED",
        "league_name": standings.get("league_name"),
        "expected_manager_count": denominator,
        "collected_manager_count": denominator,
        "submitted_picks_exposure": {
            "state": "AVAILABLE", "expected_count": denominator, "available_count": denominator
        },
        "live_standings_rank": {"state": "UNAVAILABLE_NEEDS_NET_SCORING_VERIFICATION"},
        "material_player_exposure": exposure,
        "user_summary": {"live_points": gross},
        "rank_note": "Provisional live rank withheld until hits, autosubs and tie-breaks are validated",
    }
    source_freshness = {
        "mini_league_submitted_picks": {"status": "AVAILABLE", "as_of": submitted.get("generated_at")},
        "live_standings": {"status": "DEGRADED", "as_of": standings.get("generated_at")},
        "match_evidence_feed": {"status": "UNAVAILABLE"},
        "event_live": {"status": "AVAILABLE", "as_of": as_of},
        "submitted_picks": {"status": "AVAILABLE", "as_of": own.get("checked_at")},
    }
    report = materialize_match_report(
        canonical_text=canonical_text,
        live_payload=live_payload,
        icon_live=icon,
        source_freshness=source_freshness,
        next_critical_observation="next Official FPL live refresh",
        next_critical_reason="confirm live scoring, bonus and autosubs",
        next_reassess_at=as_of,
    )
    body = render_match_text(report)
    if len(report.get("sections") or []) != 13 or body.count("## MATCH ") != 13:
        raise PublicMatchError("MATCH_13_SECTION_CONTRACT_FAILED")
    return {
        "schema": "FPL_MASTER_V12_INTEGRATED_REPORT_BUNDLE_V2",
        "report_mode": "MATCH", "report_slot": report_slot,
        "planning_gw": gw, "runner_status": "DEGRADED",
        "root_failure": "LIVE_RANK_NET_SCORING_UNVERIFIED",
        "report": report,
        "section_manifest": [
            {"section_id": row.get("section_id"), "status": row.get("state")}
            for row in report.get("sections") or []
        ],
        "visible_body": body,
        "execution_proof": {
            "runner": "V12_PUBLIC_MATCH_BRIDGE",
            "report_mode": "MATCH", "report_slot": report_slot,
            "planning_gw": gw, "runner_status": "DEGRADED",
            "canonical_catalog_complete": True,
            "rendered_section_ids": [f"MATCH{i}" for i in range(1, 14)],
            "report_prefetch_binding": {
                "report_prefetch_run_id": pf.get("report_prefetch_run_id"),
                "target_logical_report_slot": report_slot,
                "same_occurrence_bound": True,
            },
            "source_evidence": {
                "submitted_coverage": len(entries),
                "expected_managers": denominator,
                "live_checked_at": as_of,
                "missing_player_names": missing_names,
                "net_scoring_verified": False,
                "auth_required": False,
            },
            "no_second_model_authority": True,
            "no_private_finance_inferred": True,
        },
    }
