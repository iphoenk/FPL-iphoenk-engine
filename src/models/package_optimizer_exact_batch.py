from __future__ import annotations

import math
from typing import Any

import numpy as np

from src.models.package_optimizer_v2 import (
    PARSED_FORMATIONS,
    POSITIONS,
    CompiledPackageScorer,
    _f,
    _scoring_context,
    load_config,
)


class ExactBatchScorer:
    """Guarded vectorized accelerator for canonical package scoring semantics.

    This class is never an independent scoring authority. Exact formation ties are
    resolved by the same stable ordering and first-max semantics as the canonical
    scorer. Only candidates close to a three-decimal floating publication boundary
    are re-scored by the canonical ``CompiledPackageScorer`` before exposure.
    """

    ROUND_BOUNDARY_SCALED_EPS = 1e-5
    FORMATION_MARGIN_EPS = 1e-9

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
        self.player_by_element: dict[int, dict[str, Any]] = {}
        positions: list[int] = []
        teams: list[int] = []
        means: list[list[float]] = []
        variances: list[list[float]] = []
        position_code = {position: index for index, position in enumerate(POSITIONS)}
        canonical_universe: list[dict[str, Any]] = []

        for player in universe:
            element = int(player.get("element") or -1)
            position = str(player.get("position") or "")
            if element <= 0 or position not in position_code:
                continue
            by_gw = {int(row.get("gw") or -1): row for row in (player.get("xpts_by_gw") or [])}
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
            self.player_by_element[element] = player
            canonical_universe.append(player)
            positions.append(position_code[position])
            teams.append(int(player.get("team_id") or -1))
            means.append(row_means)
            variances.append(row_vars)

        self.position_codes = np.asarray(positions, dtype=np.int8)
        self.team_ids = np.asarray(teams, dtype=np.int16)
        self.means = np.asarray(means, dtype=np.float64)
        self.variances = np.asarray(variances, dtype=np.float64)
        self.formations = tuple((int(d), int(m), int(f)) for _, (d, m, f) in PARSED_FORMATIONS)
        self.canonical = CompiledPackageScorer(canonical_universe, self.planning_gw, scoring_context=self.context)
        self.last_scalar_fallback_count = 0
        self.total_scalar_fallback_count = 0
        self.last_formation_tie_count = 0
        self.total_formation_tie_count = 0

    @staticmethod
    def _round3(values: np.ndarray) -> np.ndarray:
        return np.fromiter((round(float(value), 3) for value in values), dtype=np.float64, count=len(values))

    @classmethod
    def _near_round_boundary(cls, values: np.ndarray) -> np.ndarray:
        scaled = np.asarray(values, dtype=np.float64) * 1000.0
        fractional = scaled - np.floor(scaled)
        return np.abs(fractional - 0.5) <= cls.ROUND_BOUNDARY_SCALED_EPS

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

    @staticmethod
    def _ordered_sum(values: np.ndarray, columns: list[np.ndarray], rows: np.ndarray) -> np.ndarray:
        total = np.zeros(len(rows), dtype=np.float64)
        for column in columns:
            total = total + values[rows, column]
        return total

    @staticmethod
    def _numeric_surface(score: dict[str, Any]) -> dict[str, Any]:
        return {
            key: score.get(key)
            for key in (
                "valid",
                "horizons",
                "objective_mean",
                "objective_std",
                "change_penalty_points",
                "team_cluster_penalty_points",
                "robust_score",
            )
            if key in score
        }

    def _canonical_surface(self, ids: list[int], changes: int) -> dict[str, Any]:
        return self._numeric_surface(
            self.canonical.score(
                [self.player_by_element[int(element)] for element in ids],
                changes=int(changes),
            )
        )

    def score_ids_compact(self, candidate_ids: list[list[int]], *, changes: int) -> list[dict[str, Any]]:
        self.last_scalar_fallback_count = 0
        self.last_formation_tie_count = 0
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
        position_columns = {position: np.flatnonzero(layout0 == code) for code, position in enumerate(POSITIONS)}
        if any(len(position_columns[position]) == 0 for position in POSITIONS):
            raise ValueError("batch candidate layout is missing a position")

        means = self.means[indices]
        variances = self.variances[indices]
        rows = np.arange(n)
        total_mean = np.zeros(n, dtype=np.float64)
        total_var = np.zeros(n, dtype=np.float64)
        horizon_means: dict[int, np.ndarray] = {}
        horizon_stds: dict[int, np.ndarray] = {}
        scalar_required = np.zeros(n, dtype=bool)
        formation_tied = np.zeros(n, dtype=bool)
        bench_weight = float(self.context["bench_weight"])
        captain_weight = float(self.context["captain_weight"])

        for offset in range(self.max_horizon):
            gw_means = means[:, :, offset]
            gw_vars = variances[:, :, offset]
            ranked_columns: dict[str, np.ndarray] = {}
            for position in POSITIONS:
                cols = position_columns[position]
                pm = gw_means[:, cols]
                order = np.argsort(-pm, axis=1, kind="stable")
                ranked_columns[position] = cols[order]

            formation_means: list[np.ndarray] = []
            for d, m, f in self.formations:
                selected_columns: list[np.ndarray] = [ranked_columns["GK"][:, 0]]
                selected_columns.extend(ranked_columns["DEF"][:, rank] for rank in range(d))
                selected_columns.extend(ranked_columns["MID"][:, rank] for rank in range(m))
                selected_columns.extend(ranked_columns["FWD"][:, rank] for rank in range(f))
                formation_means.append(self._ordered_sum(gw_means, selected_columns, rows))
            fm = np.stack(formation_means, axis=1)
            best_formation = np.argmax(fm, axis=1)
            if fm.shape[1] > 1:
                sorted_fm = np.sort(fm, axis=1)
                formation_tied |= (sorted_fm[:, -1] - sorted_fm[:, -2]) <= self.FORMATION_MARGIN_EPS
            selected_counts = np.asarray(self.formations, dtype=np.int8)[best_formation]

            starter_mask = np.zeros((n, width), dtype=bool)
            lineup_mean = np.zeros(n, dtype=np.float64)
            lineup_var = np.zeros(n, dtype=np.float64)
            gk_column = ranked_columns["GK"][:, 0]
            starter_mask[rows, gk_column] = True
            lineup_mean = lineup_mean + gw_means[rows, gk_column]
            lineup_var = lineup_var + gw_vars[rows, gk_column]

            for position_index, position in enumerate(("DEF", "MID", "FWD")):
                ranked = ranked_columns[position]
                counts = selected_counts[:, position_index]
                for rank in range(ranked.shape[1]):
                    selected = rank < counts
                    if not np.any(selected):
                        continue
                    column = ranked[:, rank]
                    selected_rows = rows[selected]
                    selected_columns = column[selected]
                    starter_mask[selected_rows, selected_columns] = True
                    lineup_mean = lineup_mean + np.where(selected, gw_means[rows, column], 0.0)
                    lineup_var = lineup_var + np.where(selected, gw_vars[rows, column], 0.0)

            all_mean = np.zeros(n, dtype=np.float64)
            all_var = np.zeros(n, dtype=np.float64)
            for column in range(width):
                all_mean = all_mean + gw_means[:, column]
                all_var = all_var + gw_vars[:, column]
            bench_mean = all_mean - lineup_mean
            bench_var = all_var - lineup_var

            starter_means = np.where(starter_mask, gw_means, -np.inf)
            captain_column = np.argmax(starter_means, axis=1)
            captain_mean = gw_means[rows, captain_column]
            captain_var = gw_vars[rows, captain_column]

            gw_mean = lineup_mean + bench_weight * bench_mean + captain_weight * captain_mean
            captain_extra_var = ((1.0 + captain_weight) ** 2 - 1.0) * captain_var
            gw_var = lineup_var + (bench_weight ** 2) * bench_var + captain_extra_var
            total_mean = total_mean + gw_mean
            total_var = total_var + gw_var

            elapsed = offset + 1
            if elapsed in self.context["horizon_set"]:
                raw_std = np.sqrt(total_var)
                scalar_required |= self._near_round_boundary(total_mean)
                scalar_required |= self._near_round_boundary(raw_std)
                horizon_means[elapsed] = self._round3(total_mean)
                horizon_stds[elapsed] = self._round3(raw_std)

        self.last_formation_tie_count = int(np.count_nonzero(formation_tied))
        self.total_formation_tie_count += self.last_formation_tie_count

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
        normalized = {h: float(weights.get(str(h), 0.0)) / weight_sum for h in horizons}
        change_penalty = int(changes) * float(self.context["change_penalty_points"])
        risk_aversion = float(self.context["risk_aversion"])

        out: list[dict[str, Any]] = []
        for row_index in range(n):
            if bool(scalar_required[row_index]):
                out.append(self._canonical_surface(candidate_ids[row_index], int(changes)))
                self.last_scalar_fallback_count += 1
                self.total_scalar_fallback_count += 1
                continue
            horizon_rows = {str(h): {"valid": True, "mean": float(horizon_means[h][row_index]), "std": float(horizon_stds[h][row_index])} for h in horizons}
            objective_mean = sum(normalized[h] * horizon_rows[str(h)]["mean"] for h in horizons)
            objective_var = sum((normalized[h] ** 2) * (horizon_rows[str(h)]["std"] ** 2) for h in horizons)
            objective_std = math.sqrt(objective_var)
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
    values = np.asarray(metrics, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 6:
        raise ValueError("skyline metrics must have shape (n, 6)")
    n = values.shape[0]
    if n <= 1:
        return np.arange(n, dtype=np.int32)
    active = np.arange(n, dtype=np.int32)
    block = 512
    dominated = np.zeros(n, dtype=bool)
    for start in range(0, n, block):
        stop = min(n, start + block)
        target_idx = active[start:stop]
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