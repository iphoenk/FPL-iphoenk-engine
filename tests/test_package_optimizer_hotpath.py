import random

import numpy as np

from src.models.package_optimizer_exact_batch import ExactBatchScorer, exact_skyline_indices
from src.models.package_optimizer_v2 import CompiledPackageScorer, _scoring_context, load_config, score_package


def _squad():
    rows = []
    element = 1
    for position, count in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for i in range(count):
            rows.append({
                "element": element,
                "position": position,
                "team_id": (element % 10) + 1,
                "xpts_by_gw": [
                    {"gw": gw, "mean": 3.5 + i * 0.2 + gw * 0.01, "std": 1.2 + i * 0.03}
                    for gw in range(3, 18)
                ],
            })
            element += 1
    return rows


def _candidate(element: int, position: str, team_id: int, seed: int) -> dict:
    rng = random.Random(seed)
    return {
        "element": element,
        "position": position,
        "team_id": team_id,
        "xpts_by_gw": [
            {"gw": gw, "mean": round(rng.uniform(0.0, 8.0), 4), "std": round(rng.uniform(0.2, 3.0), 4)}
            for gw in range(3, 18)
        ],
    }


def _numeric_surface(score: dict) -> dict:
    return {
        "valid": score.get("valid"),
        "horizons": score.get("horizons"),
        "objective_mean": score.get("objective_mean"),
        "objective_std": score.get("objective_std"),
        "change_penalty_points": score.get("change_penalty_points"),
        "team_cluster_penalty_points": score.get("team_cluster_penalty_points"),
        "robust_score": score.get("robust_score"),
    }


def test_cached_scoring_context_is_materially_identical():
    squad = _squad()
    baseline = score_package(squad, planning_gw=3, changes=1)
    context = _scoring_context(load_config(), 3)
    optimized = score_package(squad, planning_gw=3, changes=1, scoring_context=context)
    assert optimized == baseline


def test_scoring_context_is_reusable_without_mutation():
    squad = _squad()
    context = _scoring_context(load_config(), 3)
    first = score_package(squad, planning_gw=3, changes=0, scoring_context=context)
    second = score_package(squad, planning_gw=3, changes=0, scoring_context=context)
    assert first == second
    assert context["horizons"] == [3, 5, 10, 15]
    assert context["change_cap"] == 2


def test_precompiled_adapter_is_exactly_equal_to_canonical_score_package():
    squad = _squad()
    context = _scoring_context(load_config(), 3)
    compiled = CompiledPackageScorer(squad, 3, scoring_context=context)
    for changes in (0, 1, 2):
        expected = score_package(squad, planning_gw=3, changes=changes, scoring_context=context)
        actual = compiled.score(squad, changes=changes)
        assert actual == expected


def test_precompiled_adapter_preserves_input_order_for_tie_semantics():
    squad = _squad()
    for row in squad[:2]:
        for gw_row in row["xpts_by_gw"]:
            gw_row["mean"] = 10.0
    squad[0]["xpts_by_gw"][0]["std"] = 0.5
    squad[1]["xpts_by_gw"][0]["std"] = 2.5
    context = _scoring_context(load_config(), 3)
    expected = score_package(squad, planning_gw=3, changes=1, scoring_context=context)
    compiled = CompiledPackageScorer(squad, 3, scoring_context=context)
    assert compiled.score(squad, changes=1) == expected


def test_exact_batch_scorer_matches_canonical_randomized_single_and_pair_layouts():
    current = _squad()
    extras = []
    element = 100
    for position, count in (("GK", 6), ("DEF", 12), ("MID", 12), ("FWD", 8)):
        for i in range(count):
            extras.append(_candidate(element, position, 11 + (i % 8), element * 17))
            element += 1
    universe = current + extras
    context = _scoring_context(load_config(), 3)
    batch = ExactBatchScorer(universe, 3, scoring_context=context)
    rng = random.Random(4321)

    candidates: list[tuple[list[dict], int]] = []
    by_position = {position: [row for row in extras if row["position"] == position] for position in ("GK", "DEF", "MID", "FWD")}
    for _ in range(80):
        if rng.random() < 0.45:
            out_index = rng.randrange(len(current))
            outgoing = current[out_index]
            incoming = rng.choice(by_position[outgoing["position"]])
            candidate = [row for i, row in enumerate(current) if i != out_index] + [incoming]
            candidates.append((candidate, 1))
        else:
            out_indices = sorted(rng.sample(range(len(current)), 2))
            outs = [current[index] for index in out_indices]
            ins = [rng.choice(by_position[row["position"]]) for row in outs]
            if ins[0]["element"] == ins[1]["element"]:
                continue
            candidate = [row for i, row in enumerate(current) if i not in set(out_indices)] + ins
            candidates.append((candidate, 2))

    grouped: dict[tuple[int, tuple[str, ...]], list[list[dict]]] = {}
    for candidate, changes in candidates:
        layout = tuple(str(row["position"]) for row in candidate)
        grouped.setdefault((changes, layout), []).append(candidate)

    checked = 0
    for (changes, _layout), group in grouped.items():
        actual = batch.score_ids_compact([[int(row["element"]) for row in candidate] for candidate in group], changes=changes)
        expected = [score_package(candidate, 3, changes=changes, scoring_context=context) for candidate in group]
        assert [_numeric_surface(row) for row in actual] == [_numeric_surface(row) for row in expected]
        checked += len(group)
    assert checked >= 60


def test_exact_batch_scorer_preserves_captain_and_formation_ties():
    squad = _squad()
    extras = [_candidate(200, "MID", 18, 1), _candidate(201, "MID", 19, 2)]
    for row in squad + extras:
        for gw_row in row["xpts_by_gw"]:
            gw_row["mean"] = 5.0
    extras[0]["xpts_by_gw"][0]["std"] = 0.4
    extras[1]["xpts_by_gw"][0]["std"] = 2.4
    candidate = [row for row in squad if row["element"] not in {8, 9}] + extras
    universe = squad + extras
    context = _scoring_context(load_config(), 3)
    batch = ExactBatchScorer(universe, 3, scoring_context=context)
    expected = score_package(candidate, 3, changes=2, scoring_context=context)
    actual = batch.score_ids_compact([[int(row["element"]) for row in candidate]], changes=2)[0]
    assert _numeric_surface(actual) == _numeric_surface(expected)


def _python_skyline(metrics: np.ndarray) -> list[int]:
    out = []
    for i, row in enumerate(metrics):
        dominated = False
        for j, other in enumerate(metrics):
            if i == j:
                continue
            no_worse = (
                all(other[k] >= row[k] - 1e-12 for k in range(4))
                and other[4] <= row[4]
                and other[5] <= row[5] + 1e-12
            )
            strict = (
                any(other[k] > row[k] + 1e-12 for k in range(4))
                or other[4] < row[4]
                or other[5] < row[5] - 1e-12
            )
            if no_worse and strict:
                dominated = True
                break
        if not dominated:
            out.append(i)
    return out


def test_numpy_skyline_is_identical_to_canonical_dominance_relation():
    rng = np.random.default_rng(99)
    metrics = np.column_stack([
        rng.normal(size=(160, 4)),
        rng.integers(0, 3, size=160),
        rng.uniform(0.1, 30.0, size=160),
    ]).astype(np.float64)
    assert exact_skyline_indices(metrics).tolist() == _python_skyline(metrics)
