from src.engines.v12_cache_operational import (
    LAYERS,
    plan_cache_behavior,
    validate_actual_behavior,
)


def same(state):
    return {layer: state for layer in LAYERS}


def test_unchanged_reuses_all_layers():
    plan = plan_cache_behavior("UNCHANGED")
    assert set(plan.reusable_layers) == set(LAYERS)
    assert validate_actual_behavior(plan, actual_states=same("HIT")).correctness == "PASS"


def test_price_only_and_mini_league_operational_states():
    price = plan_cache_behavior("PRICE_ONLY", affected_dependency_keys=["finance:team"])
    assert price.expected["Stage2"] == "HIT"
    assert price.expected["MC"] == "PARTIAL_INVALIDATION"
    mini = plan_cache_behavior("MINI_LEAGUE_ONLY", affected_dependency_keys=["league:overlay"])
    assert mini.expected["Stage2"] == "HIT"
    assert mini.expected["MC"] == "HIT"
    assert mini.expected["scenario"] == "PARTIAL_INVALIDATION"


def test_owned_availability_and_material_projection():
    owned = plan_cache_behavior("OWNED_AVAILABILITY", affected_dependency_keys=["player:1"])
    assert owned.expected["Stage2"] == "HIT"
    assert owned.expected["P1.7"] == "MISS"
    projection = plan_cache_behavior("MATERIAL_PROJECTION", affected_dependency_keys=["player:1:xmins"])
    assert set(projection.expected.values()) == {"MISS"}


def test_fixture_model_schema_result_bonus_and_set_piece_fact_hard_invalidate():
    for change in (
        "FIXTURE",
        "MODEL_VERSION",
        "SCHEMA_VERSION",
        "OFFICIAL_RESULT",
        "BONUS_FINALIZATION",
        "SET_PIECE_FACT",
    ):
        plan = plan_cache_behavior(change, affected_dependency_keys=["x"])
        assert set(plan.expected.values()) == {"MISS"}


def test_current15_and_captain_change_preserve_only_public_stage2():
    for change in ("CURRENT15_CHANGE", "CAPTAIN_CHANGE", "VICE_CAPTAIN_CHANGE"):
        plan = plan_cache_behavior(change, affected_dependency_keys=["owner"])
        assert plan.expected["Stage2"] == "HIT"
        assert all(plan.expected[layer] == "MISS" for layer in LAYERS if layer != "Stage2")


def test_scenario_hit_and_miss_are_explicit_operational_classes():
    hit = plan_cache_behavior("P4_SCENARIO_HIT")
    assert hit.matrix_class == "UNCHANGED"
    assert set(hit.expected.values()) == {"HIT"}
    miss = plan_cache_behavior("P4_SCENARIO_MISS", affected_dependency_keys=["scenario:base"])
    assert set(miss.expected.values()) == {"MISS"}


def test_perf_f_case_aliases_resolve_without_rewriting_frozen_matrix():
    no_change = plan_cache_behavior("NO_CHANGE")
    assert no_change.matrix_class == "UNCHANGED"
    assert set(no_change.expected.values()) == {"HIT"}
    availability = plan_cache_behavior(
        "OUR15_AVAILABILITY",
        affected_dependency_keys=["player:1:availability"],
    )
    assert availability.matrix_class == "OWNED_AVAILABILITY"
    assert availability.expected["Stage2"] == "HIT"
    assert availability.expected["P1.7"] == "MISS"


def test_wrong_hit_is_correctness_fail():
    plan = plan_cache_behavior("MODEL_VERSION", affected_dependency_keys=["model"])
    actual = same("MISS")
    actual["MC"] = "HIT"
    result = validate_actual_behavior(plan, actual_states=actual)
    assert result.correctness == "CORRECTNESS_FAIL"


def test_partial_reuse_of_affected_key_is_correctness_fail():
    plan = plan_cache_behavior("PRICE_ONLY", affected_dependency_keys=["finance:team"])
    actual = dict(plan.expected)
    result = validate_actual_behavior(
        plan,
        actual_states=actual,
        reused_dependency_keys={"MC": ["finance:team"]},
    )
    assert result.correctness == "CORRECTNESS_FAIL"


def test_over_invalidation_is_performance_not_correctness_failure():
    plan = plan_cache_behavior("UNCHANGED")
    actual = same("HIT")
    actual["Stage2"] = "MISS"
    result = validate_actual_behavior(plan, actual_states=actual)
    assert result.correctness == "PASS"
    assert result.performance == "PERFORMANCE_OVER_INVALIDATION"


def test_uncertain_scope_fails_closed_to_miss():
    plan = plan_cache_behavior("PRICE_ONLY", affected_dependency_keys=[], scope_certain=False)
    assert set(plan.expected.values()) == {"MISS"}


def test_uncertain_scope_sentinel_is_full_miss_even_if_caller_marks_scope_certain():
    for scope_certain in (False, True):
        plan = plan_cache_behavior(
            "UNCERTAIN_SCOPE",
            affected_dependency_keys=["unknown"],
            scope_certain=scope_certain,
        )
        assert set(plan.expected.values()) == {"MISS"}


def test_all_required_operational_classes_resolve():
    required = (
        "UNCHANGED",
        "PRICE_ONLY",
        "MINI_LEAGUE_ONLY",
        "OWNED_AVAILABILITY",
        "CURRENT15_CHANGE",
        "CAPTAIN_CHANGE",
        "VICE_CAPTAIN_CHANGE",
        "MATERIAL_PROJECTION",
        "FIXTURE",
        "MODEL_VERSION",
        "SCHEMA_VERSION",
        "OFFICIAL_RESULT",
        "BONUS_FINALIZATION",
        "SET_PIECE_FACT",
        "P4_SCENARIO_HIT",
        "P4_SCENARIO_MISS",
        "UNCERTAIN_SCOPE",
    )
    for change in required:
        plan = plan_cache_behavior(change, affected_dependency_keys=["test:key"])
        assert set(plan.expected) == set(LAYERS)
