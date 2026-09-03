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
    # Force an exact captain-mean tie with different variances; canonical max()
    # keeps the first starter in input order, so the compiled path must too.
    for row in squad[:2]:
        for gw_row in row["xpts_by_gw"]:
            gw_row["mean"] = 10.0
    squad[0]["xpts_by_gw"][0]["std"] = 0.5
    squad[1]["xpts_by_gw"][0]["std"] = 2.5
    context = _scoring_context(load_config(), 3)
    expected = score_package(squad, planning_gw=3, changes=1, scoring_context=context)
    compiled = CompiledPackageScorer(squad, 3, scoring_context=context)
    assert compiled.score(squad, changes=1) == expected
