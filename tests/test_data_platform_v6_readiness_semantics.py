from src.runtime_v6.health import _consumer_readiness_summary


def test_readiness_summary_exposes_source_native_and_join_dimensions():
    source = {
        "readiness": {
            "operational": "GREEN",
            "data": "GREEN",
            "join": "RED",
        }
    }
    summary = _consumer_readiness_summary([source])
    assert summary["source_native_readiness_overall"] == "GREEN"
    assert summary["join_readiness_overall"] == "RED"
    assert summary["consumer_readiness_overall"] == "GREEN"
