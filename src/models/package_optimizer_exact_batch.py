from __future__ import annotations

from typing import Any

import numpy as np

from src.models.package_optimizer_v2 import PARSED_FORMATIONS, POSITIONS, _f, _scoring_context, load_config


class ExactBatchScorer:
    """Vectorized accelerator for canonical package scoring semantics.

    This is not an independent scoring authority. It consumes the same governed
    scoring context and is accepted for exhaustive traversal only behind
    differential tests against ``score_package`` / ``CompiledPackageScorer``.
    The public decision surface is rehydrated by the canonical scalar scorer.
    """

    def __init__(
        self,
        universe: list[dict[str, Any]],
        planning_gw: int,
        *,
        scoring_context: dict[str, Any] | None = None,
    ) -> None:
        self.planning_gw = int(planning_gw)
        self.context = scoring_context or _scoring_context(load_config(), self.planning_gw)
        self.max_horizon = int(self.context["max_horizon"])
        self.elements: list[int] = []
        self.element_to_index: dict[int, int] = {}
        positions: list[int] = []
        teams: list[int] = []
        means: list[list[float]] = []
        variances: list[list[float]] = []
        position_code = {position: index for index, position in enumerate(POSITIONS)}

        for player in universe:
            element = int(player.get("element") or -1)
            position = str(player.get("position") or "")
            if element <= 0 or position not in position_code:
                continue
            by_gw = {
                int(row.get("gw") or -1): row
                for row in (player.get("xpts_by_gw") or [])
            }
            row_means: list[float] = []
            row_vars: list[float] = []
            for offset in range(self.max_horizon):
                row = by_gw.get(self.planning_gw + offset, {})
                mean = _f(row.get("mean"))
                std = _f(row.get("std"))
                row_means.append(mean)
                row_vars.append(std * std)
            self.element_to_index[element] = len(self.elements)
            self.elements.append(element)
            positions.append(position_code[position])
            teams.append(int(player.get("team_id") or -1))
            means.append(row_means)
            variances.append(row_vars)

        self.position_codes = np.asarray(positions, dtype=np.int8)
        self.team_ids = np.asarray(teams, dtype=np.int16)
        self.means = np.asarray(means, dtype=np.float64)
        self.variances = np.asarray(variances, dtype=np.float64)
        self.formations = tuple((int(d), int(m), int(f)) for _, (d, m, f) in PARSED_FORMATIONS)

    @staticmethod
    def _round3(values: np.ndarray) -> np.ndarray:
        # Use Python round() to preserve the scalar scorer's externally visible
        # decimal semantics rather than relying on NumPy's formatter details.
        return np.fromiter((round(float(value), 3) for value in values), dtype=np.float64, count=len(values))

    def _indices(self, candidate_ids: list[list[int]]) -> np.ndarray:
        flat: list[int] = []
        width = -1
        for row in candidate_ids:
            if width < 0:
                width = len(row)
            elif len(row) != width:
                raise ValueError("candidate rows must have equal width")
            for element in row:
                try:
                    flat.append(self.element_to_index[int(element)])
                except KeyError as exc:
                    raise KeyError(f"exact batch scorer missing element={element}") from exc
        if width <= 0:
            return np.empty((0, 0), dtype=np.int32)
        return np.asarray(flat, dtype=np.int32).reshape(len(candidate_ids), width)

    def score_ids_compact(self, candidate_ids: list[list[int]], *, changes: int) -> list[dict[str, Any]]:
        """Score equal-width legal squads and return decision-bearing numeric fields."""
        if not candidate_ids:
            return []
        if int(changes) > int(self.context["change_cap"]):
            return [{"valid": False, "reason": "early_season_change_cap_exceeded"} for _ in candidate_ids]

        indices = self._indices(candidate_ids)
        n, width = indices.shape
        if width != 15:
            raise ValueError(f"exact batch scorer requires 15-player squads, got width={width}")
        layout = self.position_codes[indices]
        if not np.all(layout == layout[0]):
            raise ValueError("batch candidate position layout must be constant")
        layout0 = layout[0]
        position_columns = {
            position: np.flatnonzero(layout0 == code)
            for code, position in enumerate(POSITIONS)
        }
        if any(len(position_columns[position]) == 0 for position in POSITIONS):
            raise ValueError("batch candidate layout is missing a position")

        means = self.means[indices]
        variances = self.variances[indices]
        total_mean = np.zeros(n, dtype=np.float64)
        total_var = np.zeros(n, dtype=np.float64)
        horizon_means: dict[int, np.ndarray] = {}
        horizon_stds: dict[int, np.ndarray] = {}
        bench_weight = float(self.context["bench_weight"])
        captain_weight = float(self.context["captain_weight"])

        for offset in range(self.max_horizon):
            prefix_mean: dict[str, np.ndarray] = {}
            prefix_var: dict[str, np.ndarray] = {}
            top_means: list[np.ndarray] = []
            top_vars: list[np.ndarray] = []
            top_cols: list[np.ndarray] = []

            for position in POSITIONS:
                cols = position_columns[position]
                pm = means[:, cols, offset]
                pv = variances[:, cols, offset]
                order = np.argsort(-pm, axis=1, kind="stable")
                sorted_mean = np.take_along_axis(pm, order, axis=1)
                sorted_var = np.take_along_axis(pv, order, axis=1)
                prefix_mean[position] = np.cumsum(sorted_mean, axis=1)
                prefix_var[position] = np.cumsum(sorted_var, axis=1)
                top_means.append(sorted_mean[:, 0])
                top_vars.append(sorted_var[:, 0])
                top_cols.append(cols[order[:, 0]])

            formation_means: list[np.ndarray] = []
            formation_vars: list[np.ndarray] = []
            for d, m, f in self.formations:
                formation_means.append(
                    prefix_mean["GK"][:, 0]
                    + prefix_mean["DEF"][:, d - 1]
                    + prefix_mean["MID"][:, m - 1]
                    + prefix_mean["FWD"][:, f - 1]
                )
                formation_vars.append(
                    prefix_var["GK"][:, 0]
                    + prefix_var["DEF"][:, d - 1]
                    + prefix_var["MID"][:, m - 1]
                    + prefix_var["FWD"][:, f - 1]
                )
            fm = np.stack(formation_means, axis=1)
            fv = np.stack(formation_vars, axis=1)
            best_formation = np.argmax(fm, axis=1)  # first maximum matches scalar strict-gt tie rule
            rows = np.arange(n)
            lineup_mean = fm[rows, best_formation]
            lineup_var = fv[rows, best_formation]

            all_mean = np.sum(means[:, :, offset], axis=1)
            all_var = np.sum(variances[:, :, offset], axis=1)
            bench_mean = all_mean - lineup_mean
            bench_var = all_var - lineup_var

            captain_means = np.stack(top_means, axis=1)
            captain_vars = np.stack(top_vars, axis=1)
            captain_cols = np.stack(top_cols, axis=1)
            max_captain_mean = np.max(captain_means, axis=1)
            tied = captain_means == max_captain_mean[:, None]
            sentinel = width + 1
            first_col = np.min(np.where(tied, captain_cols, sentinel), axis=1)
            chosen_position = np.argmax(tied & (captain_cols == first_col[:, None]), axis=1)
            captain_mean = captain_means[rows, chosen_position]
            captain_var = captain_vars[rows, chosen_position]

            total_mean += lineup_mean + bench_weight * bench_mean + captain_weight * captain_mean
            total_var += lineup_var + (bench_weight * bench_weight) * bench_var + (((1.0 + captain_weight) ** 2 - 1.0) * captain_var)

            elapsed = offset + 1
            if elapsed in self.context["horizon_set"]:
                horizon_means[elapsed] = self._round3(total_mean)
                horizon_stds[elapsed] = self._round3(np.sqrt(total_var))

        cfg = self.context["cfg"]
        cluster = cfg.get("team_cluster_penalty") or {}
        cluster_enabled = bool(cluster.get("enabled"))
        free = max(0, int(cluster.get("free_players_per_club") or 0))
        per_extra = max(0.0, _f(cluster.get("points_per_extra_player")))
        cluster_penalty = np.zeros(n, dtype=np.float64)
        if cluster_enabled and per_extra > 0.0:
            candidate_teams = self.team_ids[indices]
            valid_teams = sorted({int(x) for x in self.team_ids.tolist() if int(x) > 0})
            excess = np.zeros(n, dtype=np.int16)
            for team_id in valid_teams:
                count = np.sum(candidate_teams == team_id, axis=1)
                excess += np.maximum(0, count - free).astype(np.int16)
            cluster_penalty = excess.astype(np.float64) * per_extra

        horizons = [int(x) for x in self.context["horizons"]]
        weights = self.context["weights"]
        weight_sum = sum(float(weights.get(str(h), 0.0)) for h in horizons)
        if weight_sum <= 0:
            return [{"valid": False, "reason": "invalid_horizon_weight_sum"} for _ in candidate_ids]
        normalized = {h: float(weights.get(str(h), 0.0)) / weight_sum for h in horizons}
        change_penalty = int(changes) * float(self.context["change_penalty_points"])
        risk_aversion = float(self.context["risk_aversion"])

        out: list[dict[str, Any]] = []
        for row_index in range(n):
            horizon_rows = {
                str(h): {
                    "valid": True,
                    "mean": float(horizon_means[h][row_index]),
                    "std": float(horizon_stds[h][row_index]),
                }
                for h in horizons
            }
            objective_mean = sum(normalized[h] * horizon_rows[str(h)]["mean"] for h in horizons)
            objective_var = sum((normalized[h] ** 2) * (horizon_rows[str(h)]["std"] ** 2) for h in horizons)
            objective_std = objective_var ** 0.5
            robust = objective_mean - risk_aversion * objective_std - change_penalty - float(cluster_penalty[row_index])
            out.append({
                "valid": True,
                "horizons": horizon_rows,
                "objective_mean": round(objective_mean, 3),
                "objective_std": round(objective_std, 3),
                "change_penalty_points": round(change_penalty, 3),
                "team_cluster_penalty_points": round(float(cluster_penalty[row_index]), 3),
                "robust_score": round(robust, 3),
            })
        return out


