from __future__ import annotations

from src.runtime_v6.domains.report_plane.league_prefetch import (
    build_league_membership_context,
    fetch_all_standings,
)

ICON = 9477
OBS = "2026-10-25T10:00:00Z"


def _row(entry: int, rank: int, last_rank: int | None = None) -> dict:
    return {"entry": entry, "player_name": f"Manager {entry}", "entry_name": f"Team {entry}",
            "rank": rank, "last_rank": last_rank, "total": 1000 - rank, "event_total": 40}


def _page(first: int, count: int, *, has_next: bool, league_id: int = ICON) -> dict:
    return {"league": {"id": league_id},
            "standings": {"has_next": has_next, "results": [_row(first + i, first + i) for i in range(count)]}}


def _ctx(pages, **kw):
    return build_league_membership_context(pages, season="2026/27", league_id=ICON, gw=8, observed_at=OBS, **kw)


def test_50_plus_8_are_58_unique_members_and_complete():
    ctx = _ctx([_page(1, 50, has_next=True), _page(51, 8, has_next=False)])
    assert ctx["version"] == "FPL_LEAGUE_CONTEXT_V1"
    assert ctx["coverage"]["status"] == "COMPLETE" and ctx["coverage"]["members_collected"] == 58
    assert len({m["entry_id"] for m in ctx["members"]}) == 58
    assert ctx["coverage"]["pages_collected"] == 2 and ctx["coverage"]["reasons"] == []


def test_duplicate_page_loop_is_partial_and_not_counted_twice():
    page1 = _page(1, 50, has_next=True)
    ctx = _ctx([page1, dict(page1), dict(page1)])
    assert ctx["coverage"]["status"] == "PARTIAL"
    assert "DUPLICATE_PAGE" in ctx["coverage"]["reasons"]
    assert ctx["coverage"]["members_collected"] == 50


def test_empty_final_page_is_complete_but_empty_page_before_end_is_partial():
    ok = _ctx([_page(1, 50, has_next=True), {"league": {"id": ICON}, "standings": {"has_next": False, "results": []}}])
    assert ok["coverage"]["status"] == "COMPLETE" and ok["coverage"]["members_collected"] == 50
    bad = _ctx([_page(1, 50, has_next=True), {"league": {"id": ICON}, "standings": {"has_next": True, "results": []}}])
    assert bad["coverage"]["status"] == "PARTIAL" and "EMPTY_PAGE_BEFORE_END" in bad["coverage"]["reasons"]


def test_missing_second_page_is_partial_not_complete():
    ctx = _ctx([_page(1, 50, has_next=True)])
    assert ctx["coverage"]["status"] == "PARTIAL" and ctx["coverage"]["members_collected"] == 50
    assert ctx["coverage"]["reasons"] == ["NEXT_PAGE_MISSING"]
    assert ctx["coverage"]["expected_members"] is None


def test_55_of_58_is_partial_even_when_pages_end():
    # A last page that ends the listing with fewer rows is complete for what FPL returned;
    # but an interrupted listing (55 rows, has_next still true) is never complete.
    ctx = _ctx([_page(1, 50, has_next=True), _page(51, 5, has_next=True)])
    assert ctx["coverage"]["status"] == "PARTIAL" and ctx["coverage"]["members_collected"] == 55


def test_current_membership_is_never_presented_as_historical():
    ctx = _ctx([_page(1, 50, has_next=True), _page(51, 8, has_next=False)])
    assert ctx["membership_basis"] == "CURRENT_AT_OBSERVED_AT"
    assert ctx["membership_change_basis"] == "NO_BASELINE_EVIDENCE"
    assert ctx["joins"] is None and ctx["leavers"] is None


def test_rank_ties_joins_and_leavers_against_explicit_baseline():
    tied = {"league": {"id": ICON}, "standings": {"has_next": False, "results": [
        _row(1, 1), _row(2, 2), _row(3, 2), _row(4, 4)]}}
    ctx = _ctx([tied], baseline_member_ids={1, 2, 9})
    assert ctx["rank_ties"] == {"2": [2, 3]}
    assert ctx["joins"] == [3, 4] and ctx["leavers"] == [9]
    assert ctx["membership_change_basis"] == "EXPLICIT_BASELINE"


def test_other_league_page_is_never_mixed_into_icon():
    ctx = _ctx([_page(1, 50, has_next=True), _page(900, 10, has_next=False, league_id=1234)])
    assert ctx["coverage"]["status"] == "PARTIAL" and "LEAGUE_MISMATCH" in ctx["coverage"]["reasons"]
    assert all(m["entry_id"] < 900 for m in ctx["members"])


def test_missing_optional_history_keeps_official_standings():
    row = _row(7, 3)
    row.pop("last_rank")
    ctx = _ctx([{"league": {"id": ICON}, "standings": {"has_next": False, "results": [row]}}])
    member = ctx["members"][0]
    assert member["entry_id"] == 7 and member["rank"] == 3 and member["last_rank"] is None


class _Client:
    def __init__(self, pages):
        self.pages, self.calls = pages, 0

    def classic_standings(self, league_id, page):
        self.calls += 1
        return {"status": "LIVE", "http_status": 200, "payload": {"standings": self.pages[min(page, len(self.pages)) - 1]["standings"]}}


def _league():
    return {"league_id": ICON, "league_kind": "classic", "league_name": "ICON+ League"}


def test_fetch_all_standings_stops_on_pagination_loop_and_dedupes():
    page1 = _page(1, 50, has_next=True)
    client = _Client([page1])  # every page returns the same rows with has_next=true
    state = fetch_all_standings(client, _league())
    assert state["complete"] is False
    assert len(state["rows"]) == 50 and len({r["entry_id"] for r in state["rows"]}) == 50
    assert client.calls <= 3
    assert state["failed_pages"][-1]["status"] == "DUPLICATE_PAGE"


def test_fetch_all_standings_complete_for_50_plus_8():
    client = _Client([_page(1, 50, has_next=True), _page(51, 8, has_next=False)])
    state = fetch_all_standings(client, _league())
    assert state["complete"] is True and len(state["rows"]) == 58 and state["failed_pages"] == []


def test_fetch_all_standings_empty_page_before_end_is_incomplete():
    client = _Client([_page(1, 50, has_next=True), {"league": {"id": ICON}, "standings": {"has_next": True, "results": []}}])
    state = fetch_all_standings(client, _league())
    assert state["complete"] is False and state["failed_pages"][-1]["status"] == "EMPTY_PAGE_BEFORE_END"
