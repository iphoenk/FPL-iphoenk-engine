from __future__ import annotations

from src.runtime_v6.domains.report_plane.official_gw_history import official_event_context

DEADLINE = "2026-10-24T10:00:00Z"


def _event(**kw):
    return {"id": 8, "deadline_time": DEADLINE, "finished": False, "data_checked": False, **kw}


def _fx(fid, h, a, *, finished=False, event=8, kickoff="2026-10-25T14:00:00Z"):
    return {"id": fid, "event": event, "team_h": h, "team_a": a, "finished": finished, "kickoff_time": kickoff}


def _ctx(event, fixtures, as_of="2026-10-26T00:00:00Z"):
    return official_event_context(event, fixtures, as_of=as_of)


def test_finished_true_checked_false_is_pending_not_final():
    r = _ctx(_event(finished=True, data_checked=False), [_fx(1, 1, 2, finished=True), _fx(2, 3, 4, finished=True)])
    assert r["status"] == "PENDING_CHECK" and r["checked"] is False


def test_finished_and_checked_is_final():
    r = _ctx(_event(finished=True, data_checked=True), [_fx(1, 1, 2, finished=True)])
    assert r["status"] == "FINAL" and r["checked"] is True


def test_partial_finality_is_not_final():
    r = _ctx(_event(), [_fx(1, 1, 2, finished=True), _fx(2, 3, 4)])
    assert r["status"] == "PARTIAL_FINALITY" and r["coverage"]["finished"] == 1 and r["coverage"]["fixtures"] == 2


def test_postponed_fixture_is_listed_and_excluded_from_finality():
    r = _ctx(_event(finished=True, data_checked=True),
             [_fx(1, 1, 2, finished=True), {"id": 9, "event": None, "kickoff_time": None, "team_h": 5, "team_a": 6}])
    assert r["postponed_fixture_ids"] == [9] and r["fixture_ids"] == [1] and r["status"] == "FINAL"


def test_blank_gameweek_valid_empty_differs_from_failed_fetch():
    assert _ctx(_event(), [])["status"] == "BLANK_GAMEWEEK"
    failed = _ctx(_event(), None)
    assert failed["status"] == "UNAVAILABLE" and failed["coverage"]["status"] == "FETCH_FAILED"
    assert failed["coverage"]["fixtures"] is None  # unknown, not zero


def test_double_gameweek_keeps_two_partitions_for_the_team():
    r = _ctx(_event(), [_fx(1, 1, 2), _fx(2, 3, 1)])
    assert r["fixture_ids"] == [1, 2] and r["double_gameweek_team_ids"] == [1]
    assert r["team_fixture_counts"]["1"] == 2


def test_facts_observed_after_the_deadline_are_not_prospective():
    after = _ctx(_event(), [_fx(1, 1, 2)], as_of="2026-10-26T00:00:00Z")
    before = _ctx(_event(), [_fx(1, 1, 2)], as_of="2026-10-23T00:00:00Z")
    assert after["observation_class"] == "RETROSPECTIVE_POST_DEADLINE_FACTS"
    assert before["observation_class"] == "PROSPECTIVE_BEFORE_DEADLINE"
    assert _ctx(_event(), [_fx(1, 1, 2)], as_of="not-a-time")["observation_class"] == "UNKNOWN"


def test_timezone_of_as_of_does_not_change_fixture_ids_or_classification():
    fixtures = [_fx(1, 1, 2, kickoff="2026-10-25T23:30:00Z"), _fx(2, 3, 4, kickoff="2026-10-26T00:30:00Z")]
    wib = _ctx(_event(), fixtures, as_of="2026-10-26T07:00:00+07:00")
    uk = _ctx(_event(), fixtures, as_of="2026-10-26T00:00:00+00:00")
    assert wib["fixture_ids"] == uk["fixture_ids"] == [1, 2]
    assert wib["observation_class"] == uk["observation_class"]


def test_corrupt_rows_are_isolated_and_mark_coverage_partial():
    rows = [_fx(1, 1, 2), {"event": 8}, "junk", _fx(2, 3, 4, event=7), _fx(1, 1, 2)]
    r = _ctx(_event(), rows)
    assert r["fixture_ids"] == [1]
    reasons = sorted(x["reason"] for x in r["rejected_rows"])
    assert reasons == ["DUPLICATE_FIXTURE_ID", "MALFORMED_ROW", "MALFORMED_ROW", "WRONG_EVENT"]
    assert r["coverage"]["status"] == "PARTIAL"
