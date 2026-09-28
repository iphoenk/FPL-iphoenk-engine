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


def test_fixture_model_schema_and_set_piece_fact_hard_invalidate():
    for change in ("FIXTURE", "MODEL_VERSION", "SCHEMA_VERSION", "SET_PIECE_FACT"):
        plan = plan_cache_behavior(change, affected_dependency_keys=["x"])
        assert set(plan.expected.values()) == {"MISS"}


def test_current15_and_captain_change_preserve_only_public_stage2():
    for change in ("CURRENT15_CHANGE", "CAPTAIN_CHANGE", "VICE_CAPTAIN_CHANGE"):
        plan = plan_cache_behavior(change, affected_dependency_keys=["owner"])
        assert plan.expected["Stage2"] == "HIT"
        assert all(plan.expected[layer] == "MISS" for layer in LAYERS if layer != "Stage2")


def test_scenario_hit_and_miss():
    hit = plan_cache_behavior("UNCHANGED")
    assert hit.expected["scenario"] == "HIT"
    miss = plan_cache_behavior("XMINS", affected_dependency_keys=["player:2:xmins"])
    assert miss.expected["scenario"] == "MISS"


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
