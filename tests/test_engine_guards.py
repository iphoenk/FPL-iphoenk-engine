from src.engines.reliability import validate_snapshot, leakage_allowed
from src.models.projection import xmins_distribution, project_points
from src.models.optimizer import evaluate_package
from src.models.price_model import price_pressure

def test_leakage_gate():
    assert leakage_allowed("2026-08-28T17:00:00Z","2026-08-28T17:30:00Z")
    assert not leakage_allowed("2026-08-28T18:00:00Z","2026-08-28T17:30:00Z")
    assert not leakage_allowed(None,"2026-08-28T17:30:00Z")

def test_snapshot_validator():
    s={
        "schema_version":32,
        "engine_version":"3.3.1",
        "generated_at":"x",
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
        "files":{k:k for k in ("team","live","prices","health","universe","chips")},
        "meta":{},
    }
    assert validate_snapshot(s)["ok"]

def test_projection_distribution():
    p={"status":"a","minutes":90,"starts":1,"element_type":3}
    d=xmins_distribution(p); assert 0<=d["start_probability"]<=1 and d["expected_minutes"]<=90
    assert project_points(p)["projected_points"]>=0

def test_price_probability_bounds():
    r=price_pressure({"selected_by_percent":"10","transfers_in_event":1000,"transfers_out_event":100},100000)
    assert 0<=r["rise_probability"]<=1
