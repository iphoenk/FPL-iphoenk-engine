from src.engines.v12_cache_operational import LAYERS, plan_cache_behavior
from src.engines.v12_p6_runtime import _full_recompute_states, classify_change


def test_runtime_classifier_prefers_known_private_and_public_scopes():
    assert classify_change([], ["personal/current_team.json"])[0] == "CURRENT15_CHANGE"
    assert classify_change([], ["personal/memberships.json"])[0] == "MINI_LEAGUE_ONLY"
    assert (
        classify_change(
            ["data/v6/mini_leagues/9477/standings.json"],
            [],
        )[0]
        == "MINI_LEAGUE_ONLY"
    )
    assert classify_change(["data/v6/price/latest.json"], [])[0] == "PRICE_ONLY"


def test_runtime_classifier_never_guesses_mixed_or_broad_change():
    change, keys, certain = classify_change(
        ["data/v6/official_fpl/bootstrap-static.json"],
        ["personal/current_team.json"],
    )
    assert change == "UNCERTAIN_SCOPE"
    assert keys
    assert certain is False
    plan = plan_cache_behavior(
        change,
        affected_dependency_keys=keys,
        scope_certain=certain,
    )
    assert set(plan.expected.values()) == {"MISS"}


def test_full_recompute_is_reported_as_over_invalidation_not_fake_hit():
    plan = plan_cache_behavior(
        "PRICE_ONLY",
        affected_dependency_keys=["price"],
    )
    actual = _full_recompute_states(plan.expected)
    assert actual["Stage2"] == "MISS"
    assert actual["MC"] == "MISS"
    assert set(actual) == set(LAYERS)
