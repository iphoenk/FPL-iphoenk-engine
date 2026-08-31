from pathlib import Path

p = Path('src/v5/decision/lineup_optimizer.py')
s = p.read_text(encoding='utf-8')

def once(old: str, new: str, label: str) -> None:
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1 match, found {n}')
    s = s.replace(old, new, 1)

once(
    'import itertools\nfrom collections import Counter\nfrom typing import Any, Iterable, Mapping\n',
    'import itertools\nfrom collections import Counter\nfrom functools import lru_cache\nfrom typing import Any, Iterable, Mapping\n',
    'lru import',
)
once(
    'def _cfg() -> dict[str, Any]:\n',
    '@lru_cache(maxsize=1)\ndef _cfg() -> dict[str, Any]:\n',
    'cfg cache',
)
once(
'''def _lineup_risk_adjustment(
    starters: list[dict[str, Any]],
    bench_rows: list[dict[str, Any]],
    gw: int,
    lineup_cfg: Mapping[str, Any],
) -> dict[str, Any]:
''',
'''def _lineup_risk_adjustment(
    starters: list[dict[str, Any]],
    bench_rows: list[dict[str, Any]],
    gw: int,
    lineup_cfg: Mapping[str, Any],
    precomputed: Mapping[str, Mapping[int, float]] | None = None,
) -> dict[str, Any]:
''',
    'risk signature',
)
once(
'''    defensive_route_points = sum(_defensive_route_proxy(row, gw) for row in starters)
    total_points = sum(max(0.0, gw_projection(row, gw)["mean"]) for row in starters)
    route_share = defensive_route_points / total_points if total_points > 1e-9 else 0.0
    concentration_penalty = max(0.0, route_share - 0.50) * _f(cfg.get("defensive_route_concentration_penalty"), 0.06)

    usable_bench = [row for row in bench_rows if row.get("position") != "GK"]
    bench_scores = [max(0.0, player_score(row, gw, "bench_score")) for row in usable_bench[:3]]
''',
'''    cached = precomputed or {}
    route_by_id = cached.get("defensive_route") or {}
    mean_by_id = cached.get("mean") or {}
    bench_score_by_id = cached.get("bench_score") or {}

    def element(row: Mapping[str, Any]) -> int:
        return int(row.get("element") or -1)

    defensive_route_points = sum(
        _f(route_by_id.get(element(row)), _defensive_route_proxy(row, gw))
        for row in starters
    )
    total_points = sum(
        max(0.0, _f(mean_by_id.get(element(row)), gw_projection(row, gw)["mean"]))
        for row in starters
    )
    route_share = defensive_route_points / total_points if total_points > 1e-9 else 0.0
    concentration_penalty = max(0.0, route_share - 0.50) * _f(cfg.get("defensive_route_concentration_penalty"), 0.06)

    usable_bench = [row for row in bench_rows if row.get("position") != "GK"]
    bench_scores = [
        max(0.0, _f(bench_score_by_id.get(element(row)), player_score(row, gw, "bench_score")))
        for row in usable_bench[:3]
    ]
''',
    'risk cached metrics',
)
once(
'''    candidates: list[dict[str, Any]] = []
    all_ids = {int(player["element"]) for player in indexed}
    for combo in itertools.combinations(indexed, starting_size):
''',
'''    candidates: list[dict[str, Any]] = []
    all_ids = {int(player["element"]) for player in indexed}
    bench_policy = lineup_cfg.get("bench_score")
    if not isinstance(bench_policy, dict):
        raise RuntimeError("V5 lineup bench_score policy missing")
    precomputed = {
        "mean": {int(player["element"]): float(metrics[int(player["element"])]["mean"]) for player in indexed},
        "defensive_route": {int(player["element"]): _defensive_route_proxy(player, gw) for player in indexed},
        "bench_score": {},
    }
    for player in indexed:
        element_id = int(player["element"])
        projection = gw_projection(player, gw)
        start_probability, dnp_probability = _minutes_probabilities(player)
        precomputed["bench_score"][element_id] = _score_from_metrics(
            bench_policy, projection, start_probability, dnp_probability
        )
    for combo in itertools.combinations(indexed, starting_size):
''',
    'enumeration precompute',
)
once(
    '        risk = _lineup_risk_adjustment(rows, bench_rows, gw, lineup_cfg)\n',
    '        risk = _lineup_risk_adjustment(rows, bench_rows, gw, lineup_cfg, precomputed)\n',
    'risk precompute call',
)
p.write_text(s, encoding='utf-8')
