from src.runtime_v3 import incremental_reuse


def _snapshot(score=0, generated_at="2026-08-29T00:00:00+00:00", started=True):
    return {
        "generated_at": generated_at,
        "endpoint_health": {"event_live": {"latency_ms": 123}},
        "phase": {"planning_gw": 3, "scoring_gw": 2},
        "bootstrap": {
            "teams": [{"id": 1, "name": "A", "strength_attack_home": 100, "strength_attack_away": 100, "strength_defence_home": 100, "strength_defence_away": 100}],
            "elements": [{"id": 10, "element_type": 3, "team": 1, "web_name": "P", "now_cost": 50, "status": "a", "selected_by_percent": "1.0", "starts": 1, "minutes": 90, "expected_goals": "0.1", "expected_assists": "0.1", "bonus": 0, "saves": 0, "chance_of_playing_next_round": 100}],
        },
        "fixtures": [{"event": 2, "kickoff_time": "2026-08-29T00:00:00Z", "started": started, "finished": False, "team_h": 1, "team_a": 2, "team_h_score": score, "team_a_score": 0}],
        "event_live": {"elements": [{"id": 10, "stats": {"bps": 12}}]},
    }


def test_prediction_semantic_fingerprint_ignores_nonmaterial_live_chatter():
    left = incremental_reuse._semantic_json("prediction", "official_snapshot.json", _snapshot())
    right = incremental_reuse._semantic_json("prediction", "official_snapshot.json", _snapshot(generated_at="2026-08-29T00:01:00+00:00", started=False))
    assert left == right


def test_prediction_semantic_fingerprint_changes_on_material_score_change():
    left = incremental_reuse._semantic_json("prediction", "official_snapshot.json", _snapshot(score=0))
    right = incremental_reuse._semantic_json("prediction", "official_snapshot.json", _snapshot(score=1))
    assert left != right


def test_live_reuse_is_explicit_compute_positive_and_prediction_only():
    registry = incremental_reuse._registry()
    policy = registry["policy"]
    assert policy["live_reuse_requires_explicit_service_opt_in"] is True
    assert policy["disable_when_current_scoring_fixture_live"] is True
    assert policy["reuse_is_invalidated_by_source_tree_change"] is True
    assert policy["reuse_only_when_avoided_compute_exceeds_fingerprint_cost"] is True
    assert policy["cheap_decision_consumers_execute_and_validate_directly"] is True
    services = registry["services"]
    assert {name for name, spec in services.items() if spec.get("allow_during_live") is True} == {"prediction"}
    assert "lineup_governance" in services
    assert services["lineup_governance"].get("allow_during_live") is not True
    assert "challenger" not in services
    assert "watchlist" not in services
    assert "reporting" not in services
    assert "report_materializer" not in services
    assert all("src/" in spec.get("inputs", []) for spec in services.values())


def test_source_tree_digest_is_available_for_reuse_invalidation():
    digest = incremental_reuse._digest_path("prediction", "src/")
    assert isinstance(digest, str)
    assert len(digest) == 64
