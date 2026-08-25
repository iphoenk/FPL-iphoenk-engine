from src.engine import native_entry_summary
from src.engines.reliability import validate_snapshot


def test_native_entry_summary_keeps_current_official_fields():
    entry={
        "id":3462711,
        "current_event":1,
        "summary_overall_points":71,
        "summary_overall_rank":462166,
        "summary_event_points":71,
        "summary_event_rank":462167,
        "last_deadline_bank":5,
        "last_deadline_value":995,
        "last_deadline_total_transfers":0,
    }
    out=native_entry_summary(entry,"2026-08-25T17:00:00+00:00")
    assert out["summary_overall_rank"]==462166
    assert out["summary_overall_points"]==71
    assert out["last_deadline_bank"]==5
    assert out["fetched_at"]=="2026-08-25T17:00:00+00:00"


def test_schema32_snapshot_requires_native_entry_payload():
    snapshot={
        "schema_version":32,
        "engine_version":"3.3.1",
        "generated_at":"2026-08-25T17:00:00+00:00",
        "phase":{},
        "entry":{
            "id":3462711,
            "current_event":1,
            "summary_overall_points":71,
            "summary_overall_rank":462166,
            "summary_event_points":71,
            "summary_event_rank":462167,
            "fetched_at":"2026-08-25T17:00:00+00:00",
        },
        "team_summary":{"itb":5,"market_value":995,"sell_value":995},
        "files":{"team":"x","live":"x","prices":"x","health":"x","universe":"x","chips":"x"},
        "meta":{},
    }
    assert validate_snapshot(snapshot)["ok"]
    snapshot["entry"]={}
    result=validate_snapshot(snapshot)
    assert not result["ok"]
    assert "missing_entry:fetched_at" in result["errors"]
