from __future__ import annotations

from src.runtime_v6.entity_scope import entity_scopes_for_source, load_entity_scope_policy


def test_ffscout_public_player_scope_requires_deterministic_embedded_identity():
    policy = load_entity_scope_policy()
    source = {"id": "ffscout", "category": "fpl_model_reference"}

    assert entity_scopes_for_source(source, policy) == ["FEED", "PLAYER"]
    assert policy["governance"]["ffscout_player_identity_requires_stable_native_id_before_player_scope"] is True
    assert policy["governance"]["ffscout_public_premierleague_media_code_is_stable_identity_evidence"] is True
