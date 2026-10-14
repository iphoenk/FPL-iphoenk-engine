from __future__ import annotations

"""Stage-1 statistical utilities for existing V12 model owners.

This module does not own final xMins, FDR, event posterior, xPts, scheduling,
or rendering. It prepares governed evidence and canonical component inputs for
the existing owners.
"""

from collections import Counter, defaultdict
import math
from statistics import NormalDist
from typing import Any, Mapping, Sequence

from src.engines.v12_player_minutes import (
    build_player_selection_evidence,
    estimate_player_minutes,
)

Z90 = NormalDist().inv_cdf(0.95)
GOAL_POINTS = {"GK": 10.0, "DEF": 6.0, "MID": 5.0, "FWD": 4.0}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)
    return out if math.isfinite(out) else float(default)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _position(value: Any) -> str:
    text = str(value or "").upper()
    return "GK" if text in {"GK", "GKP"} else text


def _rate90(
    rows: Sequence[Mapping[str, Any]],
    field: str,
    *,
    weights: Sequence[float] | None = None,
) -> float | None:
    ws = list(weights or [1.0] * len(rows))
    exposure = sum(
        max(0.0, _f(row.get("minutes"))) * weight / 90.0
        for row, weight in zip(rows, ws)
    )
    if exposure <= 0:
        return None
    mass = sum(
        max(0.0, _f(row.get(field))) * weight
        for row, weight in zip(rows, ws)
    )
    return mass / exposure


def _midrank(value: float, universe: Sequence[float]) -> float:
    values = sorted(float(x) for x in universe)
    if not values:
        return 50.0
    less = sum(x < value for x in values)
    equal = sum(x == value for x in values)
    return 100.0 * (less + 0.5 * equal) / len(values)


