import json

from src.engines import watchlist_public_sanitize


def test_sanitize_removes_internal_price_health_code():
    payload = {
        "status": "READY",
        "screening_contract": "FULL_DSS_SCREEN_V1",
        "positions": {
            "MID": [{
                "element": 10,
                "price_risk": {
                    "official_progress_pct": 91.0,
                    "prediction_source": "TRAJECTORY_RATE",
                    "official_projection_health": "SUSPECT_STATIC_OFFSET0",
                },
            }]
        },
    }
    clean = watchlist_public_sanitize.sanitize(payload)
    row = clean["positions"]["MID"][0]
    assert "official_projection_health" not in row["price_risk"]
    assert row["price_risk"]["projection_confidence_note"] == "proyeksi waktu perubahan harga belum cukup yakin"
    assert "SUSPECT_STATIC_OFFSET0" not in json.dumps(clean, ensure_ascii=False)
    assert clean["screening_contract"] == "FULL_DSS_SCREEN_V1"


def test_non_ready_watchlist_cannot_claim_ready_screening_contract():
    payload = {
        "status": "BLOCKED",
        "screening_contract": "FULL_DSS_SCREEN_V1",
        "positions": {"GK": [], "DEF": [], "MID": [], "FWD": []},
    }
    clean = watchlist_public_sanitize.sanitize(payload)
    assert clean["screening_contract"] == "FULL_DSS_SCREEN_INCOMPLETE_V1"
    assert clean["public_contract"]["ready_contract_requires_ready_status"] is True
