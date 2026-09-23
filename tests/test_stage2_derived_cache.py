from __future__ import annotations

import json

from src.engines.v12_stage2_derived_cache import (
    load_or_build_foundation,
    load_or_build_projections,
    stage2_public_input_key,
)


def _bootstrap():
    return {
        "events": [
            {"id": 5, "finished": True},
            {"id": 6, "finished": False, "is_next": True},
        ],
        "teams": [
            {"id": 1, "name": "A", "short_name": "A"},
            {"id": 2, "name": "B", "short_name": "B"},
        ],
        "elements": [
            {
                "id": 10,
                "team": 1,
                "element_type": 3,
                "minutes": 450,
                "starts": 5,
                "status": "a",
                "chance_of_playing_next_round": 100,
                "now_cost": 75,
                "selected_by_percent": "10.0",
                "web_name": "P10",
                # Private/irrelevant-like noise must not enter the model key.
                "transfers_in_event": 999,
            }
        ],
    }


def _write_public_sources(root, marker="A"):
    for name in (
        "official_fpl",
        "vaastav_fpl",
        "understat",
        "statmuse",
        "rotowire",
    ):
        path = root / f"data/v6/normalized/sources/{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "source_health": "GREEN",
                    "normalization_status": "NORMALIZED",
                    "marker": marker,
                }
            ),
            encoding="utf-8",
        )


def _foundation_payload():
    return {
        "contract": "V12_ANALYTICS_FOUNDATION_V2",
        "status": "MATCH_FOUNDATION_READY",
        "stage1_full_foundation_ready": True,
        "historical_prior": {"model": None, "players": {}},
        "player_features_payload": {"players": {}},
        "player_match_rows": [],
        "opponent_history_rows": [],
        "opponent_history_scope": "CURRENT-SEASON ONLY",
    }


def test_stage2_public_key_ignores_private_runtime_files_but_tracks_public_sources(
    monkeypatch,
    tmp_path,
):
    cache = tmp_path / "cache"
    monkeypatch.setenv("V12_STAGE2_DERIVED_CACHE_DIR", str(cache))
    _write_public_sources(tmp_path, marker="A")
    bootstrap = _bootstrap()
    strength = {"teams": [{"team_id": 1}], "matchups": []}

    first = stage2_public_input_key(
        tmp_path,
        bootstrap=bootstrap,
        strength=strength,
        planning_gw=6,
    )

    private = tmp_path / "data/v6/personal/current_team.json"
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text(
        json.dumps(
            {
                "auth_state": "AUTH_EXPIRED",
                "bank": None,
                "players": [565],
            }
        ),
        encoding="utf-8",
    )
    second = stage2_public_input_key(
        tmp_path,
        bootstrap=bootstrap,
        strength=strength,
        planning_gw=6,
    )
    assert second == first

    private.write_text(
        json.dumps(
            {
                "auth_state": "AUTH_AVAILABLE",
                "bank": 2,
                "players": [124],
            }
        ),
        encoding="utf-8",
    )
    third = stage2_public_input_key(
        tmp_path,
        bootstrap=bootstrap,
        strength=strength,
        planning_gw=6,
    )
    assert third == first

    _write_public_sources(tmp_path, marker="B")
    changed = stage2_public_input_key(
        tmp_path,
        bootstrap=bootstrap,
        strength=strength,
        planning_gw=6,
    )
    assert changed != first


def test_stage2_foundation_and_projection_cache_reuse_exact_outputs(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "V12_STAGE2_DERIVED_CACHE_DIR",
        str(tmp_path / "cache"),
    )
    _write_public_sources(tmp_path)
    bootstrap = _bootstrap()
    strength = {"teams": [{"team_id": 1}], "matchups": []}
    calls = {"foundation": 0, "projection": 0}

    def foundation_builder(
        runtime_data_root,
        *,
        bootstrap,
        planning_gw,
        strength,
    ):
        del runtime_data_root, bootstrap, planning_gw, strength
        calls["foundation"] += 1
        return _foundation_payload()

    first_foundation, first_meta = load_or_build_foundation(
        tmp_path,
        bootstrap=bootstrap,
        strength=strength,
        planning_gw=6,
        builder=foundation_builder,
    )
    second_foundation, second_meta = load_or_build_foundation(
        tmp_path,
        bootstrap=bootstrap,
        strength=strength,
        planning_gw=6,
        builder=foundation_builder,
    )
    assert first_foundation == second_foundation
    assert first_meta["cache_hit"] is False
    assert second_meta["cache_hit"] is True
    assert calls["foundation"] == 1

    def projection_builder(
        bootstrap,
        strength,
        planning_gw,
        prior,
        **kwargs,
    ):
        del bootstrap, strength, prior, kwargs
        calls["projection"] += 1
        return {
            "model": "TEST",
            "planning_gw": planning_gw,
            "players": [{"element": 10, "mean": 5.0}],
        }

    first_projection, first_projection_meta = (
        load_or_build_projections(
            bootstrap=bootstrap,
            strength=strength,
            planning_gw=6,
            foundation=first_foundation,
            public_input_key=first_meta["cache_key"],
            builder=projection_builder,
        )
    )
    second_projection, second_projection_meta = (
        load_or_build_projections(
            bootstrap=bootstrap,
            strength=strength,
            planning_gw=6,
            foundation=first_foundation,
            public_input_key=first_meta["cache_key"],
            builder=projection_builder,
        )
    )
    assert first_projection == second_projection
    assert first_projection_meta["cache_hit"] is False
    assert second_projection_meta["cache_hit"] is True
    assert calls["projection"] == 1

    # Returned mappings are detached from disk cache state.
    second_projection["players"][0]["mean"] = 99.0
    third_projection, third_meta = load_or_build_projections(
        bootstrap=bootstrap,
        strength=strength,
        planning_gw=6,
        foundation=first_foundation,
        public_input_key=first_meta["cache_key"],
        builder=projection_builder,
    )
    assert third_meta["cache_hit"] is True
    assert third_projection["players"][0]["mean"] == 5.0
