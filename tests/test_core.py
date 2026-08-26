
from src.engines.team_value import sell_cost


def test_official_snapshot_fetches_are_concurrent(monkeypatch):
    import threading
    import src.engine as engine

    barrier = threading.Barrier(3)

    def fake_get(path, retries=3):
        barrier.wait(timeout=1)
        return {"path": path}, {"status": "LIVE", "retries": retries}

    monkeypatch.setattr(engine, "get_json", fake_get)
    out = engine._parallel_official_get([
        ("one", "one/", 3), ("two", "two/", 2), ("three", "three/", 1),
    ])
    assert set(out) == {"one", "two", "three"}
    assert out["two"][1]["retries"] == 2
from src.models.optimizer import legal_counts

def test_sell_value():
    assert sell_cost(78,75)==76
    assert sell_cost(74,75)==74
    assert sell_cost(75,75)==75

def test_legal_counts():
    players=[]
    for i in range(2):players.append({"position":"GK","team":i})
    for i in range(5):players.append({"position":"DEF","team":10+i})
    for i in range(5):players.append({"position":"MID","team":20+i})
    for i in range(3):players.append({"position":"FWD","team":30+i})
    assert legal_counts(players)
