from src.engines.watchlist_public_sanitize import sanitize


def _candidate(element: int, position: str) -> dict:
    return {
        "element": element,
        "name": f"P{element}",
        "team": "Club",
        "team_id": 1,
        "position": position,
        "now_cost": 50,
        "price": 5.0,
        "status": "a",
        "ownership_pct": 5.0,
        "projection_confidence": "HIGH",
        "xmins": {},
        "horizons": {},
        "direct_replacement_context": {},
        "evidence_coverage": 1.0,
        "critical_dimension_score": 1.0,
        "dss_score": 80.0,
        "rank": 1,
        "lifecycle": "KEEP",
        "reasons": [],
        "risks": [],
        "action": "WATCH",
        "price_risk": {"official_progress_pct": 10.0},
    }


def _official(element: int) -> dict:
    return {
        "element": element,
        "name": f"P{element}",
        "element_id": element,
        "player_name": f"P{element}",
        "current_price": 5.0,
        "ownership_percent": 5.0,
        "confirmed_price_change": None,
        "current_progress_percent": 10.0,
        "price_change_hourly_rate": 20.0,
        "projection_offset_0_percent": 20.0,
        "projection_offset_0_likelihood": 1,
        "projection_offset_0_at": "2026-09-01T06:00:00+07:00",
        "projection_offset_1_percent": 30.0,
        "projection_offset_1_likelihood": 1,
        "projection_offset_1_at": "2026-09-02T06:00:00+07:00",
        "projection_offset_2_percent": 40.0,
        "projection_offset_2_likelihood": 2,
        "projection_offset_2_at": "2026-09-03T06:00:00+07:00",
        "direction": "RISE",
        "next_official_price_update_at": "2026-09-01T06:00:00+07:00",
        "eta_to_next_price_update_seconds": 3600,
        "eta_human": "1 jam 0 menit",
        "predicted_change_cycle": "NONE",
        "predicted_change_at": None,
        "model_urgency": "LOW",
        "source": "OFFICIAL_FPL",
        "freshness_seconds": 10,
        "confidence": "HIGH",
        "fallback_reason": None,
        "evidence_state": "AVAILABLE",
        "narrative": "Belum ada proyeksi resmi yang melewati ambang model.",
        "sell_value_relevance": "NOT_OWNED",
        "action": "Pantau; sinyal harga adalah overlay dan tidak menggantikan keputusan sepak bola/DSS.",
    }


def test_all_20_published_watchlist_rows_keep_full_governed_official_price_evidence():
    positions = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    position_order = ["GK", "DEF", "MID", "FWD"]
    for element in range(1, 21):
        positions[position_order[(element - 1) // 5]].append(_candidate(element, position_order[(element - 1) // 5]))
    payload = {
        "status": "READY",
        "screening_contract": "FULL_DSS_SCREEN_V1",
        "positions": positions,
        "candidate_audit": {},
        "public_contract": {},
    }
    price_index = {element: _official(element) for element in range(1, 21)}
    result = sanitize(payload, price_index)
    summary = result["price_evidence_summary"]
    assert summary["published_watchlist_rows"] == 20
    assert summary["official_price_evidence_rows"] == 20
    assert summary["complete"] is True
    rows = [row for group in result["positions"].values() for row in group]
    required = {
        "current_price", "ownership_percent", "current_progress_percent",
        "projection_offset_0_percent", "projection_offset_0_likelihood",
        "direction", "next_official_price_update_at", "eta_human",
        "predicted_change_cycle", "model_urgency", "source", "freshness_seconds",
        "action", "narrative",
    }
    assert len(rows) == 20
    assert all(required.issubset(row["price_risk"]) for row in rows)
    assert all(row["price_risk"]["source"] == "OFFICIAL_FPL" for row in rows)


def test_missing_canonical_price_evidence_is_visible_as_incomplete_not_silently_omitted():
    payload = {
        "status": "READY",
        "screening_contract": "FULL_DSS_SCREEN_V1",
        "positions": {"MID": [_candidate(7, "MID")]},
    }
    result = sanitize(payload, {})
    assert result["price_evidence_summary"]["complete"] is False
    assert result["positions"]["MID"][0]["price_risk"]["source"] == "LEGACY_COMPATIBILITY_FALLBACK"