def opponent_adjust_match_rows(
    rows: Sequence[Mapping[str, Any]],
    strength: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Attach venue-specific opponent weights to historical observations."""
    teams = {
        _i(row.get("team_id")): dict(row)
        for row in (strength or {}).get("teams") or []
        if _i(row.get("team_id")) > 0
    }
    out = []
    for raw in rows:
        row = dict(raw)
        opponent = teams.get(_i(row.get("opponent_team_id")))
        home = bool(row.get("home"))
        if opponent:
            defence = _f(
                opponent.get(
                    "defence_away_index" if home else "defence_home_index"
                ),
                1.0,
            )
            attack = _f(
                opponent.get(
                    "attack_away_index" if home else "attack_home_index"
                ),
                1.0,
            )
            attack_weight = _clamp(math.sqrt(max(0.2, defence)), 0.70, 1.30)
            defence_weight = _clamp(math.sqrt(max(0.2, attack)), 0.70, 1.30)
            status = "AVAILABLE"
        else:
            attack_weight = defence_weight = 1.0
            status = "UNAVAILABLE_NEUTRAL_WEIGHT"
        row["opponent_strength_weight"] = round(attack_weight, 6)
        row["opponent_attack_weight"] = round(defence_weight, 6)
        row["opponent_adjustment"] = {
            "status": status,
            "attack_observation_weight": round(attack_weight, 6),
            "defence_observation_weight": round(defence_weight, 6),
            "home_advantage_embedded_in_venue_strength": True,
            "league_position_primary": False,
            "elo_primary": False,
        }
        out.append(row)
    return out


def _gamma_interval(shape: float, rate: float) -> list[float]:
    if shape <= 0 or rate <= 0:
        return [0.0, 0.0]
    values = []
    for z in (-Z90, Z90):
        base = max(
            1e-9,
            1.0 - 1.0 / (9.0 * shape)
            + z / (3.0 * math.sqrt(shape)),
        )
        values.append(max(0.0, shape * base**3 / rate))
    return [round(values[0], 6), round(values[1], 6)]


def _sufficient(
    rows: Sequence[Mapping[str, Any]],
    field: str,
    weight_field: str,
) -> tuple[float, float]:
    mass = exposure = 0.0
    for row in rows:
        minutes = max(0.0, _f(row.get("minutes")))
        if minutes <= 0:
            continue
        weight = _clamp(_f(row.get(weight_field), 1.0), 0.5, 1.5)
        exposure += minutes * weight / 90.0
        mass += max(0.0, _f(row.get(field))) * weight
    return mass, exposure


def build_hierarchical_priors(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Empirical-Bayes league->position->role(if factual)->team->player priors.

    These are upstream priors only. Existing P1.3 remains final posterior owner.
    """
    specs = {
        "xg90": ("xg", "opponent_strength_weight", 8.0, 5.0, 5.0),
        "xa90": ("xa", "opponent_strength_weight", 10.0, 6.0, 6.0),
        "saves90": ("saves", "opponent_attack_weight", 6.0, 4.0, 4.0),
        "defcon90": ("defensive", "opponent_attack_weight", 7.0, 5.0, 5.0),
    }
    clean = [dict(row) for row in rows]
    by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_team: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in clean:
        pid = _i(row.get("player_id"), _i(row.get("element")))
        if pid <= 0:
            continue
        by_player[pid].append(row)
        by_position[_position(row.get("position"))].append(row)
        by_team[_i(row.get("team_id"))].append(row)
        role = str(row.get("actual_role") or "").strip().upper()
        if role:
            by_role[role].append(row)

    players: dict[str, Any] = {}
    league_sufficient_cache: dict[tuple[str, str], tuple[float, float]] = {}
    position_sufficient_cache: dict[
        tuple[str, str, str], tuple[float, float]
    ] = {}
    for pid, history in by_player.items():
        latest = max(
            history,
            key=lambda row: (_i(row.get("gw")), str(row.get("match_id") or "")),
        )
        position = _position(latest.get("position"))
        team_id = _i(latest.get("team_id"))
        role = str(latest.get("actual_role") or "").strip().upper() or None
        bundle = {
            "position": position,
            "team_id": team_id,
            "actual_role": role,
            "role_layer_used": bool(role),
            "variables": {},
        }
        for name, (field, weight, pos_k, role_k, team_k) in specs.items():
            league_key = (field, weight)
            if league_key not in league_sufficient_cache:
                league_sufficient_cache[league_key] = _sufficient(
                    clean, field, weight
                )
            league_mass, league_exp = league_sufficient_cache[league_key]
            league_rate = (
                league_mass / league_exp if league_exp > 0 else 0.0
            )
            position_key = (position, field, weight)
            if position_key not in position_sufficient_cache:
                position_sufficient_cache[position_key] = _sufficient(
                    by_position.get(position, []), field, weight
                )
            pos_mass, pos_exp = position_sufficient_cache[position_key]
            pos_rate = (
                pos_mass + league_rate * pos_k
            ) / max(1e-9, pos_exp + pos_k)

            team_loo = [
                row
                for row in by_team.get(team_id, [])
                if _i(row.get("player_id"), _i(row.get("element"))) != pid
            ]
            team_mass, team_exp = _sufficient(team_loo, field, weight)
            team_rate = (
                team_mass + pos_rate * team_k
            ) / max(1e-9, team_exp + team_k)

            prior = team_rate
            source = "LEAGUE_POSITION_TEAM_EMPIRICAL_BAYES"
            role_exp = 0.0
            if role and by_role.get(role):
                role_loo = [
                    row
                    for row in by_role[role]
                    if _i(row.get("player_id"), _i(row.get("element"))) != pid
                ]
                role_mass, role_exp = _sufficient(role_loo, field, weight)
                prior = (
                    role_mass + team_rate * role_k
                ) / max(1e-9, role_exp + role_k)
                source = "LEAGUE_POSITION_TEAM_ROLE_EMPIRICAL_BAYES"

            kappa = 5.0 if name == "xg90" else 6.0
            bundle["variables"][name] = {
                "prior_rate90": round(max(0.0, prior), 6),
                "credible_interval90": _gamma_interval(
                    max(1e-6, prior * kappa), kappa
                ),
                "prior_equivalent_matches": kappa,
                "prior_source": source,
                "league_rate90": round(max(0.0, league_rate), 6),
                "position_rate90": round(max(0.0, pos_rate), 6),
                "team_rate90_leave_one_player_out": round(
                    max(0.0, team_rate), 6
                ),
                "role_layer_used": bool(role),
                "role_evidence_exposure90": round(role_exp, 3),
                "sample_exposure_minutes": round(
                    sum(max(0.0, _f(row.get("minutes"))) for row in history),
                    1,
                ),
            }

        starts = sum(bool(row.get("starter")) for row in history)
        n = len(history)
        alpha, beta = 2.5 + starts, 1.5 + n - starts
        mean = alpha / (alpha + beta)
        variance = (
            alpha * beta
            / ((alpha + beta) ** 2 * (alpha + beta + 1.0))
        )
        half = Z90 * math.sqrt(max(0.0, variance))
        bundle["start_probability"] = round(mean, 6)
        bundle["start_probability_credible_interval90"] = [
            round(_clamp(mean - half, 0.0, 1.0), 6),
            round(_clamp(mean + half, 0.0, 1.0), 6),
        ]
        bundle["start_prior"] = {
            "alpha0": 2.5,
            "beta0": 1.5,
            "sample_matches": n,
        }
        players[str(pid)] = bundle

    return {
        "model": "V12_STAGE1_HIERARCHICAL_PRIOR_UTILITY_V1",
        "players": players,
        "hierarchy": [
            "league",
            "position",
            "role_if_factual",
            "team_leave_one_player_out",
            "player_owner_posterior",
        ],
        "different_prior_strengths_by_variable": True,
        "final_player_posterior_owner": "V12_PLAYER_EVENTS",
        "role_fabricated_from_position": False,
    }


def distribution_selection_matrix(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    specs = {
        "starter": ("binary", "starter"),
        "goals": ("count", "goals"),
        "assists": ("count", "assists"),
        "saves": ("count", "saves"),
        "bonus": ("count", "bonus"),
        "defensive": ("count", "defensive"),
        "xg": ("continuous_nonnegative", "xg"),
        "xa": ("continuous_nonnegative", "xa"),
        "xgi": ("continuous_nonnegative", "xgi"),
    }
    matrix = []
    positions = sorted(
        {
            _position(row.get("position"))
            for row in rows
            if _position(row.get("position")) in {"GK", "DEF", "MID", "FWD"}
        }
    )
    for position in positions:
        subset = [
            row for row in rows if _position(row.get("position")) == position
        ]
        for target, (kind, field) in specs.items():
            values = []
            exposure = 0.0
            for row in subset:
                value = row.get(field)
                if value is None:
                    continue
                values.append(
                    1.0 if kind == "binary" and bool(value) else _f(value)
                )
                exposure += max(0.0, _f(row.get("minutes")))
            if not values:
                matrix.append(
                    {
                        "position": position,
                        "target": target,
                        "status": "UNAVAILABLE",
                        "sample_size": 0,
                    }
                )
                continue
            n = len(values)
            mean = sum(values) / n
            variance = sum((x - mean) ** 2 for x in values) / max(1, n - 1)
            zero_rate = sum(x == 0 for x in values) / n
            if kind == "binary":
                selected = (
                    "BETA_BINOMIAL"
                    if n >= 4
                    else "BERNOULLI_WITH_HIERARCHICAL_PRIOR"
                )
                candidates = ["BERNOULLI", "BETA_BINOMIAL"]
                reason = "binary target"
            elif kind == "count":
                dispersion = variance / max(mean, 1e-9)
                zero_excess = zero_rate - math.exp(-mean)
                if n >= 8 and zero_excess > 0.15:
                    selected = "ZINB" if dispersion > 1.25 else "ZIP"
                elif dispersion > 1.25:
                    selected = "NEGATIVE_BINOMIAL"
                else:
                    selected = "POISSON"
                candidates = [
                    "POISSON",
                    "NEGATIVE_BINOMIAL",
                    "ZIP",
                    "ZINB",
                    "HURDLE",
                ]
                reason = (
                    f"variance_mean_ratio={dispersion:.3f}; "
                    f"zero_excess={zero_excess:.3f}"
                )
            else:
                selected = "HURDLE_GAMMA" if zero_rate >= 0.4 else "GAMMA"
                candidates = ["GAMMA", "HURDLE_GAMMA", "EMPIRICAL_SHRUNK"]
                reason = (
                    "nonnegative continuous target; Erlang rejected without "
                    "time-to-k-event semantics"
                )
            matrix.append(
                {
                    "position": position,
                    "target": target,
                    "kind": kind,
                    "sample_size": n,
                    "mean": round(mean, 6),
                    "variance": round(variance, 6),
                    "zero_rate": round(zero_rate, 6),
                    "exposure_minutes": round(exposure, 1),
                    "overdispersion_ratio": (
                        None if mean <= 0 else round(variance / mean, 6)
                    ),
                    "candidates": candidates,
                    "selected": selected,
                    "selection_reason": reason,
                    "erlang_selected": False,
                    "status": "AVAILABLE",
                }
            )
    return {
        "matrix": matrix,
        "selection_is_data_driven": True,
        "one_distribution_for_all_targets_forbidden": True,
        "erlang_generic_football_model_forbidden": True,
    }


def regime_change_evidence(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    data = [dict(row) for row in rows]
    n = len(data)
    if n < 4:
        return {
            "method": "BETA_BINOMIAL_BAYES_FACTOR_REGIME",
            "sample_size": n,
            "p_change": 0.0,
            "p_role_stable": 1.0,
            "change_after_match_index": None,
            "old_regime_weight": 1.0,
            "history_hard_reset": False,
            "status": "LOW_SAMPLE_NO_RESET",
        }

    def log_marginal(bits: Sequence[int]) -> float:
        a = b = 2.0
        successes = sum(bits)
        failures = len(bits) - successes
        return (
            math.lgamma(a + successes)
            + math.lgamma(b + failures)
            - math.lgamma(a + b + len(bits))
            - math.lgamma(a)
            - math.lgamma(b)
            + math.lgamma(a + b)
        )

    starters = [1 if row.get("starter") else 0 for row in data]
    null = log_marginal(starters)
    best = (-1e9, None)
    for split in range(2, n - 1):
        score = (
            log_marginal(starters[:split])
            + log_marginal(starters[split:])
            - null
        )
        left = [
            str(row.get("actual_role") or "").strip().upper()
            for row in data[:split]
            if str(row.get("actual_role") or "").strip()
        ]
        right = [
            str(row.get("actual_role") or "").strip().upper()
            for row in data[split:]
            if str(row.get("actual_role") or "").strip()
        ]
        if left and right:
            if Counter(left).most_common(1)[0][0] != Counter(right).most_common(1)[0][0]:
                score += math.log(3.0)
        if score > best[0]:
            best = (score, split)
    log_bf, split = best
    prior = 0.20
    log_odds = math.log(prior / (1.0 - prior)) + log_bf
    p_change = 1.0 / (1.0 + math.exp(-_clamp(log_odds, -30.0, 30.0)))
    return {
        "method": "BETA_BINOMIAL_BAYES_FACTOR_REGIME",
        "sample_size": n,
        "log_bayes_factor": round(log_bf, 6),
        "p_change": round(p_change, 6),
        "p_role_stable": round(1.0 - p_change, 6),
        "change_after_match_index": split,
        "old_regime_weight": round(max(0.15, 1.0 - p_change), 6),
        "history_hard_reset": False,
        "status": "AVAILABLE",
    }


def walk_forward_validate(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    clean = [dict(row) for row in rows if _i(row.get("gw")) > 0]
    gws = sorted({_i(row.get("gw")) for row in clean})
    rows_by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    rows_by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    position_history_cache: dict[
        tuple[int, str], tuple[dict[str, Any], ...]
    ] = {}
    position_rate_cache: dict[
        tuple[int, str, str, str], float
    ] = {}
    position_start_cache: dict[tuple[int, str], float] = {}
    for row in clean:
        pid = _i(row.get("player_id"), _i(row.get("element")))
        rows_by_player[pid].append(row)
        rows_by_position[_position(row.get("position"))].append(row)
    errors: dict[str, list[float]] = defaultdict(list)
    brier: dict[str, list[float]] = defaultdict(list)
    logloss: dict[str, list[float]] = defaultdict(list)
    folds = 0
    for target_gw in gws:
        train = [row for row in clean if _i(row.get("gw")) < target_gw]
        test = [row for row in clean if _i(row.get("gw")) == target_gw]
        if not train or not test:
            continue
        folds += 1
        for actual in test:
            pid = _i(actual.get("player_id"), _i(actual.get("element")))
            position = _position(actual.get("position"))
            player_train = [
                row
                for row in rows_by_player.get(pid, [])
                if _i(row.get("gw")) < target_gw
            ]
            position_history_key = (target_gw, position)
            if position_history_key not in position_history_cache:
                position_history_cache[position_history_key] = tuple(
                    row
                    for row in rows_by_position.get(position, [])
                    if _i(row.get("gw")) < target_gw
                )
            position_train = position_history_cache[position_history_key]
            if not player_train or not position_train:
                continue
            position_rate_key = (
                target_gw,
                position,
                "xgi",
                "weights=None",
            )
            if position_rate_key not in position_rate_cache:
                position_rate_cache[position_rate_key] = (
                    _rate90(position_train, "xgi") or 0.0
                )
            pos_rate = position_rate_cache[position_rate_key]
            season = _rate90(player_train, "xgi")
            season = pos_rate if season is None else season
            recency_weights = [
                0.5 ** (max(0, target_gw - _i(row.get("gw"))) / 2.5)
                for row in player_train
            ]
            recency = _rate90(
                player_train, "xgi", weights=recency_weights
            )
            recency = season if recency is None else recency
            opponent_weights = [
                weight
                * _clamp(
                    _f(row.get("opponent_strength_weight"), 1.0),
                    0.5,
                    1.5,
                )
                for row, weight in zip(player_train, recency_weights)
            ]
            opponent = _rate90(
                player_train, "xgi", weights=opponent_weights
            )
            opponent = recency if opponent is None else opponent
            effective = sum(opponent_weights)
            bayes = (
                opponent * effective + pos_rate * 4.0
            ) / max(1e-9, effective + 4.0)
            minutes = max(0.0, _f(actual.get("minutes")))
            if minutes > 0:
                observed = (
                    90.0 * max(0.0, _f(actual.get("xgi"))) / minutes
                )
                for label, prediction in {
                    "naive_position": pos_rate,
                    "season_aggregate": season,
                    "recency": recency,
                    "opponent_adjusted": opponent,
                    "bayesian_opponent_adjusted": bayes,
                }.items():
                    errors[label].append(abs(prediction - observed))

            if position_history_key not in position_start_cache:
                position_start_cache[position_history_key] = (
                    2.0
                    + sum(bool(row.get("starter")) for row in position_train)
                ) / (4.0 + len(position_train))
            pos_start = position_start_cache[position_history_key]
            season_start = (
                2.0 + sum(bool(row.get("starter")) for row in player_train)
            ) / (4.0 + len(player_train))
            recent = player_train[-min(4, len(player_train)) :]
            recent_start = (
                1.5 + sum(bool(row.get("starter")) for row in recent)
            ) / (3.0 + len(recent))
            bayes_start = (
                pos_start * 4.0 + recent_start * len(recent)
            ) / (4.0 + len(recent))
            y = 1.0 if actual.get("starter") else 0.0
            for label, prediction in {
                "naive_position": pos_start,
                "season_aggregate": season_start,
                "recency": recent_start,
                "bayesian_opponent_adjusted": bayes_start,
            }.items():
                p = _clamp(prediction, 1e-6, 1.0 - 1e-6)
                brier[label].append((p - y) ** 2)
                logloss[label].append(
                    -(y * math.log(p) + (1 - y) * math.log(1 - p))
                )

    def average(mapping: Mapping[str, Sequence[float]]) -> dict[str, float | None]:
        return {
            key: round(sum(values) / len(values), 6) if values else None
            for key, values in mapping.items()
        }

    xgi_mae = average(errors)
    starter_brier = average(brier)
    starter_logloss = average(logloss)
    valid_xgi = {k: v for k, v in xgi_mae.items() if v is not None}
    valid_start = {k: v for k, v in starter_brier.items() if v is not None}
    return {
        "status": "PASS" if folds > 0 and valid_start else "INSUFFICIENT_COMPLETED_FOLDS",
        "folds": folds,
        "future_leakage": False,
        "split": "EXPANDING_WINDOW_BY_GW",
        "xgi_mae": xgi_mae,
        "starter_brier": starter_brier,
        "starter_log_loss": starter_logloss,
        "xgi_selected_variant": min(valid_xgi, key=valid_xgi.get) if valid_xgi else None,
        "starter_selected_variant": min(valid_start, key=valid_start.get) if valid_start else None,
        "complex_model_survives_only_if_metric_improves": True,
    }


def walk_forward_pstart_validate(
    rows: Sequence[Mapping[str, Any]],
    *,
    neutral_prior: float = 0.72,
    deadlines_by_gw: Mapping[int | str, str] | None = None,
    min_sample_size: int = 200,
    min_position_sample_size: int = 25,
    expected_player_count: int | None = None,
) -> dict[str, Any]:
    """Evidence-only, paired P(start) walk-forward against canonical V12 owner.

    GW N consumes only outcomes from lower GWs. That numerical split alone
    does not prove source-as-of availability: archived finalized_at provenance
    must precede the real GW-N deadline for a promoted calibration verdict.
    Neither predictions nor the configured V12_PLAYER_MINUTES weights are
    mutated by this diagnostic.
    """
    from datetime import datetime

    def aware(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        return out if out.tzinfo is not None else None

    clean: list[dict[str, Any]] = []
    rejected = Counter()
    unique = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            rejected["NON_MAPPING"] += 1
            continue
        row = dict(raw)
        pid = _i(row.get("player_id"), _i(row.get("element")))
        gw = _i(row.get("gw"))
        fixture = _i(row.get("match_id"), _i(row.get("fixture")))
        status = str(row.get("official_status") or row.get("status") or "FINAL").upper()
        if pid <= 0 or gw <= 0 or fixture <= 0:
            rejected["UNVERIFIED_IDENTITY_OR_GW"] += 1
            continue
        if status not in {"FINAL", "DNP", "BLANK"}:
            rejected["NONFINAL_OUTCOME"] += 1
            continue
        if not isinstance(row.get("starter"), bool):
            rejected["STARTER_NOT_BOOLEAN"] += 1
            continue
        minutes = _f(row.get("minutes_played"), _f(row.get("minutes"), -1))
        if minutes < 0 or minutes > 130 or (row["starter"] and minutes <= 0):
            rejected["INVALID_MINUTES"] += 1
            continue
        key = (pid, gw, fixture)
        if key in unique:
            rejected["DUPLICATE_PLAYER_FIXTURE"] += 1
            continue
        unique.add(key)
        row["player_id"] = pid
        row["gw"] = gw
        row["match_id"] = fixture
        row["minutes"] = minutes
        clean.append(row)

    by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in clean:
        by_player[row["player_id"]].append(row)
    for player_rows in by_player.values():
        player_rows.sort(key=lambda x: (x["gw"], x["match_id"]))
    gws = sorted({row["gw"] for row in clean})
    buckets = {
        label: defaultdict(list)
        for label in ("baseline", "individualized")
    }
    by_position: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    by_team: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    reliability: dict[str, list[tuple[float, int]]] = {"baseline": [], "individualized": []}
    candidate_test = 0
    no_prior_history = 0
    chronology_errors = 0
    provenance_gaps = 0
    folds_with_predictions = set()
    for gw in gws:
        test = [row for row in clean if row["gw"] == gw]
        if gw == gws[0]:
            continue
        target_deadline = aware(
            (deadlines_by_gw or {}).get(gw)
            or (deadlines_by_gw or {}).get(str(gw))
        )
        for actual in test:
            candidate_test += 1
            history = [row for row in by_player[actual["player_id"]] if row["gw"] < gw]
            if not history:
                no_prior_history += 1
                continue
            if any(row["gw"] >= gw for row in history):
                chronology_errors += 1
                continue
            # Strictly verify source availability at the target deadline; a
            # retrospective refresh timestamp is NOT an archived predeadline
            # snapshot. Missing proof remains a blocker to calibration PASS.
            for past in history:
                final_at = aware(past.get("finalized_at"))
                if not target_deadline or not final_at:
                    provenance_gaps += 1
                elif final_at > target_deadline:
                    chronology_errors += 1
            evidence = build_player_selection_evidence(
                {"id": actual["player_id"]}, history, neutral_prior=neutral_prior
            )
            if evidence.get("status") != "AVAILABLE":
                continue
            player = {
                "id": actual["player_id"], "starts": evidence["starts"],
                "minutes": evidence["minutes"], "status": "a",
                "chance_of_playing_next_round": 100,
            }
            context = {"team_matches_played": evidence["observed_matches"]}
            predictions = {
                "baseline": estimate_player_minutes(player, context),
                "individualized": estimate_player_minutes(
                    player, {**context, "selection_evidence": evidence}
                ),
            }
            y_start = int(actual["starter"])
            y_minutes = actual["minutes"]
            y_dnp = int(y_minutes == 0)
            y_cameo = int(not y_start and y_minutes > 0)
            pos = _position(actual.get("position")) or "UNKNOWN"
            team = str(actual.get("team_id") or "UNKNOWN")
            folds_with_predictions.add(gw)
            for label, prediction in predictions.items():
                p = _clamp(_f(prediction.get("start_probability")), 1e-6, 1 - 1e-6)
                pd = _clamp(_f(prediction.get("dnp_probability")), 0, 1)
                pc = _clamp(_f(prediction.get("cameo_probability")), 0, 1)
                part = (prediction.get("derived_probabilities") or {})
                if abs(p + _f(part.get("p_regular_cameo")) + _f(part.get("p_late_cameo")) + pd - 1) > 0.002:
                    chronology_errors += 1
                scores = {
                    "brier": (p - y_start) ** 2,
                    "log_loss": -(y_start * math.log(p) + (1 - y_start) * math.log(1 - p)),
                    "xmins_mae": abs(_f(prediction.get("expected_minutes")) - y_minutes),
                    "dnp_brier": (pd - y_dnp) ** 2,
                    "cameo_brier": (pc - y_cameo) ** 2,
                }
                for key, value in scores.items():
                    buckets[label][key].append(value)
                reliability[label].append((p, y_start))
                for metric, score in scores.items():
                    by_position[pos][f"{label}_{metric}"].append(score)
                    by_team[team][f"{label}_{metric}"].append(score)

    def avg(values: Sequence[float]) -> float | None:
        return round(sum(values) / len(values), 6) if values else None

    metrics = {
        label: {k: avg(v) for k, v in scores.items()}
        for label, scores in buckets.items()
    }
    bins: dict[str, list[dict[str, Any]]] = {}
    for label, entries in reliability.items():
        groups: dict[int, list[tuple[float, int]]] = defaultdict(list)
        for p, y in entries:
            groups[min(9, int(p * 10))].append((p, y))
        bins[label] = [{
            "range": f"{index / 10:.1f}-{(index + 1) / 10:.1f}",
            "n": len(group), "mean_predicted": avg([v[0] for v in group]),
            "observed_start_rate": avg([v[1] for v in group]),
        } for index, group in sorted(groups.items())]
    delta = {
        k: (
            None if metrics["baseline"].get(k) is None or metrics["individualized"].get(k) is None
            else round(metrics["individualized"][k] - metrics["baseline"][k], 6)
        ) for k in ("brier", "log_loss", "xmins_mae", "dnp_brier", "cameo_brier")
    }
    noninferior = bool(
        delta["brier"] is not None
        and delta["brier"] <= 0.01
        and delta["log_loss"] <= 0.02
        and delta["xmins_mae"] <= 1.0
        and delta["dnp_brier"] <= 0.02
        and delta["cameo_brier"] <= 0.02
    )
    sample_count = len(reliability["individualized"])
    pos_summary = {
        key: {**{k: avg(v) for k, v in bundle.items()},
              "n": len(bundle.get("individualized_brier") or [])}
        for key, bundle in by_position.items()
    }
    expected = expected_player_count if expected_player_count and expected_player_count > 0 else None
    observed_players = len(by_player)
    universe_ratio = (round(observed_players / expected, 6) if expected else None)
    enough_universe = bool(universe_ratio is not None and universe_ratio >= 0.95)
    position_regressions = {
        position: round(
            (pos_summary.get(position, {}).get("individualized_brier") or 0)
            - (pos_summary.get(position, {}).get("baseline_brier") or 0),
            6,
        )
        for position in ("GK", "DEF", "MID", "FWD")
        if pos_summary.get(position, {}).get("n", 0) >= min_position_sample_size
    }
    positional_noninferior = bool(
        len(position_regressions) == 4
        and all(value <= 0.03 for value in position_regressions.values())
    )
    enough_samples = bool(
        sample_count >= min_sample_size
        and enough_universe
        and all(pos_summary.get(p, {}).get("n", 0) >= min_position_sample_size
                for p in ("GK", "DEF", "MID", "FWD"))
    )
    noninferior = bool(noninferior and positional_noninferior)
    gw_temporal_only = chronology_errors == 0
    source_temporal = gw_temporal_only and provenance_gaps == 0 and bool(deadlines_by_gw)
    if not sample_count:
        status = "INSUFFICIENT_COMPLETED_FOLDS"
    elif not source_temporal:
        status = "RETROSPECTIVE_DIAGNOSTIC_ONLY"
    elif not enough_samples:
        status = "INSUFFICIENT_POSITION_SAMPLES"
    elif not noninferior:
        status = "REGRESSION_BLOCKED"
    else:
        status = "PASS"
    return {
        "status": status,
        "folds": len(folds_with_predictions),
        "target_gws": sorted(folds_with_predictions),
        "samples": sample_count,
        "tested_fixture_rows": candidate_test,
        "no_prior_history": no_prior_history,
        "unique_players_tested": observed_players,
        "expected_player_count": expected,
        "source_player_coverage_ratio": universe_ratio,
        "source_universe_coverage": "PASS" if enough_universe else "PARTIAL_OR_UNVERIFIED",
        "position_brier_deltas": position_regressions,
        "position_noninferiority": "PASS" if positional_noninferior else "FAIL_OR_INSUFFICIENT",

        "rejected_rows": dict(rejected),
        "future_leakage": chronology_errors > 0,
        "gw_split_integrity": "PASS" if gw_temporal_only else "FAIL",
        "predeadline_source_lineage": "PASS" if source_temporal else "UNVERIFIED",
        # Absence of independently archived source finalization must remain
        # explicit; report READY_FULL is not a calibration promotion gate.
        "historical_asof_status": (
            "PASS" if source_temporal else "HISTORICAL_AS_OF_UNAVAILABLE"
        ),
        "missing_predeadline_source_proofs": provenance_gaps,
        "split": "EXPANDING_WINDOW_BY_GW_STRICTLY_PRE_DEADLINE",
        "split_precision": "GW_ORDER_ONLY_WITHOUT_ARCHIVED_FINALIZATION_TIMESTAMPS" if not source_temporal else "AS_OF_ARCHIVED",
        "baseline": metrics["baseline"],
        "individualized": metrics["individualized"],
        "delta_individualized_minus_baseline": delta,
        "noninferiority": "PASS" if noninferior else "FAIL_OR_INSUFFICIENT",
        "minimum_sample_satisfied": enough_samples,
        "reliability_bins": bins,
        "by_position": pos_summary,
        "by_team": {k: {metric: avg(v) for metric, v in b.items()} for k, b in by_team.items()},
        "promotion_rule": "PASS_ONLY_WITH_PREDEADLINE_SOURCE_LINEAGE_POSITION_COVERAGE_AND_NONINFERIORITY",
        "automatic_parameter_retuning": False,
        "mathematical_owner": "V12_PLAYER_MINUTES",
    }



def probabilistic_tactical_states(
    bootstrap: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    dimensions = (
        "coach",
        "nominal_formation",
        "in_possession_shape",
        "out_of_possession_shape",
        "press_block",
        "width",
        "transition",
        "build_up",
        "set_piece_style",
        "substitution_tendencies",
    )
    teams = {
        str(_i(team.get("id"))): {
            name: {
                "state": "UNAVAILABLE",
                "probabilities": {"UNKNOWN": 1.0},
            }
            for name in dimensions
        }
        for team in bootstrap.get("teams") or []
        if _i(team.get("id")) > 0
    }
    histories: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        histories[_i(row.get("player_id"), _i(row.get("element")))].append(row)
    players = {}
    for pid, history in histories.items():
        roles = [
            str(row.get("actual_role") or "").strip().upper()
            for row in history[-4:]
            if str(row.get("actual_role") or "").strip()
        ]
        if roles:
            counts = Counter(roles)
            total = sum(counts.values())
            probabilities = {
                role: round(count / total, 6)
                for role, count in counts.items()
            }
            state = "OBSERVED_DISTRIBUTION"
        else:
            probabilities = {"UNKNOWN": 1.0}
            state = "UNAVAILABLE"
        players[str(pid)] = {
            "actual_role": {
                "state": state,
                "probabilities": probabilities,
            },
            "fpl_position_used_as_role_proof": False,
        }
    return {
        "teams": teams,
        "players": players,
        "formation_is_not_deterministic": True,
        "unknown_state_is_explicit_not_neutral_fact": True,
    }


def build_canonical_universe(
    projections: Mapping[str, Any],
) -> dict[str, Any]:
    """Build exact 20/25/30/25 score from existing owner outputs only."""
    rows = []
    for player in projections.get("players") or []:
        if not isinstance(player, Mapping):
            continue
        position = _position(player.get("position"))
        if position not in {"GK", "DEF", "MID", "FWD"}:
            continue
        rates = dict(player.get("posterior_rates") or {})
        goal, assist = dict(rates.get("goal") or {}), dict(rates.get("assist") or {})
        saves, dc = dict(rates.get("saves") or {}), dict(rates.get("defcon") or {})
        historical = (
            GOAL_POINTS[position] * _f(goal.get("prior"))
            + 3.0 * _f(assist.get("prior"))
        )
        current = (
            GOAL_POINTS[position] * _f(goal.get("posterior_rate90"))
            + 3.0 * _f(assist.get("posterior_rate90"))
        )
        if position == "GK":
            historical += _f(saves.get("prior")) / 3.0
            current += _f(saves.get("posterior_rate90")) / 3.0
        elif position in {"DEF", "MID"}:
            historical += _f(dc.get("prior_expected_points90"))
            current += _f(dc.get("expected_points90"))

        tactical = (
            dict(player.get("tactical_role_component") or {}).get(
                "canonical_tactical_role_score"
            )
        )
        horizons = dict(player.get("horizons") or {})
        future = []
        horizon_lineage: dict[str, Any] = {}
        for horizon, weight in ((1, 0.45), (3, 0.30), (5, 0.25)):
            data = dict(horizons.get(str(horizon)) or {})
            distribution = dict(data.get("point_distribution") or {})
            horizon_lineage[str(horizon)] = {
                "mean": data.get("mean"),
                "distribution_status": distribution.get("status"),
                "distribution_model": distribution.get("model"),
                "sum_probability": distribution.get("sum_probability"),
            }
            if data.get("mean") is None:
                future = []
                break
            future.append(weight * _f(data.get("mean")) / horizon)
        fixture = sum(future) if future else None

        xmins = dict(player.get("xmins") or {})
        position_engine = dict(player.get("position_engine") or {})
        matchup_vector = dict(
            position_engine.get("matchup_vector")
            or player.get("dynamic_matchup_vector")
            or {}
        )
        p1_1_present = bool(
            xmins
            and (
                xmins.get("expected_minutes") is not None
                or xmins.get("xmins_distribution")
            )
        )
        posterior_present = bool(rates and goal and assist)
        position_engine_present = bool(
            position_engine and matchup_vector.get("vector")
        )
        horizon_distributions_complete = all(
            (horizon_lineage.get(str(horizon)) or {}).get(
                "distribution_status"
            )
            == "READY_COMPLETE_CONDITIONAL_PMF"
            for horizon in (1, 3, 5)
        )
        stage2_lineage = {
            "contract": "V12_CANONICAL_STAGE2_SINGLE_CHAIN_V1",
            "same_projection_row": True,
            "snapshot_lineage": "SAME_GOVERNED_PROJECTION_SNAPSHOT",
            "p1_1": {
                "owner": "V12_PLAYER_MINUTES",
                "present": p1_1_present,
                "xMins": xmins.get("expected_minutes"),
                "Pstart": xmins.get("start_probability"),
                "P60": xmins.get("p_60_plus"),
            },
            "posterior": {
                "owner": "V12_PLAYER_EVENTS",
                "present": posterior_present,
                "goal_rate90": goal.get("posterior_rate90"),
                "assist_rate90": assist.get("posterior_rate90"),
            },
            "position_engine": {
                "owner": "V12_PLAYER_EVENTS",
                "present": position_engine_present,
                "model": position_engine.get("model"),
                "matchup_model": matchup_vector.get("model"),
            },
            "horizons": horizon_lineage,
            "horizon_distributions_complete": horizon_distributions_complete,
            "lineage_complete": bool(
                p1_1_present
                and posterior_present
                and position_engine_present
                and horizon_distributions_complete
            ),
            "duplicate_model_created": False,
        }
        rows.append(
            {
                "element_id": _i(player.get("element")),
                "element": _i(player.get("element")),
                "name": player.get("name"),
                "position": position,
                "team_id": _i(player.get("team_id")),
                "now_cost": _i(player.get("now_cost")),
                "status": player.get("status"),
                "eligible": str(player.get("status") or "a") != "u",
                "_historical": historical,
                "_current": current,
                "_tactical": None if tactical is None else _f(tactical),
                "_fixture": fixture,
                "stage2_lineage": stage2_lineage,
            }
        )

    complete_rows = []
    for position in ("GK", "DEF", "MID", "FWD"):
        pool = [
            row for row in rows
            if row["position"] == position and row["eligible"]
        ]
        hvals = [row["_historical"] for row in pool]
        cvals = [row["_current"] for row in pool]
        fvals = [row["_fixture"] for row in pool if row["_fixture"] is not None]
        for row in pool:
            complete = (
                row["_tactical"] is not None
                and row["_fixture"] is not None
            )
            row["canonical_evaluation_complete"] = complete
            if not complete:
                continue
            components = {
                "PROVEN_HISTORICAL": round(_midrank(row["_historical"], hvals), 6),
                "TACTICAL_ROLE": round(_clamp(row["_tactical"], 0.0, 100.0), 6),
                "CURRENT_UNDERLYING": round(_midrank(row["_current"], cvals), 6),
                "FIXTURE_SECURITY": round(_midrank(row["_fixture"], fvals), 6),
            }
            row["canonical_components"] = components
            row["football_score"] = round(
                0.20 * components["PROVEN_HISTORICAL"]
                + 0.25 * components["TACTICAL_ROLE"]
                + 0.30 * components["CURRENT_UNDERLYING"]
                + 0.25 * components["FIXTURE_SECURITY"],
                6,
            )
            row["anti_double_count"] = {
                "historical_uses_owner_prior_rates": True,
                "current_uses_owner_posterior_rates": True,
                "tactical_uses_p1_6_owner_score": True,
                "fixture_security_uses_p1_3_xpts": True,
                "p1_1_security_not_reapplied": True,
            }
            complete_rows.append(row)

    for position in ("GK", "DEF", "MID", "FWD"):
        ranked = sorted(
            [row for row in complete_rows if row["position"] == position],
            key=lambda row: (-_f(row.get("football_score")), _i(row.get("element_id"))),
        )
        for rank, row in enumerate(ranked, 1):
            row["canonical_rank"] = rank

    for row in rows:
        for key in ("_historical", "_current", "_tactical", "_fixture"):
            row.pop(key, None)
    counts = {
        position: sum(
            1 for row in complete_rows if row["position"] == position
        )
        for position in ("GK", "DEF", "MID", "FWD")
    }
    return {
        "status": (
            "COMPLETE"
            if all(counts[position] >= 5 for position in counts)
            else "PARTIAL"
        ),
        "players": rows,
        "complete_players": len(complete_rows),
        "stage2_lineage_contract": "V12_CANONICAL_STAGE2_SINGLE_CHAIN_V1",
        "stage2_lineage_complete_players": sum(
            1
            for row in complete_rows
            if (row.get("stage2_lineage") or {}).get("lineage_complete")
            is True
        ),
        "position_counts": counts,
        "weights": {
            "PROVEN_HISTORICAL": 0.20,
            "TACTICAL_ROLE": 0.25,
            "CURRENT_UNDERLYING": 0.30,
            "FIXTURE_SECURITY": 0.25,
        },
        "new_xpts_model_created": False,
        "new_xmins_model_created": False,
        "new_posterior_created": False,
        "new_fdr_created": False,
    }
