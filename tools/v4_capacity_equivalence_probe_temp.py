from pathlib import Path

path = Path("src/engines/v4_full_universe_exact_state_frontier.py")
text = path.read_text()
text = text.replace(
    "from typing import Any, Callable, Iterator\n",
    "from typing import Any, Callable, Iterator\n\nimport numpy as np\n",
    1,
)
insert_at = text.index("    def iter_legal(\n")
helper = r'''    def _capacity_key(
        self,
        keep_signature: int,
        incoming_signature: int,
        remaining_picks: int,
        cache: dict[tuple[int, int], int | None],
    ) -> int | None:
        cache_key = (incoming_signature, remaining_picks)
        if cache_key in cache:
            return cache[cache_key]
        if remaining_picks <= 0:
            result = 0 if _legal_with_keep(keep_signature, incoming_signature) else None
            cache[cache_key] = result
            return result
        value = 0
        for team_id in range(1, 21):
            used = _club_count(keep_signature, team_id) + _club_count(incoming_signature, team_id)
            if used > MAX_PER_CLUB:
                cache[cache_key] = None
                return None
            residual = MAX_PER_CLUB - used
            effective = min(int(remaining_picks), residual)
            value |= int(effective) << ((team_id - 1) * 2)
        cache[cache_key] = value
        return value

    @staticmethod
    def _gw_flat(row: IncomingState) -> tuple[float, ...]:
        return tuple(
            value
            for position_values in row.gw_values
            for gw_values in position_values
            for value in gw_values
        )

    def _rank_monotone_key(self, row: IncomingState) -> tuple:
        # Dominance-consistent total order. If A rank-dominates B, A must sort
        # before B. Therefore later rows can never displace earlier rows.
        return (
            -row.x5,
            -row.x15,
            row.cost,
            row.projection_uncertainty,
            row.xmins_uncertainty,
            row.tactical_uncertainty,
            row.roster_change_uncertainty,
            tuple(-value for value in self._gw_flat(row)),
            _state_key(row),
        )

    @staticmethod
    def _frontier_monotone_key(row: IncomingState) -> tuple:
        # Includes every scalar no-worse dimension used by frontier_dominates.
        return (
            -row.x5,
            -row.x15,
            -row.x10,
            -row.x3,
            row.cost,
            row.projection_uncertainty,
            row.xmins_uncertainty,
            row.tactical_uncertainty,
            row.roster_change_uncertainty,
            row.price_risk,
            -row.tactical_role_confidence,
            -row.opponent_matchup_confidence,
            _state_key(row),
        )

    @staticmethod
    def _scalar_index(capacity: int, gw_width: int = 0) -> dict[str, Any]:
        names = (
            "cost", "x3", "x5", "x10", "x15",
            "projection_uncertainty", "xmins_uncertainty", "tactical_uncertainty",
            "roster_change_uncertainty", "price_risk", "tactical_role_confidence",
            "opponent_matchup_confidence",
        )
        result = {
            "capacity": int(capacity),
            "count": 0,
            "gw_width": int(gw_width),
            **{
                name: np.empty(int(capacity), dtype=np.int64 if name == "cost" else np.float64)
                for name in names
            },
        }
        if gw_width:
            result["gw"] = np.empty((int(capacity), int(gw_width)), dtype=np.float64)
        return result

    def _scalar_index_add(self, index: dict[str, Any], row: IncomingState) -> None:
        pos = int(index["count"])
        index["cost"][pos] = row.cost
        index["x3"][pos] = row.x3
        index["x5"][pos] = row.x5
        index["x10"][pos] = row.x10
        index["x15"][pos] = row.x15
        index["projection_uncertainty"][pos] = row.projection_uncertainty
        index["xmins_uncertainty"][pos] = row.xmins_uncertainty
        index["tactical_uncertainty"][pos] = row.tactical_uncertainty
        index["roster_change_uncertainty"][pos] = row.roster_change_uncertainty
        index["price_risk"][pos] = row.price_risk
        index["tactical_role_confidence"][pos] = row.tactical_role_confidence
        index["opponent_matchup_confidence"][pos] = row.opponent_matchup_confidence
        gw_width = int(index.get("gw_width") or 0)
        if gw_width:
            values = self._gw_flat(row)
            if len(values) != gw_width:
                raise RuntimeError("rank GW vector width drifted inside exact stage")
            index["gw"][pos, :] = values
        index["count"] = pos + 1

    def _rank_index_dominated(self, index: dict[str, Any], candidate: IncomingState) -> bool:
        n = int(index["count"])
        if n <= 0:
            return False
        mask = index["cost"][:n] <= candidate.cost
        mask &= index["x5"][:n] >= candidate.x5
        mask &= index["x15"][:n] >= candidate.x15
        mask &= index["projection_uncertainty"][:n] <= candidate.projection_uncertainty
        mask &= index["xmins_uncertainty"][:n] <= candidate.xmins_uncertainty
        mask &= index["tactical_uncertainty"][:n] <= candidate.tactical_uncertainty
        mask &= index["roster_change_uncertainty"][:n] <= candidate.roster_change_uncertainty
        mask &= (
            (index["x5"][:n] > candidate.x5 + _TWO_DP_ROUND_ERROR)
            | (index["x15"][:n] > candidate.x15 + _TWO_DP_ROUND_ERROR)
            | (index["cost"][:n] < candidate.cost)
        )
        gw_width = int(index.get("gw_width") or 0)
        if gw_width:
            candidate_gw = np.asarray(self._gw_flat(candidate), dtype=np.float64)
            mask &= np.all(index["gw"][:n, :] >= candidate_gw, axis=1)
        matched = int(np.count_nonzero(mask))
        self.stats["dominance_full_checks"] += matched
        self.stats["dominance_pairs_skipped_by_scalar_mask"] = int(
            self.stats.get("dominance_pairs_skipped_by_scalar_mask") or 0
        ) + max(0, n - matched)
        if matched:
            self.stats["frontier_insert_rejected"] += 1
            return True
        return False

    def _frontier_index_dominated(self, index: dict[str, Any], candidate: IncomingState) -> bool:
        n = int(index["count"])
        if n <= 0:
            return False
        mask = index["cost"][:n] <= candidate.cost
        mask &= index["projection_uncertainty"][:n] <= candidate.projection_uncertainty
        mask &= index["xmins_uncertainty"][:n] <= candidate.xmins_uncertainty
        mask &= index["tactical_uncertainty"][:n] <= candidate.tactical_uncertainty
        mask &= index["roster_change_uncertainty"][:n] <= candidate.roster_change_uncertainty
        mask &= index["price_risk"][:n] <= candidate.price_risk
        mask &= index["x3"][:n] >= candidate.x3
        mask &= index["x5"][:n] >= candidate.x5
        mask &= index["x10"][:n] >= candidate.x10
        mask &= index["x15"][:n] >= candidate.x15
        mask &= index["tactical_role_confidence"][:n] >= candidate.tactical_role_confidence
        mask &= index["opponent_matchup_confidence"][:n] >= candidate.opponent_matchup_confidence
        k = max(1, len(candidate.players))
        horizon_gap = float(self.frontier_epsilon) + _TWO_DP_ROUND_ERROR
        sum_gap = (float(self.frontier_epsilon) + _FOUR_DP_ROUND_ERROR) * k
        mask &= (
            (index["x3"][:n] > candidate.x3 + horizon_gap)
            | (index["x5"][:n] > candidate.x5 + horizon_gap)
            | (index["x10"][:n] > candidate.x10 + horizon_gap)
            | (index["x15"][:n] > candidate.x15 + horizon_gap)
            | (index["price_risk"][:n] + sum_gap < candidate.price_risk)
            | (index["tactical_role_confidence"][:n] > candidate.tactical_role_confidence + sum_gap)
            | (index["opponent_matchup_confidence"][:n] > candidate.opponent_matchup_confidence + sum_gap)
        )
        matched = int(np.count_nonzero(mask))
        self.stats["dominance_full_checks"] += matched
        self.stats["dominance_pairs_skipped_by_scalar_mask"] = int(
            self.stats.get("dominance_pairs_skipped_by_scalar_mask") or 0
        ) + max(0, n - matched)
        if matched:
            self.stats["frontier_insert_rejected"] += 1
            return True
        return False

    def _monotone_rank_layers(
        self,
        candidates: list[IncomingState],
    ) -> list[list[IncomingState]]:
        layers = self._new_rank_layers()
        if not candidates:
            return layers
        gw_width = len(self._gw_flat(candidates[0]))
        indexes = [self._scalar_index(len(candidates), gw_width) for _ in range(self.top_keep)]
        started = __import__("time").perf_counter()
        ordered = sorted(candidates, key=self._rank_monotone_key)
        for ordinal, candidate in enumerate(ordered, 1):
            for layer_index in range(self.top_keep):
                self.stats["frontier_insert_calls"] += 1
                if self._rank_index_dominated(indexes[layer_index], candidate):
                    continue
                layers[layer_index].append(candidate)
                self._scalar_index_add(indexes[layer_index], candidate)
                break
            if ordinal % 5000 == 0:
                print(
                    "RANK_MASK_PROGRESS", ordinal, len(candidates),
                    "elapsed", round(__import__("time").perf_counter() - started, 3),
                    "layer_sizes", [len(layer) for layer in layers],
                    "checks", self.stats["dominance_full_checks"],
                    "scalar_skipped", self.stats.get("dominance_pairs_skipped_by_scalar_mask", 0),
                    flush=True,
                )
        return layers

    def _monotone_frontier(
        self,
        candidates: list[IncomingState],
    ) -> list[IncomingState]:
        layer: list[IncomingState] = []
        index = self._scalar_index(len(candidates))
        started = __import__("time").perf_counter()
        ordered = sorted(candidates, key=self._frontier_monotone_key)
        for ordinal, candidate in enumerate(ordered, 1):
            self.stats["frontier_insert_calls"] += 1
            if not self._frontier_index_dominated(index, candidate):
                layer.append(candidate)
                self._scalar_index_add(index, candidate)
            if ordinal % 5000 == 0:
                print(
                    "FRONTIER_MASK_PROGRESS", ordinal, len(candidates),
                    "elapsed", round(__import__("time").perf_counter() - started, 3),
                    "retained", len(layer),
                    "checks", self.stats["dominance_full_checks"],
                    "scalar_skipped", self.stats.get("dominance_pairs_skipped_by_scalar_mask", 0),
                    flush=True,
                )
        return layer

    def _states_for_need_keep(
        self,
        need: Counter,
        keep: tuple[Candidate, ...],
    ) -> tuple[tuple[IncomingState, ...], tuple[IncomingState, ...]]:
        key = _need_key(need)
        keep_signature = _signature(tuple(keep))
        cache_key = (key, keep_signature)
        keep_cache = getattr(self, "_keep_need_cache", None)
        if keep_cache is None:
            keep_cache = {}
            self._keep_need_cache = keep_cache
        cached = keep_cache.get(cache_key)
        if cached is not None:
            return cached

        raw_need = 1
        for position, count in key:
            raw_need *= comb(len(self.pools.get(position, tuple())), count)
        self.stats["need_raw_combinations_theoretical"] += raw_need

        total_picks = sum(count for _position, count in key)
        rank_states = (_empty_state(),)
        frontier_states = (_empty_state(),)
        capacity_cache: dict[tuple[int, int], int | None] = {}
        picked_before = 0
        probe_started = __import__("time").perf_counter()

        for position, count in key:
            remaining_after_position = total_picks - picked_before - count
            pool = self.pools.get(position, tuple())

            rank_dp: list[dict[int, list[list[IncomingState]]]] = [dict() for _ in range(count + 1)]
            frontier_dp: list[dict[int, list[IncomingState]]] = [dict() for _ in range(count + 1)]
            remaining_before_position = count + remaining_after_position
            for row in rank_states:
                bucket = self._capacity_key(
                    keep_signature, row.club_signature, remaining_before_position, capacity_cache
                )
                if bucket is None:
                    continue
                _skyband_insert(
                    rank_dp[0].setdefault(bucket, self._new_rank_layers()),
                    row,
                    top_keep=self.top_keep,
                    frontier_epsilon=self.frontier_epsilon,
                    relation=rank_dominates,
                    metrics=self.stats,
                )
            for row in frontier_states:
                bucket = self._capacity_key(
                    keep_signature, row.club_signature, remaining_before_position, capacity_cache
                )
                if bucket is None:
                    continue
                _front_insert(
                    frontier_dp[0].setdefault(bucket, []),
                    row,
                    frontier_epsilon=self.frontier_epsilon,
                    relation=frontier_dominates,
                    metrics=self.stats,
                )

            if count == 1:
                remaining = remaining_after_position
                rank_pending: dict[int, list[IncomingState]] = {}
                rank_sources = _flatten_rank(rank_dp[0])
                for player in pool:
                    singleton = self._single_state[player.element]
                    for prefix in rank_sources:
                        self.stats["rank_merge_states_considered"] += 1
                        merged = singleton if not prefix.players else _merge_disjoint_position(prefix, singleton, position)
                        bucket = self._capacity_key(
                            keep_signature, merged.club_signature, remaining, capacity_cache
                        )
                        if bucket is not None:
                            rank_pending.setdefault(bucket, []).append(merged)
                for bucket, candidates in rank_pending.items():
                    rank_dp[1][bucket] = self._monotone_rank_layers(candidates)

                frontier_pending: dict[int, list[IncomingState]] = {}
                frontier_sources = _flatten_frontier(frontier_dp[0])
                for player in pool:
                    singleton = self._single_state[player.element]
                    for prefix in frontier_sources:
                        self.stats["frontier_merge_states_considered"] += 1
                        merged = singleton if not prefix.players else _merge_disjoint_position(prefix, singleton, position)
                        bucket = self._capacity_key(
                            keep_signature, merged.club_signature, remaining, capacity_cache
                        )
                        if bucket is not None:
                            frontier_pending.setdefault(bucket, []).append(merged)
                for bucket, candidates in frontier_pending.items():
                    frontier_dp[1][bucket] = self._monotone_frontier(candidates)
            else:
                for processed, player in enumerate(pool):
                    singleton = self._single_state[player.element]
                    max_pick = min(count, processed + 1)
                    for pick in range(max_pick, 0, -1):
                        rank_sources = _flatten_rank(rank_dp[pick - 1])
                        remaining = (count - pick) + remaining_after_position
                        for prefix in rank_sources:
                            self.stats["rank_merge_states_considered"] += 1
                            merged = singleton if not prefix.players else _merge_same_position(prefix, singleton, position)
                            bucket = self._capacity_key(
                                keep_signature, merged.club_signature, remaining, capacity_cache
                            )
                            if bucket is None:
                                continue
                            _skyband_insert(
                                rank_dp[pick].setdefault(bucket, self._new_rank_layers()),
                                merged,
                                top_keep=self.top_keep,
                                frontier_epsilon=self.frontier_epsilon,
                                relation=rank_dominates,
                                metrics=self.stats,
                            )

                        frontier_sources = _flatten_frontier(frontier_dp[pick - 1])
                        for prefix in frontier_sources:
                            self.stats["frontier_merge_states_considered"] += 1
                            merged = singleton if not prefix.players else _merge_same_position(prefix, singleton, position)
                            bucket = self._capacity_key(
                                keep_signature, merged.club_signature, remaining, capacity_cache
                            )
                            if bucket is None:
                                continue
                            _front_insert(
                                frontier_dp[pick].setdefault(bucket, []),
                                merged,
                                frontier_epsilon=self.frontier_epsilon,
                                relation=frontier_dominates,
                                metrics=self.stats,
                            )

            rank_states = _flatten_rank(rank_dp[count])
            frontier_states = _flatten_frontier(frontier_dp[count])
            picked_before += count
            print(
                "CAPACITY_EQ_STAGE",
                key,
                position,
                "rank",
                len(rank_states),
                "frontier",
                len(frontier_states),
                "elapsed",
                round(__import__("time").perf_counter() - probe_started, 3),
                "checks",
                self.stats["dominance_full_checks"],
                "x5_skipped",
                self.stats["dominance_pairs_skipped_by_x5_index"],
                "scalar_skipped",
                self.stats.get("dominance_pairs_skipped_by_scalar_mask", 0),
                flush=True,
            )
            if not rank_states and not frontier_states:
                break

        union_count = len(_union_states(rank_states, frontier_states))
        self.stats["need_union_states_retained"] += union_count
        cached = (rank_states, frontier_states)
        keep_cache[cache_key] = cached
        return cached

'''
text = text[:insert_at] + helper + text[insert_at:]
old = "        rank_states, frontier_states = self._states_for_need(need)\n        states = _union_states(rank_states, frontier_states)\n"
new = "        need_key = _need_key(need)\n        if len(need_key) > 1:\n            rank_states, frontier_states = self._states_for_need_keep(need, keep)\n        else:\n            rank_states, frontier_states = self._states_for_need(need)\n        states = _union_states(rank_states, frontier_states)\n"
if old not in text:
    raise RuntimeError("capacity-equivalence probe insertion target drifted")
path.write_text(text.replace(old, new, 1))
