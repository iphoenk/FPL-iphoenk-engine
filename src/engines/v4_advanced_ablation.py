from __future__ import annotations

import json
from statistics import mean, median
from time import perf_counter

from src.engines.v4_runner import (
    _quality_config,
    f,
    fixture_map,
    minutes_contexts,
    opponent_defence_ratings,
    player_priors,
    team_defence_prior,
    team_role_priors,
)
from src.engines.v4_wc_optimizer import decision_report
from src.models.player_identity import build_identity_index
from src.models.v4_prediction import project_horizon, team_strength
from src.models.v4_prediction_inputs import load_prediction_enrichment
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA, atomic_json, read_json

RUNTIME_SNAPSHOT = DATA / "runtime" / "snapshot.v1.json"
ENRICHMENT_ARTIFACT = DATA / "runtime" / "enrichment.v1.json"
PREDICTIONS = DATA / "predictions_v4.json"
UNIVERSE = DATA / "universe.json"
FULL_DECISION = DATA / "wc_decision_v4.json"
OUTFILE = DATA / "advanced_ablation_v4.json"


def _variant_predictions(
    bootstrap: dict,
    fixtures: list[dict],
    generated_at: str,
    enrichment: dict,
    advanced_enabled: bool,
) -> dict:
    """Build the same prediction graph with only advanced enrichment toggled.

    Last-season priors, official current-state inputs, quality configuration,
    fixture model, prices and all optimizer semantics are held constant.
    """
    elements = bootstrap.get("elements", [])
    teams = {team["id"]: team for team in bootstrap.get("teams", [])}
    strengths = {team_id: team_strength(team_id, elements) for team_id in teams}
    identity = build_identity_index(elements, "2026-27")
    advanced = enrichment.get("advanced", {}) if advanced_enabled else {}
    last_season = enrichment.get("last_season", {})
    quality = _quality_config()
    finished_events = sum(bool(event.get("finished")) for event in bootstrap.get("events", []))
    xmins_context = minutes_contexts(elements, last_season, max(1, finished_events), advanced, quality)
    role_priors = team_role_priors(elements, advanced, quality)
    defence_ratings = opponent_defence_ratings(teams, fixtures, quality)
    rows: list[dict] = []

    for player in elements:
        priors = player_priors(player, last_season.get(player["id"]))
        role = role_priors[player["id"]]
        player_advanced = advanced.get(player["id"])
        fixtures_for_player = fixture_map(fixtures, player["team"], defence_ratings, 15)
        context = {
            "team_attack": strengths.get(player["team"], {}).get("attack", 1),
            "team_cs_prior": team_defence_prior(teams[player["team"]]),
            "point_in_time": generated_at,
            "advanced_source": "+".join((player_advanced or {}).get("sources", [])) or "official_fpl_current_state",
            "advanced_identity_match": (player_advanced or {}).get("identity_match"),
            "advanced_materially_distinct": False,
            "xg90_prior": priors["xg90_prior"],
            "xa90_prior": priors["xa90_prior"],
            "premium_prior": priors["premium_prior"],
            "role_prior": priors["role_prior"],
            "last_season_weight": priors["last_season_weight"],
            "last_season_source": priors["last_season_source"],
            "set_piece_share": role["set_piece_share"],
            "penalty_share": role["penalty_share"],
            "set_piece_order_weight": role["set_piece_order_weight"],
            "penalty_order_weight": role["penalty_order_weight"],
            "set_piece_source": role["source"],
            "role_attack_multiplier": role["role_attack_multiplier"],
            "role_prior_adjustment_applied": role["role_prior_adjustment_applied"],
            "role_scoring_mode": role["role_scoring_mode"],
            **xmins_context[player["id"]],
        }
        row = project_horizon(player, fixtures_for_player, context, player_advanced, n=15)
        row["stable_key"] = identity["by_element"][player["id"]]["key"]
        row["priors"] = {
            **{key: round(value, 4) if isinstance(value, (int, float)) else value for key, value in priors.items()},
            **role,
            **xmins_context[player["id"]],
        }
        price_millions = max(0.1, f(player.get("now_cost")) / 10)
        row["value"] = {
            "price_millions": round(price_millions, 1),
            "xpts5_per_million": round(row["xpts_5"] / price_millions, 4),
            "xpts15_per_million": round(row["xpts_15"] / price_millions, 4),
            "decision_usage": "optimizer_objective_bounded_value_term",
        }
        rows.append(row)

    rows.sort(key=lambda row: row["xpts_5"], reverse=True)
    return {
        "schema_version": 493,
        "model_version": "v4.9.2-truthful-health" if advanced_enabled else "v4.9.2-truthful-health-no-advanced",
        "generated_at": generated_at,
        "point_in_time": True,
        "advanced_enabled": advanced_enabled,
        "players": rows,
    }


def _by_element(predictions: dict) -> dict[int, dict]:
    return {int(row["element"]): row for row in predictions.get("players", []) if row.get("element") is not None}


