from __future__ import annotations

from pathlib import Path

PATH = Path("src/engines/v4_full_universe_package_search_core.py")


def replace_between(source: str, start: str, end: str, replacement: str) -> str:
    a = source.index(start)
    b = source.index(end, a)
    return source[:a] + replacement.rstrip() + "\n\n" + source[b:]


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    ranking = '''def _rank(row: dict) -> tuple:
    cached = row.get("_rank_tuple")
    if cached is not None:
        return tuple(cached)
    rank = (
        _f(row.get("adjusted_utility_gain_5")),
        _f(row.get("net_xpts_5")),
        _f(row.get("net_xpts_15")),
        -int(row.get("hit_cost") or 0),
        -int(row.get("replacements") or 0),
        -int(row.get("target_cost") or 0),
        str(row.get("package_id") or ""),
    )
    if row.get("exact_utility_materialized") is True:
        row["_rank_tuple"] = rank
    return rank


def _retain_top(rows: list[dict], row: dict, limit: int) -> None:
    if limit <= 0:
        return
    row_rank = _rank(row)
    if len(rows) >= limit and row_rank <= _rank(rows[-1]):
        return
    index = 0
    size = len(rows)
    while index < size and _rank(rows[index]) >= row_rank:
        index += 1
    rows.insert(index, row)
    if len(rows) > limit:
        rows.pop()
'''
    text = replace_between(text, "def _rank(", "def _pairings(", ranking)

    old_metrics = '''                target_metrics = _metrics_from_profiles(\n                    keep_profile, chosen_profile, position_prefix_cache=position_prefix_cache,\n                )'''
    new_metrics = '''                target_metrics = _metrics_from_profiles(\n                    keep_profile, chosen_profile, include_horizons=False, position_prefix_cache=position_prefix_cache,\n                )'''
    if old_metrics not in text:
        raise SystemExit("exact utility metrics call target missing")
    text = text.replace(old_metrics, new_metrics, 1)

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
