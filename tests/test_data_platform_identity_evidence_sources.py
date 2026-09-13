from __future__ import annotations

from src.runtime_v6.ffscout_public import METHOD as FFSCOUT_METHOD
from src.runtime_v6.identity_coverage import load_identity_evidence_config


def test_ffscout_public_evidence_is_exact_and_name_free() -> None:
    config = load_identity_evidence_config()
    ffscout = config["direct_runtime_evidence"]["ffscout"]

    assert ffscout["verification_method"] == FFSCOUT_METHOD
    assert ffscout["canonical_anchor"] == "official_fpl.bootstrap.elements.code"
    assert ffscout["namespace"] == "resources.premierleague.com_player_media_code"
    assert ffscout["may_directly_promote_to_v6_join"] is True
    assert ffscout["public_content_only"] is True
    assert ffscout["member_paywalled_stats_acquired"] is False
    assert ffscout["name_matching_used"] is False
    assert ffscout["fuzzy_matching_used"] is False
    assert config["active_runtime_crosswalk"]["ffscout"] == FFSCOUT_METHOD


def test_reep_overlay_remains_discovery_only() -> None:
    config = load_identity_evidence_config()
    assert config["governance"]["reep_v1_overlay_is_discovery_only"] is True
    assert config["reep_v1"]["roles"]["statmuse_pl"]["may_directly_promote_to_v6_join"] is False
    assert config["reep_v1"]["roles"]["opta_numeric"]["may_directly_promote_to_v6_join"] is False
