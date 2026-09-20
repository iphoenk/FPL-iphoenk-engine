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
from src.engines.v12_player_comparator import compare_player_to_candidates
from src.models.team_strength import build_team_strength
from src.rules import ELEMENT_TYPE_TO_POSITION


RUNTIME_REF = "runtime-data-v6"
OUT_PATH = "/tmp/v12_live_owner_acceptance.json"


def _api(path: str):
    token = os.environ["GH_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "v12-live-owner-acceptance",
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


def _rest_context(all_fixtures, team_id, fixture):
    current_kickoff = datetime.fromisoformat(str(fixture["kickoff_time"]).replace("Z", "+00:00"))
    previous = []
    for row in all_fixtures:
        if team_id not in {int(row.get("team_h") or -1), int(row.get("team_a") or -1)}:
            continue
        kickoff = row.get("kickoff_time")
        if not kickoff:
            continue
        dt = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
        if dt < current_kickoff:
            previous.append(dt)
    prior = max(previous) if previous else None
    days = None if prior is None else round((current_kickoff - prior).total_seconds() / 86400.0, 2)
    return {
        "days_rest": days,
        "scope": "OFFICIAL_PL_FIXTURES",
        "competition_schedule_complete": False,
    }


def _role_profile(position, component, context):
    role_state = str(component.get("role_state") or "UNAVAILABLE")
    if role_state in {"OBSERVED", "CONFLICTED"}:
        evidence_class = "OBSERVED_ROLE"
    elif role_state == "INFERRED":
        evidence_class = "INFERRED_ROLE"
    else:
        evidence_class = "FPL_POSITION_ONLY"
    vector = dict(context.get("scoring_channel_vector") or {})
    routes = [
        key
        for key, value in sorted(vector.items(), key=lambda item: item[0])
        if value is not None and float(value) > 0.0
    ]
    return {
        "evidence_class": evidence_class,
        "role_summary": f"{position}; P1.6 role_state={role_state}",
        "route_to_points": routes,
        "provenance": "Official FPL position + native V12 P1.6 scoring-channel evidence",
    }


def _native_player_bundle(raw_player, planning_gw, fixtures, strength, team_names):
    player = dict(raw_player)
    position = ELEMENT_TYPE_TO_POSITION[int(player["element_type"])]
    player["position"] = position
    team_id = int(player["team"])
    matches_played = int(_team_row(strength, team_id)["matches_played"])
    minutes = estimate_player_minutes(
        player,
        {"team_matches_played": matches_played},
    )
    position_prior = load_event_config()["position_priors"][position]
    rates = build_posterior_rates(
        player,
        position_prior=position_prior,
        historical=None,
        feature=None,
    )

    raw_rows = [
        row
        for row in fixtures
        if planning_gw <= int(row.get("event") or 0) <= planning_gw + 4
        and team_id in {int(row.get("team_h") or -1), int(row.get("team_a") or -1)}
    ]
    raw_rows.sort(key=lambda row: (int(row["event"]), str(row.get("kickoff_time") or "")))

    xpts_by_gw = []
    event_by_gw = {}
    fixture_input_by_gw = {}
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
        event_by_gw[gw] = event
        fixture_input_by_gw[gw] = matchup
        xpts_by_gw.append({"gw": gw, "fixtures": [matchup]})

    projection_base = {
        "element": int(player["id"]),
        "position": position,
        "team_id": team_id,
        "element_type": int(player["element_type"]),
        "current_season": {
            "starts": player.get("starts"),
            "minutes": player.get("minutes"),
        },
        "xmins": minutes,
        "posterior_rates": rates,
        "xpts_by_gw": xpts_by_gw,
        "set_piece_role": {
            "source": "OFFICIAL_FPL_BOOTSTRAP",
            "corners_and_indirect_freekicks_order": player.get(
                "corners_and_indirect_freekicks_order"
            ),
            "direct_freekicks_order": player.get("direct_freekicks_order"),
        },
        "penalty_role": {
            "source": "OFFICIAL_FPL_BOOTSTRAP",
            "order": player.get("penalties_order"),
        },
    }

    tactical_by_gw = {}
    profile_by_gw = {}
    for gw in sorted(event_by_gw):
        projection = {"players": [deepcopy(projection_base)]}
        attach_tactical_role_scores(
            projection,
            gw,
            team_strength=strength,
        )
        component = projection["players"][0]["tactical_role_component"]
        contexts = component.get("fixture_contexts") or []
        if not contexts:
            raise RuntimeError(f"P1.6 produced no fixture context for element={player['id']} gw={gw}")
        context = contexts[0]
        tactical_by_gw[gw] = context
        profile_by_gw[gw] = _role_profile(position, component, context)

    bundle_fixtures = []
    for raw_fixture in raw_rows:
        gw = int(raw_fixture["event"])
        opponent_id = (
            int(raw_fixture["team_a"])
            if int(raw_fixture["team_h"]) == team_id
            else int(raw_fixture["team_h"])
        )
        home = int(raw_fixture["team_h"]) == team_id
        bundle_fixtures.append(
            {
                "gw": gw,
                "opponent": team_names[opponent_id],
                "home_away": "H" if home else "A",
                "venue": team_names[team_id] if home else team_names[opponent_id],
                "minutes": minutes,
                "events": event_by_gw[gw],
                "tactical": tactical_by_gw[gw],
                "tactical_profile": profile_by_gw[gw],
                "rest_congestion": _rest_context(fixtures, team_id, raw_fixture),
                "midweek_competition_context": {
                    "scope": "NOT_BOUND_IN_V6_OFFICIAL_PL_FIXTURE_AUTHORITY"
                },
                "fixture_confidence": "CURRENT_NATIVE_OWNER_EXECUTION",
                "data_quality": "CURRENT_V6_FACTS+NATIVE_V12",
                "provenance": "runtime-data-v6 official_fpl + native V12 owners",
            }
        )

    return {
        "element_id": int(player["id"]),
        "name": player["web_name"],
        "position": position,
        "club_id": team_id,
        "price": float(player["now_cost"]) / 10.0,
        "fixtures": bundle_fixtures,
        "competition_schedule": [],
        "provenance": "live bounded owner acceptance",
    }, {
        "minutes": minutes,
        "rates": rates,
        "events": event_by_gw,
        "tactical": tactical_by_gw,
    }


def main():
    current_team, team_sha = _runtime_json("data/v6/personal/current_team.json")
    official_wrapper, official_sha = _runtime_json("data/v6/current/official_fpl.json")
    predictor, predictor_sha = _runtime_json("data/v6/current/official_price_predictor.json")

    bootstrap = _attempt_json(official_wrapper, "bootstrap")
    fixtures = _attempt_json(official_wrapper, "fixtures")
    planning_gw = int(next(row["id"] for row in bootstrap["events"] if row.get("is_next")))
    strength = build_team_strength(bootstrap, fixtures)
    team_names = {int(row["id"]): row["name"] for row in bootstrap["teams"]}
    element_by_id = {int(row["id"]): row for row in bootstrap["elements"]}

    owned_pick, owned_price, challenger_price = _select_pair(current_team, predictor)
    out_id = int(owned_pick["element_id"])
    in_id = int(challenger_price["id"])

    player_out, native_out = _native_player_bundle(
        element_by_id[out_id], planning_gw, fixtures, strength, team_names
    )
    player_in, native_in = _native_player_bundle(
        element_by_id[in_id], planning_gw, fixtures, strength, team_names
    )
    player_out["sell_value"] = float(owned_pick["selling_price"]) / 10.0

    budget = (int(owned_pick["selling_price"]) + int(current_team.get("bank") or 0)) / 10.0
    affordability = {
        "status": "PASS",
        "budget": budget,
        "candidate_price": float(challenger_price["now_cost"]) / 10.0,
        "bank_after": round(
            budget - float(challenger_price["now_cost"]) / 10.0, 1
        ),
        "source": "AUTHENTICATED_CURRENT_TEAM+OFFICIAL_PRICE",
    }
    context = {
        in_id: {
            "affordability": affordability,
            "structural_impact": {
                "same_position_transfer": True,
                "position_slot_preserved": True,
            },
            "robustness": {
                "status": "NOT_RUN",
                "reason": "P1.7/MC route execution is outside this live owner-schema acceptance",
            },
            "expected_regret": None,
            "information_value_of_waiting": None,
            "gate0": {"status": "PASS"},
            "football_label": "CHALLENGER",
            "operational_action": "WAIT",
            "decision_reasons": ["native P1.1/P1.3/P1.6 evidence refreshed"],
            "decision_risks": ["exact FT/hit economics not present in authenticated V6 fact"],
            "reversal_triggers": ["fresh lineup/availability/price/economics evidence"],
        }
    }

    result = compare_player_to_candidates(
        player_out=player_out,
        challengers=[player_in],
        comparison_timestamp=datetime.now(timezone.utc).isoformat(),
        planning_gw=planning_gw,
        candidate_context=context,
    )
    battle = result["comparisons"][0]

    required_native = []
    for row in battle["fixture_by_fixture"]:
        for side in ("player_out", "player_in"):
            for fixture in row[side]:
                required_native.append(
                    {
                        "gw": row["gw"],
                        "side": side,
                        "opponent": fixture["opponent"],
                        "home_away": fixture["home_away"],
                        "xpts": fixture["xpts"],
                        "xmins": fixture["xmins"],
                        "p_start": fixture["p_start"],
                        "p_dnp": fixture["p_dnp"],
                        "p60": fixture["p_60_plus"],
                        "tactical_role_score": fixture["canonical_tactical_role_score"],
                        "tactical_evidence_class": fixture["tactical_evidence_class"],
                        "route_to_points": fixture["route_to_points"],
                        "rest_congestion": fixture["rest_congestion"],
                        "owner_schema_binding": fixture["owner_schema_binding"],
                    }
                )

    model_fields_complete = all(
        row["xpts"] is not None
        and row["xmins"] is not None
        and row["p_start"] is not None
        and row["p_dnp"] is not None
        and isinstance(row["p60"], dict)
        and row["p60"].get("value") != "UNAVAILABLE"
        and row["tactical_role_score"] is not None
        and row["route_to_points"]
        for row in required_native
    )

    output = {
        "acceptance_kind": "CURRENT_LIVE_NATIVE_OWNER_EXECUTION",
        "planning_gw": planning_gw,
        "player_out": battle["player_out"],
        "player_in": battle["player_in"],
        "runtime_artifacts": {
            "current_team_sha": team_sha,
            "official_fpl_sha": official_sha,
            "official_price_predictor_sha": predictor_sha,
        },
        "native_model_fields_complete": model_fields_complete,
        "fixture_rows": required_native,
        "horizons": {
            "1GW": battle["horizon_1gw"],
            "2GW": battle["horizon_2gw"],
            "3GW": battle["horizon_3gw"],
            "5GW": battle["horizon_5gw"],
        },
        "raw_gain": {
            "1GW": battle["raw_gain_1gw"],
            "2GW": battle["raw_gain_2gw"],
            "3GW": battle["raw_gain_3gw"],
            "5GW": battle["raw_gain_5gw"],
        },
        "affordability": affordability,
        "structural_impact": battle["structural_impact"],
        "hard_fact_gaps": {
            "free_transfers": current_team.get("free_transfers"),
            "free_transfers_availability": (
                current_team.get("availability") or {}
            ).get("free_transfers"),
            "transfer_economics": "NOT_COMPUTED_WITHOUT_EXACT_FT_FACT",
            "robustness_regret_mc": "NOT_RUN_WITHOUT_P1.7_ROUTE+EXACT_TRANSFER_ECONOMICS",
            "non_pl_competition_schedule": "NOT_AUTHORED_BY_OFFICIAL_FPL_V6_FIXTURE_AUTHORITY",
        },
        "operational_action": battle["operational_action"],
        "reversal_triggers": battle["reversal_triggers"],
        "no_duplicate_models": {
            "xpts": battle["duplicate_xpts_model"] is False,
            "xmins": battle["duplicate_xmins_model"] is False,
            "tactical": battle["duplicate_tactical_scorer"] is False,
        },
    }
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, sort_keys=True)
    print("V12_LIVE_OWNER_ACCEPTANCE_BEGIN")
    print(json.dumps(output, sort_keys=True))
    print("V12_LIVE_OWNER_ACCEPTANCE_END")
    if not model_fields_complete:
        raise SystemExit("native owner model fields did not complete")


if __name__ == "__main__":
    main()
