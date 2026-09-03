from __future__ import annotations

from pathlib import Path

PATH = Path("src/engines/v4_full_universe_package_search_core.py")


def replace_between(source: str, start: str, end: str, replacement: str) -> str:
    a = source.index(start)
    b = source.index(end, a)
    return source[:a] + replacement.rstrip() + "\n\n" + source[b:]


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    structural = '''def _structural_flexibility(target: tuple[Candidate, ...], itb: int) -> float:
    # For every legal 15-player squad under MAX_PER_CLUB, aggregate open club
    # capacity is exactly 20*MAX_PER_CLUB-len(target). Avoid rebuilding club
    # counters for every exact package; this is algebraically identical.
    open_club_capacity = max(0, 20 * MAX_PER_CLUB - len(target))
    return round(min(1.0, 0.55 * min(1.0, max(0, itb) / 20.0) + 0.45 * min(1.0, open_club_capacity / 45.0)), 4)
'''
    text = replace_between(text, "def _structural_flexibility(", "def _frontier_vector(", structural)

    frontier = '''def _frontier_tuple(row: dict) -> tuple[float, ...]:
    # Normalize governed frontier dimensions to maximize once per package.
    # Caching changes no frontier semantics; it only removes repeated dict
    # construction and float conversion during the exact Pareto scan.
    cached = row.get("_frontier_vec")
    if cached is not None:
        return tuple(cached)
    return (
        _f(row.get("net_xpts_3")),
        _f(row.get("net_xpts_5")),
        _f(row.get("net_xpts_10")),
        _f(row.get("net_xpts_15")),
        _f(row.get("structural_flexibility")),
        _f(row.get("tactical_role_confidence")),
        _f(row.get("opponent_matchup_confidence")),
        -_f(row.get("hit_cost")),
        -_f(row.get("xmins_uncertainty")),
        -_f(row.get("projection_uncertainty")),
        -_f(row.get("tactical_uncertainty")),
        -_f(row.get("price_risk")),
        -_f(row.get("roster_change_uncertainty")),
    )


def _dominates_vector(left: tuple[float, ...], right: tuple[float, ...], epsilon: float) -> bool:
    strict = False
    for a, b in zip(left, right):
        if a + epsilon < b:
            return False
        if a > b + epsilon:
            strict = True
    return strict


def _dominates_package(left: dict, right: dict, epsilon: float) -> bool:
    return _dominates_vector(_frontier_tuple(left), _frontier_tuple(right), epsilon)


def _frontier_insert(frontier: list[dict], row: dict, epsilon: float) -> None:
    row_vec = _frontier_tuple(row)
    survivors: list[dict] = []
    for incumbent in frontier:
        incumbent_vec = _frontier_tuple(incumbent)
        if _dominates_vector(incumbent_vec, row_vec, epsilon):
            return
        if not _dominates_vector(row_vec, incumbent_vec, epsilon):
            survivors.append(incumbent)
    survivors.append(row)
    frontier[:] = survivors


def _compact_for_frontier(row: dict) -> dict:
    keys = (
        "package_id", "replacements", "target_cost", "target_itb", "hit_cost",
        "net_xpts_3", "net_xpts_5", "net_xpts_10", "net_xpts_15", "adjusted_best_xi_gain_5",
        "adjusted_utility_gain_5", "xmins_uncertainty", "projection_uncertainty", "tactical_uncertainty",
        "price_risk", "roster_change_uncertainty", "tactical_role_confidence", "opponent_matchup_confidence",
        "structural_flexibility", "classification",
    )
    compact = {key: row.get(key) for key in keys}
    compact["_out_ids"] = tuple(row.get("_out_ids") or ())
    compact["_in_ids"] = tuple(row.get("_in_ids") or ())
    compact["_frontier_vec"] = _frontier_tuple(compact)
    if row.get("_rank_key") is not None:
        compact["_rank_key"] = tuple(row["_rank_key"])
    return compact
'''
    text = replace_between(text, "def _frontier_vector(", "def _rank(", frontier)

    ranking = '''def _rank(row: dict) -> tuple:
    cached = row.get("_rank_key")
    if cached is not None:
        return tuple(cached)
    return (
        _f(row.get("adjusted_utility_gain_5")),
        _f(row.get("net_xpts_5")),
        _f(row.get("net_xpts_15")),
        -int(row.get("hit_cost") or 0),
        -int(row.get("replacements") or 0),
        -int(row.get("target_cost") or 0),
        str(row.get("package_id") or ""),
    )


def _retain_top(rows: list[dict], row: dict, limit: int) -> None:
    # Keep the exact same top-N set as full sorting, but maintain the tiny
    # retained set in ascending rank order with binary insertion. This avoids
    # sorting and recomputing rank keys for all retained rows on every package.
    if limit <= 0:
        return
    key = _rank(row)
    row["_rank_key"] = key
    if len(rows) >= limit and key <= _rank(rows[0]):
        return
    lo = 0
    hi = len(rows)
    while lo < hi:
        mid = (lo + hi) // 2
        if _rank(rows[mid]) <= key:
            lo = mid + 1
        else:
            hi = mid
    rows.insert(lo, row)
    if len(rows) > limit:
        del rows[0]
'''
    text = replace_between(text, "def _rank(", "def _pairings(", ranking)

    old_tail = '    frontier.sort(key=_rank, reverse=True)\n'
    new_tail = '''    # _retain_top keeps rows ascending for O(log N) insertion; restore the
    # historical externally visible descending order once, after exhaustive search.
    for retained_rows in top_by_k.values():
        retained_rows.sort(key=_rank, reverse=True)
    frontier.sort(key=_rank, reverse=True)
'''
    if old_tail not in text:
        raise SystemExit("final retention ordering target missing")
    text = text.replace(old_tail, new_tail, 1)

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
