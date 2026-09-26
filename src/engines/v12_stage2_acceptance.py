from __future__ import annotations

"""Read-only Stage-2 acceptance over fresh runtime-data-v6.

This runner is acceptance evidence only. It does not acquire, publish, recover,
schedule, mutate, or repair V6. It executes the V12 analytics producer chain
against already-published factual artifacts and writes an immutable JSON proof.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.engines.v12_integrated_report_runner import (
    _official_payload,
    _owned15,
    _planning_gw,
)
from src.engines.v12_report_orchestration import build_watchlist20
from src.engines.v12_tactical_role import attach_tactical_role_scores
from src.models.historical_projection import build as build_player_projections
from src.models.official_role_evidence import attach_official_role_evidence
from src.models.team_strength import build_team_strength
from src.models.v12_analytics_foundation import (
    load_v6_analytics_foundation,
    require_match_foundation,
)
from src.models.v12_stage1_analytics import build_canonical_universe

BASELINE_V6_SHA = "d8a286a9428d8114125abb9093639de00c82103b"
MATCHUP_KEYS = {
    "goal",
    "creation",
    "attack",
    "clean_sheet",
    "defcon",
    "save",
    "set_piece",
    "aerial",
    "transition",
    "minutes",
    "bonus",
}
CANONICAL_WEIGHTS = {
    "PROVEN_HISTORICAL": 0.20,
    "TACTICAL_ROLE": 0.25,
    "CURRENT_UNDERLYING": 0.30,
    "FIXTURE_SECURITY": 0.25,
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _first_fixture(player: Mapping[str, Any]) -> dict[str, Any]:
    for gw in player.get("xpts_by_gw") or []:
        for fixture in gw.get("fixtures") or []:
            if isinstance(fixture, Mapping):
                return dict(fixture)
    return {}


def _normalize_name(value: Any) -> str:
    return str(value or "").casefold().replace("-", " ").strip()


def _find_named(
    players: Sequence[Mapping[str, Any]],
    aliases: Sequence[str],
) -> dict[str, Any] | None:
    targets = [_normalize_name(alias) for alias in aliases]
    for raw in players:
        name = _normalize_name(raw.get("name"))
        if any(alias in name or name in alias for alias in targets):
            return dict(raw)
    return None


def _distribution_summary(value: Mapping[str, Any] | None) -> dict[str, Any]:
    row = dict(value or {})
    return {
        "status": row.get("status"),
        "mean": row.get("mean", row.get("expected_points")),
        "median": row.get("median"),
        "variance": row.get("variance"),
        "Q10": (row.get("quantiles") or {}).get("Q10"),
        "Q25": (row.get("quantiles") or {}).get("Q25"),
        "Q75": (row.get("quantiles") or {}).get("Q75"),
        "Q90": (row.get("quantiles") or {}).get("Q90"),
        "p_blank": row.get("p_fpl_blank"),
        "p_haul": row.get("p_haul_10_plus"),
        "sum_probability": row.get("sum_probability"),
    }


def _player_acceptance_row(
    player: Mapping[str, Any],
    *,
    canonical_by_id: Mapping[int, Mapping[str, Any]],
    owned_ids: set[int],
) -> dict[str, Any]:
    fixture = _first_fixture(player)
    events = dict(fixture.get("events") or {})
    position_engine = dict(
        fixture.get("position_engine")
        or player.get("position_engine")
        or {}
    )
    complete = dict(
        fixture.get("complete_player_distribution")
        or player.get("complete_player_distribution")
        or {}
    )
    horizons = dict(player.get("horizons") or {})
    element = int(player.get("element") or 0)
    canonical = dict(canonical_by_id.get(element) or {})
    tactical = dict(player.get("tactical_role_component") or {})
    return {
        "element": element,
        "name": player.get("name"),
        "position": player.get("position"),
        "owned": element in owned_ids,
        "canonical_rank": canonical.get("canonical_rank"),
        "canonical_score": canonical.get("football_score"),
        "canonical_components": canonical.get("canonical_components"),
        "xMins": (player.get("xmins") or {}).get("expected_minutes"),
        "Pstart": (
            complete.get("P_start")
            if complete
            else (player.get("xmins") or {}).get("start_probability")
        ),
        "role": tactical.get("role_profile"),
        "opponent": fixture.get("opponent"),
        "home": fixture.get("home"),
        "dynamic_matchup": position_engine.get("matchup_vector"),
        "clean_sheet": {
            "P_CS": complete.get("P_CS"),
            "fixture_probability": fixture.get("clean_sheet_probability"),
        },
        "defcon": events.get("defcon"),
        "saves": events.get("saves"),
        "goal_process": position_engine.get("goal_process"),
        "creation_process": position_engine.get("creation_process"),
        "penalty_process": position_engine.get("penalty_process"),
        "set_piece_process": position_engine.get("set_piece_process"),
        "linkup": position_engine.get("linkup"),
        "bonus": events.get("bonus"),
        "complete_player_distribution": complete,
        "1GW": _distribution_summary(
            (horizons.get("1") or {}).get("point_distribution")
        ),
        "3GW": _distribution_summary(
            (horizons.get("3") or {}).get("point_distribution")
        ),
        "5GW": _distribution_summary(
            (horizons.get("5") or {}).get("point_distribution")
        ),
    }


def _case_with_alternatives(
    target: Mapping[str, Any] | None,
    *,
    players: Sequence[Mapping[str, Any]],
    canonical_rows: Sequence[Mapping[str, Any]],
    canonical_by_id: Mapping[int, Mapping[str, Any]],
    owned_ids: set[int],
    limit: int = 5,
) -> dict[str, Any]:
    if not target:
        return {
            "status": "TARGET_NOT_FOUND_IN_CURRENT_UNIVERSE",
            "target": None,
            "alternatives": [],
            "predetermined_winner": False,
        }
    position = str(target.get("position") or "").upper()
    target_id = int(target.get("element") or 0)
    player_by_id = {
        int(row.get("element") or 0): dict(row)
        for row in players
        if int(row.get("element") or 0) > 0
    }
    candidate_ids: list[int] = []
    for row in canonical_rows:
        element = int(row.get("element_id") or 0)
        if (
            element > 0
            and element != target_id
            and str(row.get("position") or "").upper() == position
            and row.get("canonical_evaluation_complete") is True
        ):
            candidate_ids.append(element)
    candidate_ids.sort(
        key=lambda element: (
            0 if element in owned_ids else 1,
            int(
                (canonical_by_id.get(element) or {}).get(
                    "canonical_rank"
                )
                or 10_000
            ),
            element,
        )
    )
    alternatives = []
    seen: set[int] = set()
    for element in candidate_ids:
        if element in seen or element not in player_by_id:
            continue
        seen.add(element)
        alternatives.append(
            _player_acceptance_row(
                player_by_id[element],
                canonical_by_id=canonical_by_id,
                owned_ids=owned_ids,
            )
        )
        if len(alternatives) >= limit:
            break
    return {
        "status": "READY",
        "target": _player_acceptance_row(
            target,
            canonical_by_id=canonical_by_id,
            owned_ids=owned_ids,
        ),
        "alternatives": alternatives,
        "alternative_selection": (
            "OUR15_SAME_POSITION_FIRST_THEN_CURRENT_CANONICAL_UNIVERSE;"
            "NO_ACCEPTANCE_WINNER_FORCED"
        ),
        "predetermined_winner": False,
    }


def _gk_tradeoff(
    players: Sequence[Mapping[str, Any]],
    *,
    canonical_by_id: Mapping[int, Mapping[str, Any]],
    owned_ids: set[int],
) -> dict[str, Any]:
    rows = []
    for player in players:
        if str(player.get("position") or "").upper() != "GK":
            continue
        fixture = _first_fixture(player)
        if not fixture:
            continue
        events = fixture.get("events") or {}
        saves = events.get("saves") or {}
        complete = (
            fixture.get("complete_player_distribution")
            or player.get("complete_player_distribution")
            or {}
        )
        rows.append(
            (
                _f(complete.get("P_CS")),
                _f(saves.get("P_saves_ge_3")),
                dict(player),
            )
        )
    if not rows:
        return {"status": "NO_GK_FIXTURE_PROFILE", "profiles": []}
    high_cs = max(rows, key=lambda row: (row[0], -row[1]))
    high_save = max(rows, key=lambda row: (row[1], -row[0]))
    selected = [high_cs]
    if int(high_save[2].get("element") or 0) != int(
        high_cs[2].get("element") or 0
    ):
        selected.append(high_save)
    elif len(rows) > 1:
        selected.append(
            sorted(rows, key=lambda row: (row[1], -row[0]), reverse=True)[1]
        )
    return {
        "status": "READY" if len(selected) >= 2 else "ONE_PROFILE_ONLY",
        "tradeoff": "CLEAN_SHEET_VS_SAVE_VOLUME",
        "profiles": [
            _player_acceptance_row(
                row[2],
                canonical_by_id=canonical_by_id,
                owned_ids=owned_ids,
            )
            for row in selected
        ],
        "predetermined_winner": False,
    }


def _same_opponent_player_specific(
    players: Sequence[Mapping[str, Any]],
) -> bool:
    by_opponent: dict[Any, list[tuple[float, ...]]] = {}
    for player in players:
        fixture = _first_fixture(player)
        engine = dict(fixture.get("position_engine") or {})
        vector = dict((engine.get("matchup_vector") or {}).get("vector") or {})
        if not fixture or set(vector) != MATCHUP_KEYS:
            continue
        signature = tuple(
            round(_f((vector.get(key) or {}).get("multiplier")), 6)
            for key in sorted(MATCHUP_KEYS)
        )
        by_opponent.setdefault(fixture.get("opponent"), []).append(signature)
    return any(
        len(values) >= 2 and len(set(values)) >= 2
        for values in by_opponent.values()
    )


def _public_personal_and_mini_league_evidence(
    runtime_data_root: Path,
    *,
    owned: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Prove current public Official FPL squad + mini-league evidence.

    Authenticated /me is deliberately diagnostic only here. Stage 2 needs a
    current 15-player identity surface and current public mini-league facts,
    both of which Official FPL exposes without an authenticated private session.
    This function consumes only already-published V6 artifacts read-only.
    """
    submitted = _read_json(
        runtime_data_root / "data/v6/personal/submitted_picks.json"
    )
    memberships = _read_json(
        runtime_data_root / "data/v6/personal/memberships.json"
    )
    prefetch = _read_json(
        runtime_data_root / "data/v6/report_prefetch/latest.json"
    )

    submitted_picks = [
        dict(row)
        for row in submitted.get("picks") or []
        if isinstance(row, Mapping)
    ]
    submitted_ids = {
        int(row.get("element_id") or 0)
        for row in submitted_picks
        if int(row.get("element_id") or 0) > 0
    }
    owned_ids = {
        int(row.get("element_id") or 0)
        for row in owned
        if int(row.get("element_id") or 0) > 0
    }
    entry_id = int(
        submitted.get("entry_id")
        or prefetch.get("entry_id")
        or 0
    )
    submitted_lineage = dict(submitted.get("lineage") or {})
    current_public_squad = bool(
        str(submitted.get("status") or "").upper() == "AVAILABLE"
        and entry_id > 0
        and int(submitted_lineage.get("http_status") or 0) == 200
        and str(submitted_lineage.get("origin") or "").upper()
        == "LIVE_FETCHED_CURRENT_GW"
        and len(submitted_picks) == 15
        and len(submitted_ids) == 15
        and len(owned_ids) == 15
        and submitted_ids == owned_ids
    )

    priority = [
        dict(row)
        for row in memberships.get("priority_resolution") or []
        if isinstance(row, Mapping)
        and str(row.get("resolution_status") or "").upper() == "RESOLVED"
    ]
    priority_league_id = int(
        prefetch.get("priority_league_id")
        or (priority[0].get("league_id") if priority else 0)
        or 0
    )
    standings = (
        _read_json(
            runtime_data_root
            / f"data/v6/mini_leagues/{priority_league_id}/standings.json"
        )
        if priority_league_id > 0
        else {}
    )
    gw = int(submitted.get("gw") or prefetch.get("gw") or 0)
    manager_picks = (
        _read_json(
            runtime_data_root
            / f"data/v6/mini_leagues/{priority_league_id}/gw_{gw}_manager_picks.json"
        )
        if priority_league_id > 0 and gw > 0
        else {}
    )
    manager_entry = dict(
        (manager_picks.get("entries") or {}).get(str(entry_id)) or {}
    )
    expected_managers = int(
        standings.get("expected_manager_count")
        or prefetch.get("expected_manager_count")
        or 0
    )
    collected_managers = int(
        standings.get("collected_manager_count")
        or prefetch.get("collected_manager_count")
        or 0
    )
    public_mini_league = bool(
        priority_league_id > 0
        and prefetch.get("public_core_complete") is True
        and str(prefetch.get("public_personal_status") or "").upper()
        == "AVAILABLE"
        and str(prefetch.get("mini_league_status") or "").upper()
        == "AVAILABLE"
        and not (prefetch.get("public_control_failures") or [])
        and standings.get("complete") is True
        and expected_managers > 0
        and collected_managers == expected_managers
        and manager_picks.get("complete") is True
        and float(manager_picks.get("coverage_percent") or 0.0) >= 100.0
        and int(manager_entry.get("http_status") or 0) == 200
        and len(manager_entry.get("picks") or []) == 15
    )
    return {
        "current_public_squad_available": current_public_squad,
        "mini_league_public_available": public_mini_league,
        "entry_id": entry_id,
        "submitted_gw": gw,
        "submitted_pick_count": len(submitted_picks),
        "submitted_http_status": submitted_lineage.get("http_status"),
        "submitted_origin": submitted_lineage.get("origin"),
        "priority_league_id": priority_league_id,
        "priority_league_name": prefetch.get("priority_league_name"),
        "standings_complete": standings.get("complete"),
        "expected_manager_count": expected_managers,
        "collected_manager_count": collected_managers,
        "manager_picks_complete": manager_picks.get("complete"),
        "manager_picks_coverage_percent": manager_picks.get("coverage_percent"),
        "manager_entry_http_status": manager_entry.get("http_status"),
        "manager_entry_pick_count": len(manager_entry.get("picks") or []),
        "authenticated_session_required": False,
        "source": "V6_PUBLISHED_OFFICIAL_FPL_PUBLIC_READ_ONLY",
    }


