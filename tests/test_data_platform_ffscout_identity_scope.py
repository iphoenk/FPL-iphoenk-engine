from __future__ import annotations

from src.runtime_v6.entity_scope import entity_scopes_for_source, load_entity_scope_policy
from src.runtime_v6.registry import load_registry


def test_ffscout_public_player_scope_requires_deterministic_embedded_identity():
    policy = load_entity_scope_policy()
    source = {"id": "ffscout", "category": "fpl_model_reference"}

    assert entity_scopes_for_source(source, policy) == ["FEED", "PLAYER"]
    assert policy["governance"]["ffscout_player_identity_requires_stable_native_id_before_player_scope"] is True
    assert policy["governance"]["ffscout_public_premierleague_media_code_is_stable_identity_evidence"] is True


def test_ffscout_registry_acquires_public_team_news_without_members_area():
    registry = load_registry()
    source = next(row for row in registry["sources"] if row["id"] == "ffscout")
    requests = {row["id"]: row for row in source.get("requests") or []}

    assert requests["home"]["url"] == "https://www.fantasyfootballscout.co.uk/"
    assert requests["team_news"]["url"] == "https://www.fantasyfootballscout.co.uk/team-news/"
    assert source["acquisition_kind"] == "generic_http"
    assert source["content_hash_dedup"] is True
    assert all("members.fantasyfootballscout.co.uk" not in str(row.get("url") or "") for row in requests.values())