def parity_report(authoritative: dict, shadow: dict, tolerance: float = 1e-6) -> dict:
    authoritative_by_id = _by_element(authoritative)
    shadow_by_id = _by_element(shadow)
    ids_match = set(authoritative_by_id) == set(shadow_by_id)
    max_delta = 0.0
    mismatches: list[dict] = []
    if ids_match:
        for element in sorted(authoritative_by_id):
            full = authoritative_by_id[element]
            candidate = shadow_by_id[element]
            for field in ("xpts_3", "xpts_5", "xpts_10", "xpts_15", "uncertainty"):
                delta = abs(float(full.get(field, 0) or 0) - float(candidate.get(field, 0) or 0))
                max_delta = max(max_delta, delta)
                if delta > tolerance:
                    mismatches.append({"element": element, "field": field, "delta": round(delta, 8)})
                    if len(mismatches) >= 20:
                        break
            if len(mismatches) >= 20:
                break
    return {
        "ok": ids_match and not mismatches,
        "ids_match": ids_match,
        "players": len(authoritative_by_id),
        "shadow_players": len(shadow_by_id),
        "max_horizon_delta": round(max_delta, 8),
        "tolerance": tolerance,
        "mismatches": mismatches,
    }


def _rank_map(predictions: dict, field: str = "xpts_5") -> dict[int, int]:
    ordered = sorted(
        predictions.get("players", []),
        key=lambda row: (float(row.get(field, 0) or 0), -int(row.get("element") or 0)),
        reverse=True,
    )
    return {int(row["element"]): index + 1 for index, row in enumerate(ordered)}


def compare_predictions(full: dict, ablated: dict) -> dict:
    full_by_id = _by_element(full)
    ablated_by_id = _by_element(ablated)
    common = sorted(set(full_by_id) & set(ablated_by_id))
    if not common or set(full_by_id) != set(ablated_by_id):
        raise RuntimeError("ablation player universe differs from full prediction universe")

    deltas: list[dict] = []
    abs_deltas: list[float] = []
    full_rank = _rank_map(full)
    ablated_rank = _rank_map(ablated)
    rank_shifts: list[int] = []
    for element in common:
        full_row = full_by_id[element]
        noadv_row = ablated_by_id[element]
        delta = float(full_row.get("xpts_5", 0) or 0) - float(noadv_row.get("xpts_5", 0) or 0)
        abs_delta = abs(delta)
        rank_shift = ablated_rank[element] - full_rank[element]
        abs_deltas.append(abs_delta)
        rank_shifts.append(abs(rank_shift))
        deltas.append(
            {
                "element": element,
                "name": full_row.get("name"),
                "position": full_row.get("position"),
                "full_xpts5": round(float(full_row.get("xpts_5", 0) or 0), 3),
                "no_advanced_xpts5": round(float(noadv_row.get("xpts_5", 0) or 0), 3),
                "delta_xpts5": round(delta, 3),
                "abs_delta_xpts5": round(abs_delta, 3),
                "full_rank": full_rank[element],
                "no_advanced_rank": ablated_rank[element],
                "rank_shift": rank_shift,
            }
        )

    deltas.sort(key=lambda row: (row["abs_delta_xpts5"], abs(row["rank_shift"])), reverse=True)

    def top_ids(predictions: dict, k: int) -> list[int]:
        return [
            int(row["element"])
            for row in sorted(
                predictions.get("players", []),
                key=lambda row: (float(row.get("xpts_5", 0) or 0), -int(row.get("element") or 0)),
                reverse=True,
            )[:k]
        ]

    top_overlap = {}
    for k in (10, 25, 50):
        full_ids = top_ids(full, k)
        ablated_ids = top_ids(ablated, k)
        overlap = set(full_ids) & set(ablated_ids)
        top_overlap[str(k)] = {
            "overlap": len(overlap),
            "overlap_ratio": round(len(overlap) / max(1, k), 4),
            "full_only": [element for element in full_ids if element not in overlap],
            "no_advanced_only": [element for element in ablated_ids if element not in overlap],
        }

    return {
        "players": len(common),
        "mean_abs_delta_xpts5": round(mean(abs_deltas), 4),
        "median_abs_delta_xpts5": round(median(abs_deltas), 4),
        "max_abs_delta_xpts5": round(max(abs_deltas), 4),
        "mean_abs_rank_shift": round(mean(rank_shifts), 4),
        "max_abs_rank_shift": max(rank_shifts),
        "players_abs_delta_ge": {
            "0.05": sum(value >= 0.05 for value in abs_deltas),
            "0.10": sum(value >= 0.10 for value in abs_deltas),
            "0.25": sum(value >= 0.25 for value in abs_deltas),
            "0.50": sum(value >= 0.50 for value in abs_deltas),
        },
        "top_overlap": top_overlap,
        "largest_impacts": deltas[:30],
    }