def exact_skyline_indices(metrics: np.ndarray, *, eps: float = 1e-12) -> np.ndarray:
    """Return exact Pareto skyline indices for [max4, min changes, min std].

    Uses chunked NumPy comparisons to avoid Python-per-candidate dominance loops.
    It is representation-only and does not influence package scoring authority.
    """
    values = np.asarray(metrics, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 6:
        raise ValueError("skyline metrics must have shape (n, 6)")
    n = values.shape[0]
    if n <= 1:
        return np.arange(n, dtype=np.int32)

    active = np.arange(n, dtype=np.int32)
    # Small blocks bound peak memory while all comparisons remain exact.
    block = 512
    dominated = np.zeros(n, dtype=bool)
    for start in range(0, n, block):
        stop = min(n, start + block)
        target_idx = active[start:stop]
        if len(target_idx) == 0:
            continue
        target = values[target_idx]
        for source_start in range(0, n, block):
            source_stop = min(n, source_start + block)
            source_idx = active[source_start:source_stop]
            source = values[source_idx]

            no_worse = (
                np.all(source[:, None, :4] >= target[None, :, :4] - eps, axis=2)
                & (source[:, None, 4] <= target[None, :, 4])
                & (source[:, None, 5] <= target[None, :, 5] + eps)
            )
            strict = (
                np.any(source[:, None, :4] > target[None, :, :4] + eps, axis=2)
                | (source[:, None, 4] < target[None, :, 4])
                | (source[:, None, 5] < target[None, :, 5] - eps)
            )
            dominated[target_idx] |= np.any(no_worse & strict, axis=0)
            if np.all(dominated[target_idx]):
                break
    return np.flatnonzero(~dominated).astype(np.int32)
