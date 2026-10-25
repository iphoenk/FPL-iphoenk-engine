"""F03 characterization: provider identity joins are anchored on the official FPL code, never on names."""
from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.domains.identity.verified_crosswalks import enrich_verified_external_crosswalks
from src.runtime_v6.domains.observability.health import _coverage_health


def _imap(*players: tuple[str, int, int, str]) -> dict:
    """players: (canonical_id, official_code, element_id, display name)."""
    return {
        "canonical_player_count": len(players),
        "mappings": {
            cid: {"official_fpl_element_id": element, "official_code": code, "display_name": name, "links": {}}
            for cid, code, element, name in players
        },
    }


def _cfg(*rows: dict, source_id: str = "understat") -> dict:
    return {"sources": {source_id: {"players": list(rows), "verification_method": "TEST_VERIFIED"}}}


def _enrich(imap, cfg, source_id: str = "understat"):
    return enrich_verified_external_crosswalks(imap, {source_id: {"source_id": source_id}}, cfg)


def _link(out, cid, source_id="understat"):
    return out["mappings"][cid]["links"].get(source_id)


def test_duplicate_names_different_clubs_map_only_the_configured_code():
    imap = _imap(("a", 111, 1, "Gabriel"), ("b", 222, 2, "Gabriel"))
    out = _enrich(imap, _cfg({"official_fpl_code": 222, "source_native_id": 900}))
    assert _link(out, "a") is None
    assert _link(out, "b")["source_native_id"] == 900
    assert _link(out, "b")["provenance"]["name_matching_used"] is False
    assert out["coverage"]["understat"]["mapped_player_count"] == 1


def test_club_move_does_not_change_the_code_anchored_link():
    before = _imap(("a", 111, 1, "Player"))
    after = deepcopy(before)
    after["mappings"]["a"]["team_id"] = 14  # moved club; identity is the code, not the club
    cfg = _cfg({"official_fpl_code": 111, "source_native_id": 77})
    assert _link(_enrich(before, cfg), "a")["source_native_id"] == _link(_enrich(after, cfg), "a")["source_native_id"] == 77


def test_reused_element_id_in_a_new_season_does_not_inherit_the_old_players_link():
    # Season N+1 reuses element_id 5 for a different player with a different code.
    new_season = _imap(("x", 999, 5, "New Player"))
    stale_cfg = _cfg({"official_fpl_code": 111, "source_native_id": 42, "official_fpl_element_id": 5})
    out = _enrich(new_season, stale_cfg)
    assert _link(out, "x") is None
    assert out["coverage"]["understat"]["mapped_player_count"] == 0


def test_unicode_name_is_irrelevant_to_the_join():
    imap = _imap(("g", 333, 7, "Groß"))
    out = _enrich(imap, _cfg({"official_fpl_code": 333, "source_native_id": "Gross-001"}))
    assert _link(out, "g")["source_native_id"] == "Gross-001"
    # A provider row for "Gross" (ASCII) with no configured code is not matched to "Groß".
    imap2 = _imap(("g", 333, 7, "Groß"))
    assert _link(_enrich(imap2, _cfg({"official_fpl_code": 444, "source_native_id": 1})), "g") is None


def test_unmapped_external_player_with_a_similar_name_is_not_fuzzy_mapped():
    imap = _imap(("a", 111, 1, "Mohamed Salah"))
    out = _enrich(imap, _cfg({"official_fpl_code": 0, "source_native_id": 5}, {"official_fpl_code": None, "source_native_id": 6}))
    assert _link(out, "a") is None
    assert out["governance"]["player_crosswalk_name_matching"] is False


def test_conflicting_existing_link_fails_closed_and_is_not_overwritten():
    imap = _imap(("a", 111, 1, "Player"))
    imap["mappings"]["a"]["links"]["understat"] = {"source_native_id": 10, "status": "VERIFIED_MANUAL"}
    out = _enrich(imap, _cfg({"official_fpl_code": 111, "source_native_id": 99}))
    assert _link(out, "a")["source_native_id"] == 10
    assert out["coverage"]["understat"]["conflicting_existing_link_count"] == 1
    assert out["coverage"]["understat"]["fail_closed_on_conflict"] is True


def test_duplicate_official_code_fails_closed_for_every_holder():
    imap = _imap(("a", 111, 1, "One"), ("b", 111, 2, "Two"))
    out = _enrich(imap, _cfg({"official_fpl_code": 111, "source_native_id": 5}))
    assert _link(out, "a") is None and _link(out, "b") is None
    assert out["coverage"]["understat"]["duplicate_canonical_code_count"] == 1


def test_missing_coverage_ratio_is_not_read_as_full_coverage():
    assert _coverage_health({}, {"coverage": {"coverage_ratio": None}, "availability": "AVAILABLE"}) != "GREEN"
    assert _coverage_health({}, {"coverage": {"coverage_ratio": 1.0}}) == "GREEN"
    assert _coverage_health({}, {"coverage": {"coverage_ratio": 0.4}}) == "AMBER"
