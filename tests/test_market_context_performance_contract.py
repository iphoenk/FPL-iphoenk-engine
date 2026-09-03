from __future__ import annotations

from src.engines import official_expansion, price_challenger_overlay


def test_empty_price_challenger_context_avoids_full_universe_deepcopy(monkeypatch) -> None:
    prices = {"players": [{"element": 1, "name": "Raya"}], "top_rise_risk": []}
    observations = {"observations": [], "cross_source": []}

    def forbidden_deepcopy(value):  # pragma: no cover - called only on regression
        raise AssertionError(f"empty challenger context must not deepcopy canonical price universe: {type(value)}")

    monkeypatch.setattr(price_challenger_overlay.copy, "deepcopy", forbidden_deepcopy)
    enriched, summary = price_challenger_overlay.apply_context(prices, observations)

    assert enriched["players"] == prices["players"]
    assert summary["fresh_observation_count"] == 0
    assert summary["matched_player_count"] == 0
    assert summary["official_fields_overridden"] is False
    assert summary["authority"] == "Official FPL"


def test_official_detail_policy_is_registry_owned_and_bounded() -> None:
    policy = official_expansion._detail_policy()

    assert policy["registry"] == "V3_OFFICIAL_DETAIL_POLICY_V1"
    assert policy["element_summary_max"] == 40
    assert 1 <= policy["element_summary_workers"] <= policy["element_summary_max"]
    assert policy["policy"]["bounded_parallel_element_summary_fetch"] is True
    assert policy["policy"]["preserve_detail_id_order"] is True
    assert policy["policy"]["same_official_endpoints"] is True
    assert policy["policy"]["same_detail_universe"] is True
    assert policy["policy"]["no_decision_authority_change"] is True


def test_element_summary_parallel_fetch_preserves_requested_order(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class FakeExecutor:
        def __init__(self, *, max_workers, thread_name_prefix):
            observed["max_workers"] = max_workers
            observed["thread_name_prefix"] = thread_name_prefix

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def map(self, fn, values):
            observed["values"] = list(values)
            return [fn(value) for value in observed["values"]]

    def fake_fetch(eid):
        return int(eid), {"fixtures": [{"id": int(eid)}], "history": [], "history_past": []}, {"status": "LIVE"}

    monkeypatch.setattr(official_expansion, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr(official_expansion, "_fetch_element_summary", fake_fetch)
    monkeypatch.setattr(official_expansion, "DETAIL_WORKERS", 3)

    details, health = official_expansion._element_summaries([9, 3, 7, 1])

    assert observed["max_workers"] == 3
    assert observed["values"] == [9, 3, 7, 1]
    assert list(details) == ["9", "3", "7", "1"]
    assert list(health) == ["9", "3", "7", "1"]
    assert all(row["status"] == "LIVE" for row in health.values())
