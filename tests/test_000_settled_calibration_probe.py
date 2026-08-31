from __future__ import annotations

import json

from src.engines.v4_backtest_store import deadline_snapshot_path
from src.engines.v4_reconciliation_truth import actual_by_element
from src.engines.v4_validation import promotion_gate, reconcile_prediction_snapshot
from src.sources.official_fpl import get_json
from src.utils import read_json


def test_probe_finalized_fixture_calibration() -> None:
    gw = 2
    bootstrap, _ = get_json("bootstrap-static/", retries=2)
    fixtures, _ = get_json("fixtures/", retries=2)
    live, _ = get_json(f"event/{gw}/live/", retries=2)
    snapshot = read_json(deadline_snapshot_path(gw), {})
    assert snapshot, "GW2 immutable deadline snapshot missing"

    event_fixtures = [f for f in (fixtures or []) if int(f.get("event") or -1) == gw]
    team_fixtures: dict[int, list[dict]] = {}
    for fixture in event_fixtures:
        for key in ("team_h", "team_a"):
            team = int(fixture.get(key) or 0)
            if team:
                team_fixtures.setdefault(team, []).append(fixture)
    settled_teams = {
        team for team, rows in team_fixtures.items()
        if rows and all(row.get("finished") is True for row in rows)
    }
    by_id = {int(row["id"]): row for row in (bootstrap or {}).get("elements", [])}
    actual_all = actual_by_element(live or {})
    actual = {
        element: row
        for element, row in actual_all.items()
        if element in by_id and int(by_id[element].get("team") or 0) in settled_teams
    }
    report = reconcile_prediction_snapshot(
        snapshot,
        actual,
        event=gw,
        deadline=snapshot.get("deadline_time"),
    )
    metrics = report.get("metrics") or {}
    gate = promotion_gate(report, minimum_n=300)
    print("SETTLED_CALIBRATION_PROBE=" + json.dumps({
        "gw": gw,
        "snapshot_model_version": snapshot.get("model_version"),
        "settled_team_count": len(settled_teams),
        "settled_teams": sorted(settled_teams),
        "fixture_count": len(event_fixtures),
        "finished_fixture_count": sum(f.get("finished") is True for f in event_fixtures),
        "unfinished_fixture_ids": [f.get("id") for f in event_fixtures if f.get("finished") is not True],
        "actual_elements": len(actual),
        "metrics": metrics,
        "promotion_gate": gate,
    }, ensure_ascii=False, sort_keys=True))
    assert False, "temporary settled calibration probe"
