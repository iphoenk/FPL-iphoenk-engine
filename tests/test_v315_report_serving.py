import json

from src.engines import report_materializer


def test_report_artifact_registry_requires_15_owned_and_20_watchlist():
    registry = report_materializer.load_registry()
    contract = registry["consumer_contract"]
    assert contract["owned_count"] == 15
    assert contract["watchlist_total"] == 20
    assert contract["watchlist_per_position"] == 5
    assert contract["watchlist_positions"] == ["GK", "DEF", "MID", "FWD"]
    assert registry["governance"]["report_materializer_may_reduce_fields_but_may_not_make_new_football_decisions"] is True


def test_watchlist_summary_is_exactly_5_per_position_and_excludes_owned(monkeypatch, tmp_path):
    monkeypatch.setattr(report_materializer, "DATA", tmp_path)
    owned = [{"element": i} for i in range(1, 16)]
    (tmp_path / "team.json").write_text(json.dumps({"team_value_ledger": owned}), encoding="utf-8")
    positions = {}
    element = 100
    for pos in ("GK", "DEF", "MID", "FWD"):
        rows = []
        for rank in range(1, 6):
            element += 1
            rows.append({
                "element": element,
                "rank": rank,
                "lifecycle": "NEW",
                "name": f"{pos} {rank}",
                "team": "X",
                "position": pos,
                "price": 5.0,
                "projection_confidence": "MEDIUM",
                "xmins": {"expected_minutes": 75, "start_probability": 0.85},
                "horizons": {"3": {"mean": 10}, "5": {"mean": 16}, "10": {"mean": 31}, "15": {"mean": 45}},
                "reasons": ["starter security / xMins kuat"],
                "risks": ["role belum penuh"],
                "price_risk": {"risk_direction": "RISE", "urgency": "LOW", "official_progress_pct": 10},
                "action": "WATCH",
            })
        positions[pos] = rows
    summary = report_materializer._watchlist_summary({"status": "READY", "screening_contract": "FULL_DSS_SCREEN_V1", "positions": positions})
    assert summary["count"] == 20
    assert summary["per_position"] == 5
    assert all(len(summary["positions"][p]) == 5 for p in positions)
    assert not ({x["element"] for x in owned} & {x["element"] for rows in summary["positions"].values() for x in rows})


def test_finance_uses_current_totals_not_purchase_baseline():
    finance = report_materializer._finance({
        "totals": {"market_value": 997, "sell_value": 995, "itb": 5},
        "team_value_ledger": [],
    })
    assert finance == {
        "squad_market_value": 99.7,
        "itb": 0.5,
        "total_team_value": 100.2,
        "squad_sell_value": 99.5,
        "spendable_value": 100.0,
    }
