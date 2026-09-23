from __future__ import annotations

from copy import deepcopy

from src.engines import v12_stage2_derived_cache as cache


def _inputs():
    return {
        "bootstrap": {
            "events": [{"id": 6, "is_next": True}],
            "elements": [{"id": 1, "team": 1, "element_type": 3}],
            "teams": [{"id": 1, "name": "A"}],
        },
        "strength": {"teams": [{"team_id": 1, "attack": 1.0}]},
        "planning_gw": 6,
        "historical_prior": {"model": "prior", "players": {}},
        "player_features_payload": {"players": {}},
        "player_match_rows": [],
        "opponent_history_rows": [],
        "opponent_history_scope": "PUBLIC",
    }


def test_stage2_derived_cache_hit_is_exact_and_builder_runs_once(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(cache.STAGE2_DERIVED_CACHE_ENV, str(tmp_path))
    calls = {"count": 0}

    def builder():
        calls["count"] += 1
        return {
            "model": "canonical",
            "planning_gw": 6,
            "players": [{"element": 1, "xpts_by_gw": [{"gw": 6, "mean": 5.0}]}],
        }

    kwargs = _inputs()
    cold, cold_proof = cache.load_or_build_stage2_projections(
        **kwargs, builder=builder
    )
    warm, warm_proof = cache.load_or_build_stage2_projections(
        **kwargs, builder=builder
    )

    assert cold == warm
    assert calls["count"] == 1
    assert cold_proof["cache_hit"] is False
    assert cold_proof["cache_miss"] is True
    assert cold_proof["cache_write"] is True
    assert warm_proof["status"] == "HIT"
    assert warm_proof["cache_hit"] is True
    assert warm_proof["cache_miss"] is False
    assert warm_proof["mathematical_owner_changed"] is False
    assert warm_proof["private_current15_in_key"] is False


def test_stage2_derived_cache_material_input_change_forces_miss(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(cache.STAGE2_DERIVED_CACHE_ENV, str(tmp_path))
    calls = {"count": 0}

    def builder():
        calls["count"] += 1
        return {
            "model": "canonical",
            "planning_gw": 6,
            "players": [{"element": 1, "xpts_by_gw": [{"gw": 6, "mean": calls["count"]}]}],
        }

    first = _inputs()
    cache.load_or_build_stage2_projections(**first, builder=builder)
    changed = deepcopy(first)
    changed["strength"]["teams"][0]["attack"] = 1.125
    _, proof = cache.load_or_build_stage2_projections(
        **changed, builder=builder
    )
    assert calls["count"] == 2
    assert proof["cache_hit"] is False
    assert proof["cache_miss"] is True


def test_stage2_derived_cache_corrupt_payload_is_rejected_fail_closed(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(cache.STAGE2_DERIVED_CACHE_ENV, str(tmp_path))
    calls = {"count": 0}

    def builder():
        calls["count"] += 1
        return {
            "model": "canonical",
            "planning_gw": 6,
            "players": [{"element": 1, "xpts_by_gw": [{"gw": 6, "mean": 5.0}]}],
        }

    kwargs = _inputs()
    cache.load_or_build_stage2_projections(**kwargs, builder=builder)
    files = list(tmp_path.rglob("*.pkl"))
    assert len(files) == 1
    files[0].write_bytes(b"corrupt")

    _, proof = cache.load_or_build_stage2_projections(
        **kwargs, builder=builder
    )
    assert calls["count"] == 2
    assert proof["cache_corrupt_reject"] is True
    assert proof["cache_miss"] is True
    assert proof["cache_write"] is True