def compare_decisions(full: dict, ablated: dict) -> dict:
    full_ids = [int(x) for x in full.get("optimized_elements", [])]
    ablated_ids = [int(x) for x in ablated.get("optimized_elements", [])]
    full_set, ablated_set = set(full_ids), set(ablated_ids)
    full_out = {int(row["element"]) for row in full.get("out", [])}
    ablated_out = {int(row["element"]) for row in ablated.get("out", [])}
    full_in = {int(row["element"]) for row in full.get("in", [])}
    ablated_in = {int(row["element"]) for row in ablated.get("in", [])}
    return {
        "classification_full": full.get("classification"),
        "classification_no_advanced": ablated.get("classification"),
        "classification_changed": full.get("classification") != ablated.get("classification"),
        "optimized_squad_overlap": len(full_set & ablated_set),
        "optimized_squad_changed_players": len(full_set ^ ablated_set),
        "full_only_optimized": sorted(full_set - ablated_set),
        "no_advanced_only_optimized": sorted(ablated_set - full_set),
        "transfer_out_changed": full_out != ablated_out,
        "transfer_in_changed": full_in != ablated_in,
        "full_out": sorted(full_out),
        "no_advanced_out": sorted(ablated_out),
        "full_in": sorted(full_in),
        "no_advanced_in": sorted(ablated_in),
        "delta_best_xi_xpts_5_full": (full.get("delta") or {}).get("best_xi_xpts_5"),
        "delta_best_xi_xpts_5_no_advanced": (ablated.get("delta") or {}).get("best_xi_xpts_5"),
        "delta_bench_adjusted_utility_5_full": (full.get("delta") or {}).get("bench_adjusted_utility_5"),
        "delta_bench_adjusted_utility_5_no_advanced": (ablated.get("delta") or {}).get("bench_adjusted_utility_5"),
        "decision_changed": (
            full.get("classification") != ablated.get("classification")
            or full_set != ablated_set
            or full_out != ablated_out
            or full_in != ablated_in
        ),
    }


def run() -> dict:
    started = perf_counter()
    raw = read_json(RUNTIME_SNAPSHOT, {})
    enrichment_artifact = read_json(ENRICHMENT_ARTIFACT, {})
    authoritative = read_json(PREDICTIONS, {})
    universe = read_json(UNIVERSE, {})
    full_decision = read_json(FULL_DECISION, {})
    locked = read_json(CONFIG / "locked_squad.json", {})

    if raw.get("schema") != "snapshot.v1":
        raise RuntimeError("ablation requires runtime snapshot.v1")
    if not authoritative.get("players") or not universe.get("players") or not full_decision.get("optimized_elements"):
        raise RuntimeError("ablation requires production predictions, universe and WC decision")

    official = raw.get("official") or {}
    bootstrap = official.get("bootstrap") or {}
    fixtures = official.get("fixtures") or []
    stats_gw = enrichment_artifact.get("stats_gw")
    generated_at = authoritative.get("generated_at")
    enrichment = load_prediction_enrichment(bootstrap.get("elements", []), stats_gw)

    full_shadow = _variant_predictions(bootstrap, fixtures, generated_at, enrichment, advanced_enabled=True)
    parity = parity_report(authoritative, full_shadow)
    if not parity["ok"]:
        raise RuntimeError(f"ablation full-shadow parity failed: {parity}")

    no_advanced = _variant_predictions(bootstrap, fixtures, generated_at, enrichment, advanced_enabled=False)
    prediction_impact = compare_predictions(authoritative, no_advanced)
    ablated_decision = decision_report(no_advanced, universe, locked)
    decision_impact = compare_decisions(full_decision, ablated_decision)

    out = {
        "schema_version": 493,
        "engine": "v4.9.3-advanced-ablation",
        "status": "PASS",
        "generated_at": generated_at,
        "snapshot_sha256": file_digest(RUNTIME_SNAPSHOT),
        "enrichment_sha256": file_digest(ENRICHMENT_ARTIFACT),
        "model_version": authoritative.get("model_version"),
        "ablation": {
            "treatment": "community_advanced_current_season_enrichment",
            "control": "same_official_snapshot_and_last_season_priors_without_advanced_enrichment",
            "advanced_removed_only": True,
            "same_official_snapshot": True,
            "same_last_season_priors": True,
            "same_quality_config": True,
            "same_optimizer_semantics": True,
            "full_shadow_parity": parity,
        },
        "prediction_impact": prediction_impact,
        "decision_impact": decision_impact,
        "interpretation": {
            "impact_is_diagnostic_not_health_threshold": True,
            "small_effect_does_not_fail_pipeline": True,
            "decision_flip_is_reported_not_forced": True,
            "future_empirical_value_requires_reconciled_samples": True,
        },
        "performance_ms": round((perf_counter() - started) * 1000, 2),
    }
    atomic_json(OUTFILE, out)
    print(
        json.dumps(
            {
                "service": "advanced_ablation",
                "players": prediction_impact["players"],
                "mean_abs_delta_xpts5": prediction_impact["mean_abs_delta_xpts5"],
                "max_abs_rank_shift": prediction_impact["max_abs_rank_shift"],
                "decision_changed": decision_impact["decision_changed"],
                "performance_ms": out["performance_ms"],
            },
            ensure_ascii=False,
        )
    )
    return out


if __name__ == "__main__":
    run()
