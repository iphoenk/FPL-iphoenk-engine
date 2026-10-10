from __future__ import annotations

"""GW6 owner-requested what-if transfers; structural legality, not a scoring model.

This is a deterministic, public-safe enumerator. It NEVER recomputes expected
points or claims transfer Monte Carlo from a baseline result. P1.7 and P1.4
are the sole canonical analytical owners. Personal selling prices are stale;
bank and FT remain unauthenticated. No transfer execution is attempted.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "config/intelligence/gw6_owner_transfer_matrix.json"
HALL_ADDENDUM_PATH = ROOT / "config/intelligence/gw6_hall_candidate.json"


def _hall_candidate() -> dict[str, Any]:
    payload = json.loads(HALL_ADDENDUM_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "GW6_OWNER_HALL_PRICE_ADDENDUM_V1":
        raise ValueError("invalid public Hall addendum contract")
    player = dict(payload["player"])
    if (int(player["element_id"]), int(player["element_type"]), int(player["team_id"])) != (449, 2, 17):
        raise ValueError("Hall candidate identity mismatch")
    return player



def _players_by_id(items: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(player["element_id"]): dict(player) for player in items}


def _squad_check(players: list[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    ids = [int(player["element_id"]) for player in players]
    teams = Counter(int(player["team_id"]) for player in players)
    positions = Counter(int(player["element_type"]) for player in players)
    required = {
        int(position): int(count)
        for position, count in (config["rules"]["positions"]).items()
    }
    assert len(players) == 15 and len(set(ids)) == 15, "scenario must have 15 unique players"
    assert positions == required, f"illegal squad positional mix: {positions}"
    return {
        "club_legal": max(teams.values()) <= int(config["rules"]["max_same_team"]),
        "max_club_count": max(teams.values()),
        "arsenal_count": teams.get(1, 0),
        "team_counts": dict(sorted(teams.items())),
    }


def build_matrix(config: Mapping[str, Any]) -> dict[str, Any]:
    if config.get("contract") != "GW6_OWNER_REQUEST_TRANSFER_FORMATION_MATRIX_V1":
        raise ValueError("unexpected transfer matrix contract")
    owned = _players_by_id(list(config["owned"]))
    candidates = _players_by_id(list(config["candidates"]))
    hall = _hall_candidate()
    candidates[int(hall["element_id"])] = hall
    lookup = {**owned, **candidates}
    if len(owned) != 15:
        raise ValueError("exact 15 owned players required")
    baseline = dict(config["baseline"])
    formations = [
        str(row[0]) for row in baseline["canonical_formations"]
    ]
    if len(formations) != 8 or len(set(formations)) != 8:
        raise ValueError("all 8 legal formations required")

    combinations: list[dict[str, Any]] = []
    matrix: list[dict[str, Any]] = []
    for forward in (346, 249, 569):
        for midfielder in (426, 427):
            for attacking_mid in (68, 12):
                exits = (31, 305, 258, 233, 449) if attacking_mid == 12 else (31, 449)
                for replacement_def in exits:
                    changes: dict[int, int] = {}
                    for old, new in (
                        (346, forward), (426, midfielder),
                        (68, attacking_mid), (31, replacement_def),
                    ):
                        if old != new:
                            changes[old] = new
                    squad = [
                        dict(lookup[changes.get(old, old)])
                        for old in owned
                    ]
                    club_check = _squad_check(squad, config)
                    stale_cash_delta = sum(
                        int(owned[old]["sell_value_stale"])
                        - int(candidates[new]["now_cost"])
                        for old, new in changes.items()
                    )
                    assumed_bank = int(config["illustrative_bank_tenths"])
                    fundable_if_assumed_bank = (
                        assumed_bank + stale_cash_delta >= 0
                    )
                    if not club_check["club_legal"]:
                        status = "ILLEGAL_MAX_3_CLUB"
                    elif not fundable_if_assumed_bank:
                        status = "INDICATIVE_UNFUNDED"
                    else:
                        status = "STRUCTURAL_PASS_FINANCE_UNVERIFIED"
                    case_id = f"GW6-R{len(combinations)+1:02d}"
                    case = {
                        "scenario_id": case_id,
                        "forward_element": forward,
                        "bruno_element": midfielder,
                        "tavernier_element": attacking_mid,
                        "konsa_element": replacement_def,
                        "out_in": [
                            {"out": old, "in": new}
                            for old, new in sorted(changes.items())
                        ],
                        "transfers": len(changes),
                        "squad_element_ids": sorted(int(row["element_id"]) for row in squad),
                        "team_counts": club_check["team_counts"],
                        "arsenal_count": club_check["arsenal_count"],
                        "club_legal": club_check["club_legal"],
                        "stale_sale_cash_delta_tenths": stale_cash_delta,
                        "bank_illustrative_after_tenths": (
                            assumed_bank + stale_cash_delta
                        ),
                        "fundable_only_if_bank_illustration_is_true": fundable_if_assumed_bank,
                        "status": status,
                        "official_bank_verified": False,
                        "free_transfers_verified": False,
                        "hit_points": None,
                        "scenario_monte_carlo_state": (
                            "NO_SCENARIO_MC" if changes else "BASELINE_MC_REFERENCE_ONLY"
                        ),
                    }
                    combinations.append(case)
                    for formation in formations:
                        row = {
                            "scenario_id": case_id,
                            "formation": formation,
                            "status": status,
                            "club_legal": club_check["club_legal"],
                            "transfers": len(changes),
                            "cash_delta_tenths": stale_cash_delta,
                            "illustrative_bank_after_tenths": assumed_bank + stale_cash_delta,
                            "captain_adjusted_xpts": (
                                next(float(value) for name, value in baseline["canonical_formations"]
                                     if name == formation)
                                if not changes else None
                            ),
                            "points_authority": (
                                "P1_7_BASELINE_20261010_1004"
                                if not changes else "P1_7_WHAT_IF_REQUIRED"
                            ),
                            "mc_500k_status": (
                                "BASELINE_PACKAGE_ONLY"
                                if not changes else "NOT_EXECUTED"
                            ),
                            "mc_paths_for_this_squad": (
                                500_000 if not changes else None
                            ),
                        }
                        matrix.append(row)

    if len(combinations) != 42 or len(matrix) != 336:
        raise AssertionError("scenario grid coverage changed")
    admissible = [
        case for case in combinations
        if case["status"] == "STRUCTURAL_PASS_FINANCE_UNVERIFIED"
    ]
    assert len(admissible) == 19, "structural+illustrative feasibility changed"
    return {
        "contract": "GW6_OWNER_TRANSFER_MATRIX_RESULTS_V1",
        "authority": "WHAT_IF_ONLY_NO_PRODUCTION_DECISION",
        "prices": config["price_source"],
        "finance": {
            "bank_auth": None,
            "ft_auth": None,
            "selling_price_auth": "STALE_NOT_AUTHORIZED",
            "assumed_bank_tenths": config["illustrative_bank_tenths"],
        },
        "coverage": {
            "distinct_squads": len(combinations),
            "formation_rows": len(matrix),
            "conditionally_fundable_squads": len(admissible),
            "conditionally_fundable_formation_rows": 8 * len(admissible),
            "invalid_or_unfunded_formation_rows": len(matrix) - 8 * len(admissible),
        },
        "baseline_500k_mc_run": baseline["run_id"],
        "base_mc_is_not_what_if_mc": True,
        "scenarios": combinations,
        "formation_matrix": matrix,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(INPUT_PATH))
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    data = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    matrix = build_matrix(data)
    target = Path(arguments.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(matrix["coverage"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
