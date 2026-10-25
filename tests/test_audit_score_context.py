"""E01: golden score cases for the single V12 scoring oracle (score_entry). No second scoring engine."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.v12_official_public_scoring import score_entry

CASES = json.loads((Path(__file__).parent / "fixtures" / "audit_20261025" / "score_cases.json").read_text(encoding="utf-8"))["cases"]


def _run(case):
    kw = dict(case["kwargs"])
    live = {int(k): v for k, v in case["live_points"].items()}
    teams = {int(k): v for k, v in (kw.get("player_teams") or {}).items()} or None
    minutes = {int(k): v for k, v in (kw.get("live_minutes") or {}).items()} or None
    finished = set(kw["finished_teams"]) if "finished_teams" in kw else None
    return score_entry(case["record"], live, published_standing=kw.get("published_standing"),
                       player_teams=teams, finished_teams=finished, live_minutes=minutes)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_golden_case(case):
    result = _run(case)
    for key, expected in case["expected"].items():
        assert result.get(key) == expected, f"{case['name']}: {key}"


def test_unknown_hit_never_becomes_zero():
    case = next(c for c in CASES if c["name"] == "unknown_hit_is_null_not_zero")
    result = _run(case)
    assert result["hit"] is None and result["net_points"] is None and result["live_overall_points"] is None
    assert result["gross_points"] == 41


def test_gross_net_captain_and_bench_are_separate_numbers():
    result = _run(next(c for c in CASES if c["name"] == "basic_gross_net_captain_bench_separate"))
    assert result["gross_points"] != result["net_points"]
    assert result["captain_points"] == 16 and result["bench_raw_points"] == 6
    assert result["gross_points"] == 41  # captain and bench are parts of / alongside gross, not deductions


def test_pre_and_post_published_autosub_multipliers_give_identical_gross():
    pre = _run(next(c for c in CASES if c["name"] == "autosub_pre_published_multipliers_applied_once"))
    post = _run(next(c for c in CASES if c["name"] == "autosub_post_published_is_idempotent"))
    assert pre["gross_points"] == post["gross_points"] == 43
    assert pre["calculated_autosub_applied"] == 1 and post["calculated_autosub_applied"] == 0


def test_the_oracle_never_reports_final():
    for case in CASES:
        assert _run(case)["status"] in {"CALCULATED", "PROVISIONAL", "UNAVAILABLE"}


def test_unconfirmed_effective_captain_is_unknown_not_zero():
    # Captain benched by an official sub and nobody carries a x2 multiplier yet: captain_points is None.
    record = json.loads(json.dumps(next(c for c in CASES if c["name"] == "basic_gross_net_captain_bench_separate")["record"]))
    for row in record["picks"]:
        if row["element_id"] == 10:
            row["multiplier"] = 0
        if row["element_id"] == 12:
            row["multiplier"] = 1
    record["automatic_subs"] = [{"element_out": 10, "element_in": 12}]
    live = {i: 1 for i in range(1, 16)}
    result = score_entry(record, live)
    assert result["captain_points"] is None and result["effective_captain_id"] is None
