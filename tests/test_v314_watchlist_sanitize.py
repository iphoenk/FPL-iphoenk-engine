import json

from src.engines import watchlist_public_sanitize


def test_sanitize_removes_internal_price_health_code_from_public_row():
    payload = {
        "status": "READY",
        "screening_contract": "FULL_DSS_SCREEN_V1",
        "positions": {
            "MID": [{
                "element": 10,
                "dimensions": {"role": {"status": "PROXY"}},
                "package_context": {"package_id": "1:1->10"},
                "underlying": {"xg90": 0.2, "sources": {"xg90": "position_prior"}},
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
    assert "dimensions" not in row
    assert "package_context" not in row
    assert "sources" not in row["underlying"]
    assert "SUSPECT_STATIC_OFFSET0" not in json.dumps(clean["positions"], ensure_ascii=False)
    assert clean["candidate_audit"]["10"]["price_risk"]["official_projection_health"] == "SUSPECT_STATIC_OFFSET0"
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
