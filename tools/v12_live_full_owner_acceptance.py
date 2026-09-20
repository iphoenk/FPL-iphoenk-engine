from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import urllib.parse
import urllib.request

from src.engines.v12_player_minutes import estimate_player_minutes
from src.engines.v12_player_events import (
    build_posterior_rates,
    load_event_config,
    project_player_fixture,
)
from src.engines.v12_tactical_role import attach_tactical_role_scores
from src.engines.v12_lineup_optimizer import optimize_lineup
from src.engines.v12_monte_carlo import run_correlated_monte_carlo
from src.models.team_strength import build_team_strength
from src.rules import ELEMENT_TYPE_TO_POSITION


RUNTIME_REF = "runtime-data-v6"
PLANNING_WIDTH = 5
PATHS = 500_000
SEED = 20260920


def _api(path: str):
    token = os.environ["GH_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "v12-live-full-owner-acceptance",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def _runtime_json(path: str):
    quoted = urllib.parse.quote(path, safe="/")
    meta = _api(f"contents/{quoted}?ref={urllib.parse.quote(RUNTIME_REF)}")
    content = meta.get("content")
    if content and meta.get("encoding") == "base64":
        raw = base64.b64decode(content).decode("utf-8")
    else:
        blob = _api(f"git/blobs/{meta['sha']}")
        raw = base64.b64decode(blob["content"]).decode("utf-8")
    return json.loads(raw), meta["sha"]


def _attempt_json(wrapper, request_id):
    for row in wrapper.get("attempts") or []:
        if row.get("request_id") == request_id:
            return row.get("json")
    raise RuntimeError(f"official_fpl request_id={request_id} missing")


def _projection0(row):
    for projection in row.get("price_change_projections") or []:
        try:
            if float(projection.get("offset")) == 0.0:
                return projection
        except (TypeError, ValueError):
            pass
    return None


def _select_pair(current_team, predictor):
    owned_ids = {int(row["element_id"]) for row in current_team["players"]}
    price_by_id = {int(row["id"]): row for row in predictor["data"]["players"]}
    choices = []
    for owned in current_team["players"]:
        if owned.get("position") != "MID":
            continue
        out_price = price_by_id.get(int(owned["element_id"]))
        if not out_price:
            continue
        budget = int(owned["selling_price"]) + int(current_team.get("bank") or 0)
        for candidate in predictor["data"]["players"]:
            if int(candidate.get("element_type") or 0) != 3:
                continue
            if int(candidate["id"]) in owned_ids:
                continue
            if int(candidate.get("now_cost") or 10**9) > budget:
                continue
            p0 = _projection0(candidate)
            if not p0:
                continue
            choices.append(
                (
                    -float(p0["projected_percent"]),
                    int(candidate["id"]),
                    owned,
                    out_price,
                    candidate,
                )
            )
    if not choices:
        raise RuntimeError("no affordable current owned-vs-challenger MID pair")
    choices.sort(key=lambda row: (row[0], row[1]))
    _, _, owned, out_price, candidate = choices[0]
    return owned, out_price, candidate


def _team_row(strength, team_id):
    return next(row for row in strength["teams"] if int(row["team_id"]) == int(team_id))


def _team_matchup(strength, raw_fixture):
    return next(
        row
        for row in strength["matchups"]
        if int(row.get("event") or 0) == int(raw_fixture.get("event") or 0)
        and int(row.get("team_h") or 0) == int(raw_fixture.get("team_h") or 0)
        and int(row.get("team_a") or 0) == int(raw_fixture.get("team_a") or 0)
    )


def _project_player(raw_player, planning_gw, fixtures, strength):
    player = dict(raw_player)
    element = int(player["id"])
    team_id = int(player["team"])
    position = ELEMENT_TYPE_TO_POSITION[int(player["element_type"])]
    player["position"] = position
    matches_played = int(_team_row(strength, team_id)["matches_played"])

    minutes = estimate_player_minutes(
        player,
        {"team_matches_played": matches_played},
    )
    priors = load_event_config()["position_priors"][position]
    rates = build_posterior_rates(
        player,
        position_prior=priors,
        historical=None,
        feature=None,
    )

    raw_rows = [
        row for row in fixtures
        if planning_gw <= int(row.get("event") or 0) < planning_gw + PLANNING_WIDTH
        and team_id in {int(row.get("team_h") or -1), int(row.get("team_a") or -1)}
    ]
    raw_rows.sort(key=lambda row: (int(row["event"]), str(row.get("kickoff_time") or "")))
    if len(raw_rows) != PLANNING_WIDTH:
        raise RuntimeError(f"element={element} fixture coverage={len(raw_rows)}/{PLANNING_WIDTH}")

    xpts_by_gw = []
    for raw_fixture in raw_rows:
        gw = int(raw_fixture["event"])
        home = int(raw_fixture["team_h"]) == team_id
        matchup = {**dict(raw_fixture), **_team_matchup(strength, raw_fixture)}
        event = project_player_fixture(
            player,
            minutes,
            matchup,
            home=home,
            rates=rates,
            league_baseline=strength["baseline"],
        )
        aggregate = dict(event.get("aggregate") or {})
        xpts_by_gw.append(
            {
                "gw": gw,
                "mean": aggregate.get("expected_fpl_points"),
                "std": aggregate.get("points_std"),
                "points_variance": aggregate.get("points_variance"),
                "point_distribution": deepcopy(event.get("point_distribution") or {}),
                "event_probabilities": deepcopy(event.get("event_probabilities") or {}),
                "fixtures": [event],
            }
        )

    return {
        "element": element,
        "name": player.get("web_name"),
        "position": position,
        "team_id": team_id,
        "element_type": int(player["element_type"]),
        "projection_confidence": minutes.get("confidence"),
        "xmins": minutes,
        "posterior_rates": rates,
        "xpts_by_gw": xpts_by_gw,
        "current_season": {
            "starts": player.get("starts"),
            "minutes": player.get("minutes"),
        },
        "set_piece_role": {
            "source": "OFFICIAL_FPL_BOOTSTRAP",
            "corners_and_indirect_freekicks_order": player.get("corners_and_indirect_freekicks_order"),
            "direct_freekicks_order": player.get("direct_freekicks_order"),
        },
        "penalty_role": {
            "source": "OFFICIAL_FPL_BOOTSTRAP",
            "order": player.get("penalties_order"),
        },
    }


def _route_row(decision, gw):
    return {
        "gw": int(gw),
        "starting_xi": [int(row["element"]) for row in decision["starting_xi"]],
        "bench_order": [int(row["element"]) for row in decision["bench"]["order"]],
        "bench_gk": int(decision["bench"]["gk"]["element"]),
        "captain": int(decision["captain"]["element"]),
        "vice_captain": int(decision["vice_captain"]["element"]),
    }


def _decision_summary(decision):
    return {
        "formation": decision["formation"],
        "starting_xi": [int(row["element"]) for row in decision["starting_xi"]],
        "bench_order": [int(row["element"]) for row in decision["bench"]["order"]],
        "bench_gk": int(decision["bench"]["gk"]["element"]),
        "captain": int(decision["captain"]["element"]),
        "vice_captain": int(decision["vice_captain"]["element"]),
        "lineup_score": deepcopy(decision["lineup_score"]),
        "legal_xi_count": decision["legal_xi_count"],
        "model_owner": decision["model_owner"],
    }


def main():
    current_team, team_sha = _runtime_json("data/v6/personal/current_team.json")
    official_wrapper, official_sha = _runtime_json("data/v6/current/official_fpl.json")
    predictor, predictor_sha = _runtime_json("data/v6/current/official_price_predictor.json")

    bootstrap = _attempt_json(official_wrapper, "bootstrap")
    fixtures = _attempt_json(official_wrapper, "fixtures")
    planning_gw = int(next(row["id"] for row in bootstrap["events"] if row.get("is_next")))
    strength = build_team_strength(bootstrap, fixtures)
    element_by_id = {int(row["id"]): row for row in bootstrap["elements"]}

    owned_pick, owned_price, challenger_price = _select_pair(current_team, predictor)
    out_id = int(owned_pick["element_id"])
    in_id = int(challenger_price["id"])
    current_ids = [int(row["element_id"]) for row in current_team["players"]]
    change_ids = [in_id if element == out_id else element for element in current_ids]
    unique_ids = sorted(set(current_ids + [in_id]))

    projections = {
        "planning_gw": planning_gw,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "players": [
            _project_player(element_by_id[element], planning_gw, fixtures, strength)
            for element in unique_ids
        ],
    }

    hold_rows = []
    change_rows = []
    hold_decisions = {}
    change_decisions = {}

    for gw in range(planning_gw, planning_gw + PLANNING_WIDTH):
        gw_projection = deepcopy(projections)
        attach_tactical_role_scores(gw_projection, gw, team_strength=strength)

        hold = optimize_lineup(
            gw_projection,
            current_ids,
            planning_gw=gw,
            generated_at=projections["generated_at"],
        )
        change = optimize_lineup(
            gw_projection,
            change_ids,
            planning_gw=gw,
            generated_at=projections["generated_at"],
        )
        hold_rows.append(_route_row(hold, gw))
        change_rows.append(_route_row(change, gw))
        hold_decisions[str(gw)] = _decision_summary(hold)
        change_decisions[str(gw)] = _decision_summary(change)

    # Deliberately zero-cost FOOTBALL-ONLY comparison. This is not a claim that
    # the actual transfer costs zero FT/hit points; exact FT is unavailable in
    # the authenticated V6 fact and remains separated below.
    route_defs = [
        {
            "route_id": "HOLD",
            "classification": "HOLD",
            "per_gw": hold_rows,
            "execution_cost_points": 0.0,
        },
        {
            "route_id": "CHANGE_FOOTBALL_ONLY",
            "classification": "FOOTBALL_ONLY_CHANGE",
            "per_gw": change_rows,
            "execution_cost_points": 0.0,
        },
    ]
    mc = run_correlated_monte_carlo(
        projections,
        route_defs,
        actual_paths=PATHS,
        seed=SEED,
        input_snapshot_id=f"live-native-{official_sha[:12]}",
        generated_at=projections["generated_at"],
        canonical=True,
        horizons=(1, 2, 3, 5),
        selected_route_id="CHANGE_FOOTBALL_ONLY",
        factual_snapshot_timestamps={
            "official_fpl": official_wrapper.get("checked_at") or projections["generated_at"],
            "current_team": current_team.get("generated_at") or projections["generated_at"],
        },
        factual_artifact_fingerprints={
            "official_fpl": official_sha,
            "current_team": team_sha,
            "official_price_predictor": predictor_sha,
        },
    )

    metrics = deepcopy(mc["metrics"])
    pairwise = deepcopy(mc["paired_outputs"])
    change_metrics = metrics["CHANGE_FOOTBALL_ONLY"]

    output = {
        "acceptance_kind": "CURRENT_LIVE_NATIVE_FULL_OWNER_EXECUTION",
        "planning_gw": planning_gw,
        "player_out": {
            "element_id": out_id,
            "name": element_by_id[out_id]["web_name"],
            "selling_price": float(owned_pick["selling_price"]) / 10.0,
        },
        "player_in": {
            "element_id": in_id,
            "name": element_by_id[in_id]["web_name"],
            "current_price": float(challenger_price["now_cost"]) / 10.0,
        },
        "affordability": {
            "status": "PASS",
            "budget": (int(owned_pick["selling_price"]) + int(current_team.get("bank") or 0)) / 10.0,
            "bank_after": (
                int(owned_pick["selling_price"])
                + int(current_team.get("bank") or 0)
                - int(challenger_price["now_cost"])
            ) / 10.0,
        },
        "p1_7": {
            "owner": "V12_LINEUP_OPTIMIZER",
            "hold": hold_decisions,
            "change": change_decisions,
        },
        "monte_carlo": {
            "owner": mc["model_owner"],
            "execution_state": mc["execution_state"],
            "canonical_pass": mc["canonical_pass"],
            "actual_paths": mc["actual_paths"],
            "horizons": mc["horizons"],
            "correlated": mc["correlated"],
            "common_random_numbers": mc["common_random_numbers"],
            "convergence": mc["convergence_evidence"],
            "change_metrics": change_metrics,
            "pairwise": pairwise,
            "football_only_zero_transfer_cost": True,
            "transfer_economics_applied": False,
        },
        "robustness": {
            horizon: {
                "status": row["status"],
                "mean_gross_points": row["mean_gross_points"],
                "median": row.get("median"),
                "standard_deviation": row.get("standard_deviation"),
                "p10": row.get("p10"),
                "p50": row.get("p50"),
                "p90": row.get("p90"),
                "p_route_gt_hold": row.get("p_route_gt_hold"),
                "p_route_lt_hold": row.get("p_route_lt_hold"),
                "downside_probability": row.get("downside_probability"),
                "material_upside_probability": row.get("material_upside_probability"),
                "mean_difference_vs_hold": row.get("mean_difference_vs_hold"),
                "expected_regret": row.get("expected_regret"),
            }
            for horizon, row in change_metrics.items()
        },
        "hard_fact_gap": {
            "free_transfers": current_team.get("free_transfers"),
            "free_transfers_availability": (current_team.get("availability") or {}).get("free_transfers"),
            "actual_transfer_cost": "NOT_ASSERTED",
            "final_net_transfer_utility": "NOT_ASSERTED",
            "information_value_of_waiting": "NO_CURRENT_GOVERNED_INPUT_ARTIFACT",
        },
        "decision_semantics": {
            "football_distribution": "COMPLETE",
            "transfer_economics": "BLOCKED_BY_MISSING_EXACT_FT_FACT",
            "final_transfer_action": "WAIT",
            "reason": "Do not convert zero-cost football-only MC into actual transfer economics.",
        },
        "runtime_artifacts": {
            "current_team_sha": team_sha,
            "official_fpl_sha": official_sha,
            "official_price_predictor_sha": predictor_sha,
        },
    }

    print("V12_LIVE_FULL_OWNER_ACCEPTANCE_BEGIN")
    print(json.dumps(output, sort_keys=True))
    print("V12_LIVE_FULL_OWNER_ACCEPTANCE_END")

    assert mc["execution_state"] == "EXECUTED"
    assert int(mc["actual_paths"]) >= 500_000
    assert all(row["status"] == "READY" for row in change_metrics.values())
    assert all(decision["model_owner"] == "V12_LINEUP_OPTIMIZER" for decision in hold_decisions.values())
    assert all(decision["model_owner"] == "V12_LINEUP_OPTIMIZER" for decision in change_decisions.values())


if __name__ == "__main__":
    main()
