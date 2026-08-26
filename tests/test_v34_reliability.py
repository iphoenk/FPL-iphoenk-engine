from src.engines.snapshot_meta import snapshot_id, changes
from src.engines.price_radar import classify
from src.version import ENGINE_VERSION, SCHEMA_VERSION


def test_release():
    assert ENGINE_VERSION == "3.12.0"
    assert SCHEMA_VERSION == 41


def test_snapshot_id_stable():
    assert snapshot_id({"b":2,"a":1}) == snapshot_id({"a":1,"b":2})


def test_change_log():
    assert changes({"rank":10},{"rank":9},["rank"]) == [{"field":"rank","old":10,"new":9}]


def test_price_noise_filter():
    assert classify(1000,0.1,100)["confidence"] == "NOISE"
    assert classify(30000,2.0,100000)["confidence"] == "HIGH"