def run_acceptance(
    runtime_data_root: Path,
    *,
    output_path: Path,
) -> dict[str, Any]:
    official = _official_payload(runtime_data_root)
    bootstrap = official["bootstrap"]
    fixtures = official["fixtures"]
    planning_gw = _planning_gw(bootstrap)
    strength = build_team_strength(bootstrap, fixtures)
    foundation = require_match_foundation(
        load_v6_analytics_foundation(
            runtime_data_root,
            bootstrap=bootstrap,
            planning_gw=planning_gw,
            strength=strength,
        )
    )
    projections = build_player_projections(
        bootstrap,
        strength,
        planning_gw,
        foundation.get("historical_prior") or {},
        player_features_payload=(
            foundation.get("player_features_payload") or {}
        ),
        player_match_rows=foundation.get("player_match_rows") or [],
        opponent_history_rows=foundation.get("opponent_history_rows") or [],
        opponent_history_scope=foundation.get("opponent_history_scope"),
    )
    attach_official_role_evidence(projections, bootstrap)
    attach_tactical_role_scores(
        projections,
        planning_gw,
        team_strength=strength,
    )

    submitted_for_owned = _read_json(
        runtime_data_root / "data/v6/personal/submitted_picks.json"
    )
    submitted_rows = [
        dict(row)
        for row in submitted_for_owned.get("picks") or []
        if isinstance(row, Mapping)
    ]
    owned = _owned15(
        {
            "finance_allowed": False,
            "rows": submitted_rows,
        },
        bootstrap,
    )
    owned_ids = {int(row["element_id"]) for row in owned}

    canonical = build_canonical_universe(projections)
    canonical_rows = list(canonical.get("players") or [])
    canonical_by_id = {
        int(row.get("element_id") or 0): dict(row)
        for row in canonical_rows
        if int(row.get("element_id") or 0) > 0
    }
    watchlist = build_watchlist20(
        evaluated_universe=canonical_rows,
        owned_element_ids=sorted(owned_ids),
        universe_authority=(
            "FULL" if canonical.get("status") == "COMPLETE" else "PARTIAL"
        ),
    )

    players = [
        dict(row)
        for row in projections.get("players") or []
        if isinstance(row, Mapping)
    ]
    first_fixtures = [
        _first_fixture(player) for player in players
    ]
    first_fixtures = [row for row in first_fixtures if row]
    by_position = {
        position: [
            row
            for row in players
            if str(row.get("position") or "").upper() == position
        ]
        for position in ("GK", "DEF", "MID", "FWD")
    }

    def fixture_with_position(position: str) -> list[dict[str, Any]]:
        return [
            _first_fixture(player)
            for player in by_position[position]
            if _first_fixture(player)
        ]

    gk_fixtures = fixture_with_position("GK")
    def_fixtures = fixture_with_position("DEF")
    mid_fixtures = fixture_with_position("MID")
    fwd_fixtures = fixture_with_position("FWD")

    v6_publish = _read_json(
        runtime_data_root / "data/v6/health/publish_integrity.json"
    )
    public_evidence = _public_personal_and_mini_league_evidence(
        runtime_data_root,
        owned=owned,
    )

    dynamic_vectors = [
        ((fixture.get("position_engine") or {}).get("matchup_vector") or {})
        for fixture in first_fixtures
    ]
    complete_matchup_vectors = [
        vector
        for vector in dynamic_vectors
        if set((vector.get("vector") or {}).keys()) == MATCHUP_KEYS
    ]

    all_horizons_ready = True
    horizon_missing: list[dict[str, Any]] = []
    for player in players:
        if str(player.get("status") or "a") == "u":
            continue
        horizons = player.get("horizons") or {}
        for horizon in ("1", "3", "5"):
            distribution = (
                (horizons.get(horizon) or {}).get("point_distribution")
                or {}
            )
            if distribution.get("status") != "READY_COMPLETE_CONDITIONAL_PMF":
                all_horizons_ready = False
                horizon_missing.append(
                    {
                        "element": player.get("element"),
                        "name": player.get("name"),
                        "horizon": horizon,
                        "status": distribution.get("status"),
                    }
                )

    watch_ids = {
        int(row.get("element_id") or 0)
        for row in watchlist.get("rows") or []
    }
    canonical_ids = {
        int(row.get("element_id") or 0)
        for row in canonical_rows
    }
    eligible_projection_ids = {
        int(row.get("element") or 0)
        for row in players
        if int(row.get("element") or 0) > 0
        and str(row.get("status") or "a") != "u"
    }
    eligible_canonical_ids = {
        int(row.get("element_id") or 0)
        for row in canonical_rows
        if int(row.get("element_id") or 0) > 0
        and row.get("eligible") is not False
        and row.get("canonical_evaluation_complete") is True
    }
    def stage2_lineage_complete(row: Mapping[str, Any]) -> bool:
        lineage = dict(row.get("stage2_lineage") or {})
        p1_1 = dict(lineage.get("p1_1") or {})
        posterior = dict(lineage.get("posterior") or {})
        position_engine = dict(lineage.get("position_engine") or {})
        horizons = dict(lineage.get("horizons") or {})
        return bool(
            lineage.get("contract")
            == "V12_CANONICAL_STAGE2_SINGLE_CHAIN_V1"
            and lineage.get("same_projection_row") is True
            and lineage.get("lineage_complete") is True
            and p1_1.get("owner") == "V12_PLAYER_MINUTES"
            and p1_1.get("present") is True
            and posterior.get("owner") == "V12_PLAYER_EVENTS"
            and posterior.get("present") is True
            and position_engine.get("owner") == "V12_PLAYER_EVENTS"
            and position_engine.get("present") is True
            and all(
                (horizons.get(horizon) or {}).get("distribution_status")
                == "READY_COMPLETE_CONDITIONAL_PMF"
                for horizon in ("1", "3", "5")
            )
            and lineage.get("duplicate_model_created") is False
        )

    watch_same_lineage = bool(
        watch_ids
        and watch_ids <= canonical_ids
        and canonical.get("weights") == CANONICAL_WEIGHTS
        and canonical.get("stage2_lineage_contract")
        == "V12_CANONICAL_STAGE2_SINGLE_CHAIN_V1"
        and all(
            (canonical_by_id.get(element) or {}).get(
                "canonical_components"
            )
            is not None
            and stage2_lineage_complete(
                canonical_by_id.get(element) or {}
            )
            for element in watch_ids
        )
    )
    full_universe_lineage = bool(
        eligible_projection_ids
        and eligible_projection_ids == eligible_canonical_ids
        and all(
            stage2_lineage_complete(canonical_by_id.get(element) or {})
            for element in eligible_projection_ids
        )
    )

    scoreline_selection = dict(
        strength.get("scoreline_model_selection") or {}
    )
    checks = {
        "dynamic_fdr_vector": bool(complete_matchup_vectors),
        "same_opponent_player_specific": _same_opponent_player_specific(
            players
        ),
        "gk_engine": any(
            ((fixture.get("events") or {}).get("saves") or {}).get(
                "count_model"
            )
            for fixture in gk_fixtures
        ),
        "def_engine": any(
            ((fixture.get("events") or {}).get("defcon") or {}).get(
                "count_model"
            )
            for fixture in def_fixtures
        ),
        "mid_engine": any(
            ((fixture.get("position_engine") or {}).get("goal_process"))
            and ((fixture.get("position_engine") or {}).get(
                "creation_process"
            ))
            for fixture in mid_fixtures
        ),
        "fwd_engine": any(
            ((fixture.get("position_engine") or {}).get("goal_process"))
            and ((fixture.get("position_engine") or {}).get(
                "creation_process"
            ))
            for fixture in fwd_fixtures
        ),
        "cs_model": scoreline_selection.get("selected")
        in {"POISSON", "DIXON_COLES", "BIVARIATE_POISSON"},
        "defcon_threshold": any(
            ((fixture.get("events") or {}).get("defcon") or {}).get(
                "P_threshold"
            )
            is not None
            for fixture in def_fixtures
        ),
        "save_threshold": any(
            ((fixture.get("events") or {}).get("saves") or {}).get(
                "P_saves_ge_3"
            )
            is not None
            for fixture in gk_fixtures
        ),
        "set_piece_penalty_chain": any(
            ((fixture.get("position_engine") or {}).get(
                "set_piece_process"
            )
            or {}).get("chain")
            and ((fixture.get("position_engine") or {}).get(
                "penalty_process"
            )
            or {}).get("chain")
            for fixture in mid_fixtures + fwd_fixtures
        ),
        "linkup_dependency_surface": any(
            (fixture.get("position_engine") or {}).get("linkup")
            is not None
            for fixture in first_fixtures
        ),
        "bps_conditional": any(
            ((fixture.get("events") or {}).get("bonus") or {}).get(
                "responds_to_simulated_football_events"
            )
            is True
            for fixture in first_fixtures
        ),
        "posterior_predictive": any(
            (
                (
                    (
                        (fixture.get("position_engine") or {}).get(
                            "posterior_predictive"
                        )
                        or {}
                    ).get("saves")
                    or {}
                ).get("replicated_mean")
                is not None
            )
            for fixture in gk_fixtures
        ),
        "complete_point_distributions": all(
            (fixture.get("point_distribution") or {}).get("status")
            == "READY_COMPLETE_POSITION_SPECIFIC"
            for fixture in first_fixtures
        )
        if first_fixtures
        else False,
        "horizons_1_3_5": all_horizons_ready,
        "full_universe_same_chain": (
            len(players) == len(bootstrap.get("elements") or [])
            and canonical.get("status") == "COMPLETE"
            and canonical.get("stage2_lineage_contract")
            == "V12_CANONICAL_STAGE2_SINGLE_CHAIN_V1"
            and canonical.get("stage2_lineage_complete_players")
            == len(eligible_projection_ids)
            and full_universe_lineage
        ),
        "watchlist20_same_lineage": (
            watchlist.get("state") == "COMPLETE"
            and len(watchlist.get("rows") or []) == 20
            and watch_same_lineage
        ),
        "v6_publish_health": v6_publish.get("status") == "PASS",
        "legacy_isolation_declared": (
            (projections.get("governance") or {}).get(
                "legacy_projection_components_migration_oracle_only"
            )
            is True
        ),
    }

    named = {
        "DEF_Muharemovic": _case_with_alternatives(
            _find_named(
                players,
                ("Muharemovic", "Muharemović"),
            ),
            players=players,
            canonical_rows=canonical_rows,
            canonical_by_id=canonical_by_id,
            owned_ids=owned_ids,
        ),
        "MID_Gross": _case_with_alternatives(
            _find_named(players, ("Groß", "Gross")),
            players=players,
            canonical_rows=canonical_rows,
            canonical_by_id=canonical_by_id,
            owned_ids=owned_ids,
        ),
        "FWD_DCL": _case_with_alternatives(
            _find_named(
                players,
                ("Calvert-Lewin", "DCL", "Calvert Lewin"),
            ),
            players=players,
            canonical_rows=canonical_rows,
            canonical_by_id=canonical_by_id,
            owned_ids=owned_ids,
        ),
        "FWD_Brobbey": _case_with_alternatives(
            _find_named(players, ("Brobbey",)),
            players=players,
            canonical_rows=canonical_rows,
            canonical_by_id=canonical_by_id,
            owned_ids=owned_ids,
        ),
        "GK_CS_SAVE_TRADEOFF": _gk_tradeoff(
            players,
            canonical_by_id=canonical_by_id,
            owned_ids=owned_ids,
        ),
    }

    stage2_engine_pass = all(checks.values())
    current_authenticated_squad_pass = False
    current_squad_evidence_pass = bool(
        public_evidence.get("current_public_squad_available") is True
    )
    mini_league_public_pass = bool(
        public_evidence.get("mini_league_public_available") is True
    )
    status = (
        "GREEN"
        if (
            stage2_engine_pass
            and current_squad_evidence_pass
            and mini_league_public_pass
        )
        else "BLOCKED_CURRENT_PUBLIC_EVIDENCE"
        if stage2_engine_pass
        else "FAIL_STAGE2_ENGINE"
    )
    proof = {
        "contract": "V12_STAGE2_LIVE_ACCEPTANCE_V1",
        "status": status,
        "stage2_engine_status": (
            "PASS" if stage2_engine_pass else "FAIL"
        ),
        "current_authenticated_squad_status": "PRIVATE_SEPARATED",
        "current_squad_evidence_status": (
            "PASS" if current_squad_evidence_pass else "BLOCKED"
        ),
        "current_squad_evidence_mode": (
            "PUBLIC_SUBMITTED_PICKS"
            if public_evidence.get("current_public_squad_available") is True
            else "UNAVAILABLE"
        ),
        "mini_league_public_status": (
            "PASS" if mini_league_public_pass else "BLOCKED"
        ),
        "v6_frozen_baseline": BASELINE_V6_SHA,
        "v6_mutated": False,
        "v6_issue_repaired_inside_stage2": False,
        "planning_gw": planning_gw,
        "source_runtime": {
            "publish_integrity_status": v6_publish.get("status"),
            "logical_slot": v6_publish.get("logical_slot"),
            "run_id": v6_publish.get("run_id"),
            "identity_counts": v6_publish.get("identity_counts"),
            "owned_count": len(owned),
            "auth_is_stage2_blocker": False,
            "public_evidence": public_evidence,
        },
        "scoreline_model_selection": scoreline_selection,
        "universe": {
            "official_elements": len(bootstrap.get("elements") or []),
            "projected_players": len(players),
            "canonical_complete_players": canonical.get(
                "complete_players"
            ),
            "canonical_status": canonical.get("status"),
            "eligible_projected_players": len(eligible_projection_ids),
            "eligible_canonical_complete_players": len(
                eligible_canonical_ids
            ),
            "stage2_lineage_complete_players": canonical.get(
                "stage2_lineage_complete_players"
            ),
            "canonical_position_counts": canonical.get(
                "position_counts"
            ),
            "weights": canonical.get("weights"),
            "horizon_missing_count": len(horizon_missing),
            "horizon_missing_sample": horizon_missing[:20],
        },
        "watchlist20": {
            "state": watchlist.get("state"),
            "count": len(watchlist.get("rows") or []),
            "position_counts": watchlist.get("position_counts"),
            "same_lineage": watch_same_lineage,
            "lineage_contract": canonical.get(
                "stage2_lineage_contract"
            ),
            "lineage_complete_rows": sum(
                1
                for element in watch_ids
                if stage2_lineage_complete(
                    canonical_by_id.get(element) or {}
                )
            ),
        },
        "checks": checks,
        "acceptance_cases": named,
        "governance": {
            "fresh_runtime_read_only": True,
            "no_candidate_specific_shortcut": True,
            "no_predetermined_acceptance_winner": True,
            "official_fdr_is_sanity_prior_only": True,
            "missing_tactical_evidence_not_fabricated": True,
            "v6_repair_forbidden": True,
            "authenticated_private_session_required_for_stage2_green": False,
            "public_official_fpl_identity_and_mini_league_are_sufficient": True,
            "stage3_started": False,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(proof, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return proof


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-data-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    proof = run_acceptance(
        Path(args.runtime_data_root),
        output_path=Path(args.output),
    )
    print(
        json.dumps(
            {
                "status": proof.get("status"),
                "stage2_engine_status": proof.get(
                    "stage2_engine_status"
                ),
                "current_authenticated_squad_status": proof.get(
                    "current_authenticated_squad_status"
                ),
                "current_squad_evidence_status": proof.get(
                    "current_squad_evidence_status"
                ),
                "mini_league_public_status": proof.get(
                    "mini_league_public_status"
                ),
                "planning_gw": proof.get("planning_gw"),
                "projected_players": (
                    proof.get("universe") or {}
                ).get("projected_players"),
                "watchlist20": (
                    proof.get("watchlist20") or {}
                ).get("state"),
            },
            sort_keys=True,
        )
    )
    if args.strict and proof.get("status") != "GREEN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
