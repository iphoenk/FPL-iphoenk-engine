from pathlib import Path

path = Path("src/engines/v4_full_universe_exact_state_frontier.py")
text = path.read_text()
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
    def _x15_key(state: IncomingState) -> float:
        return -state.x15

    def _cost_x15_add(
        self,
        index: dict[int, list[IncomingState]],
        costs: list[int],
        row: IncomingState,
    ) -> None:
        bucket = index.get(row.cost)
        if bucket is None:
            bucket = []
            index[row.cost] = bucket
            costs.insert(bisect_right(costs, row.cost), row.cost)
        bucket.insert(bisect_right(bucket, -row.x15, key=self._x15_key), row)

    def _cost_x15_build(
        self,
        rows: list[IncomingState],
    ) -> tuple[dict[int, list[IncomingState]], list[int]]:
        index: dict[int, list[IncomingState]] = {}
        costs: list[int] = []
        for row in rows:
            self._cost_x15_add(index, costs, row)
        return index, costs

    def _indexed_dominator_exists(
        self,
        index: dict[int, list[IncomingState]],
        costs: list[int],
        candidate: IncomingState,
        relation: Callable[..., bool],
    ) -> bool:
        total_indexed = sum(len(index[cost]) for cost in costs)
        eligible_cost_end = bisect_right(costs, candidate.cost)
        checks = 0
        x15_eligible = 0
        for cost in costs[:eligible_cost_end]:
            rows = index[cost]
            end = bisect_right(rows, -candidate.x15, key=self._x15_key)
            x15_eligible += end
            for idx in range(end):
                incumbent = rows[idx]
                checks += 1
                if relation(
                    incumbent,
                    candidate,
                    frontier_epsilon=self.frontier_epsilon,
                ):
                    self.stats["dominance_full_checks"] += checks
                    self.stats["dominance_pairs_skipped_by_cost_x15_index"] = int(
                        self.stats.get("dominance_pairs_skipped_by_cost_x15_index") or 0
                    ) + max(0, total_indexed - x15_eligible)
                    self.stats["frontier_insert_rejected"] += 1
                    return True
        self.stats["dominance_full_checks"] += checks
        self.stats["dominance_pairs_skipped_by_cost_x15_index"] = int(
            self.stats.get("dominance_pairs_skipped_by_cost_x15_index") or 0
        ) + max(0, total_indexed - x15_eligible)
        return False

    def _monotone_rank_layers(
        self,
        candidates: list[IncomingState],
    ) -> list[list[IncomingState]]:
        layers = self._new_rank_layers()
        indexes: list[tuple[dict[int, list[IncomingState]], list[int]]] = [
            ({}, []) for _ in range(self.top_keep)
        ]
        previous_x5: float | None = None
        for candidate in sorted(candidates, key=lambda row: (-row.x5, _state_key(row))):
            if previous_x5 is not None and candidate.x5 == previous_x5:
                _skyband_insert(
                    layers,
                    candidate,
                    top_keep=self.top_keep,
                    frontier_epsilon=self.frontier_epsilon,
                    relation=rank_dominates,
                    metrics=self.stats,
                )
                indexes = [self._cost_x15_build(layer) for layer in layers]
                previous_x5 = candidate.x5
                continue
            for layer_index in range(self.top_keep):
                self.stats["frontier_insert_calls"] += 1
                index, costs = indexes[layer_index]
                if self._indexed_dominator_exists(index, costs, candidate, rank_dominates):
                    continue
                layers[layer_index].append(candidate)
                self._cost_x15_add(index, costs, candidate)
                break
            previous_x5 = candidate.x5
        return layers

    def _monotone_frontier(
        self,
        candidates: list[IncomingState],
    ) -> list[IncomingState]:
        layer: list[IncomingState] = []
        index: dict[int, list[IncomingState]] = {}
        costs: list[int] = []
        previous_x5: float | None = None
        for candidate in sorted(candidates, key=lambda row: (-row.x5, _state_key(row))):
            if previous_x5 is not None and candidate.x5 == previous_x5:
                _front_insert(
                    layer,
                    candidate,
                    frontier_epsilon=self.frontier_epsilon,
                    relation=frontier_dominates,
                    metrics=self.stats,
                )
                index, costs = self._cost_x15_build(layer)
                previous_x5 = candidate.x5
                continue
            self.stats["frontier_insert_calls"] += 1
            if not self._indexed_dominator_exists(index, costs, candidate, frontier_dominates):
                layer.append(candidate)
                self._cost_x15_add(index, costs, candidate)
            previous_x5 = candidate.x5
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
                "cost_x15_skipped",
                self.stats.get("dominance_pairs_skipped_by_cost_x15_index", 0),
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
