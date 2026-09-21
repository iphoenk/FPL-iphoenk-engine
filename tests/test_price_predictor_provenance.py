from src.runtime_v6.domains.acquisition.adapters import collect_price_predictor


def test_v6_price_predictor_is_verified_official_fpl_product_not_local_model():
    source = {
        "id": "official_price_predictor",
        "name": "Official FPL Price Predictor",
        "adapter": "official_price_predictor",
        "category": "market",
        "critical": True,
        "independence_group": "official_fpl",
        "entity_scopes": ["PLAYER", "TEAM"],
        "derived_from": "official_fpl.bootstrap",
        "fields": [
            "id",
            "web_name",
            "team",
            "element_type",
            "now_cost",
            "selected_by_percent",
            "transfers_in_event",
            "transfers_out_event",
            "price_change_percent",
            "price_change_hourly_rate",
            "price_change_projections",
            "price_change_locked_until",
            "price_change_calibrating",
        ],
    }
    upstream = {
        "health": "GREEN",
        "effective_state": "LIVE_CHANGED",
        "official": {
            "bootstrap": {
                "elements": [
                    {
                        "id": 1,
                        "web_name": "Player",
                        "team": 1,
                        "element_type": 3,
                        "now_cost": 75,
                        "selected_by_percent": "10.0",
                        "transfers_in_event": 100,
                        "transfers_out_event": 50,
                        "price_change_percent": 101.0,
                        "price_change_hourly_rate": 10,
                        "price_change_projections": [
                            {"offset": 0, "projected_percent": 105.0, "likelihood": 5}
                        ],
                        "price_change_locked_until": None,
                        "price_change_calibrating": False,
                    }
                ]
            }
        },
    }

    payload = collect_price_predictor(source, upstream)

    assert payload["health"] == "GREEN"
    assert payload["source_name"] == "Official FPL Price Change Predictor"
    assert payload["semantic_class"] == "UPSTREAM_MODEL_SIGNAL"
    assert payload["authority_class"] == "OFFICIAL_FPL_MODEL"
    assert payload["model_author"] == "OFFICIAL_FPL"
    assert payload["predictor_official_status"] == "VERIFIED_OFFICIAL_FPL_PRODUCT"
    assert payload["independent_official_product_evidence"] is True
    assert payload["authority"]["official_fpl_predictor_product_verified"] is True
    assert payload["governance"]["may_be_described_as_official_fpl_predictor_product"] is True
    assert payload["governance"]["v6_authors_prediction"] is False
