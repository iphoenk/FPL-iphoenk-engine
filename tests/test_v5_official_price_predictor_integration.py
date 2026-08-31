from __future__ import annotations

from datetime import datetime, timezone

from src.v5.price_service import build_price_snapshot
from src.v5.price_squeeze import annotate_comparator, attach_watchlist_price_evidence, price_squeeze
from src.v5.price_trajectory import canonical_contract, normalise_projections, trajectory_eta


def _player(element: int, **overrides):
    row = {
        "id": element,
        "first_name": f"First{element}",
        "second_name": f"Second{element}",
        "web_name": f"P{element}",
        "team": 1 + (element % 5),
        "element_type": 1 + (element % 4),
        "now_cost": 50 + (element % 10),
        "selected_by_percent": "10.0",
        "transfers_in": 10000,
        "transfers_in_event": 1000,
        "transfers_out": 5000,
        "transfers_out_event": 500,
        "price_change_percent": 92.4,
        "price_change_hourly_rate": 3.7,
        "price_change_projections": [
            {"offset": 0, "projected_percent": 107.1, "likelihood": 4},
            {"offset": 1, "projected_percent": 120.0, "likelihood": 5},
            {"offset": 2, "projected_percent": 130.0, "likelihood": 5},
        ],
        "price_change_locked_until": None,
        "price_change_calibrating": False,
    }
    row.update(overrides)
    return row


def _bootstrap(count: int = 40):
    return {
        "total_players": 10_000_000,
        "elements": [_player(i) for i in range(1, count + 1)],
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"},
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
    }


def test_v5_uses_same_canonical_provider_contract_as_v3_v4():
    contract = canonical_contract()
    assert contract["model_id"] == "official_price_radar_v3"
    assert contract["source_authority"] == [
        "OFFICIAL_FPL",
        "OFFICIAL_MIRROR",
        "EXTERNAL_PREDICTOR",
        "INTERNAL_MODEL",
    ]
    assert contract["likelihood_preserved_raw"] is True
    assert contract["threshold_is_official_rule"] is False
    assert contract["no_intra_cycle_crossing_eta"] is True


def test_v5_price_snapshot_resolves_all15_and_preserves_official_fields():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    snapshot = build_price_snapshot(
        _bootstrap(),
        owned_ids=range(1, 16),
        now=now,
        observed_at=now,
        transport_health={"status": "LIVE", "fetched_at": now.isoformat()},
    )
    prices = snapshot["prices"]
    assert prices["source"] == "OFFICIAL_FPL"
    assert prices["health"]["status"] == "PASS"
    assert prices["all15_coverage"] == {"expected": 15, "resolved": 15, "complete": True}
    assert len(prices["all15_actionable_price_radar"]) == 15
    row = prices["players"][0]
    assert row["current_progress_percent"] == 92.4
    assert row["projection_offset_0_percent"] == 107.1
    assert row["projection_offset_0_likelihood"] == 4
    assert row["official_projections"][0]["likelihood"] == 4
    assert all("likelihood_label" not in item for item in row["official_projections"])
    assert row["trajectory_eta_hours"] is None
    assert row["trajectory_predicted_change_deadline"] is None
    assert prices["governance"]["authenticated_session_required"] is False
    assert prices["governance"]["ui_scraping"] is False


def test_compatibility_facade_does_not_restore_invented_likelihood_or_crossing_eta():
    projections = normalise_projections([
        {"offset": 0, "projected_percent": 107.1, "likelihood": 5},
        {"offset": 1, "projected_percent": 120.0, "likelihood": 5},
    ])
    assert projections[0] == {"offset": 0, "projected_percent": 107.1, "likelihood": 5}
    assert "likelihood_label" not in projections[0]
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    assert trajectory_eta(now, 92.4, 3.7) == (None, None)


def test_exact_all20_watchlist_price_evidence_is_bound_after_selection_without_rerank():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    snapshot = build_price_snapshot(
        _bootstrap(), owned_ids=range(1, 16), now=now, observed_at=now, transport_health={"status": "LIVE"}
    )
    ids = iter(range(16, 36))
    watchlist = {
        "status": "READY",
        "positions": {
            position: [{"element": next(ids), "name": f"X{rank}", "rank": rank} for rank in range(1, 6)]
            for position in ("GK", "DEF", "MID", "FWD")
        },
        "governance": {},
    }
    before = {
        position: [row["element"] for row in rows]
        for position, rows in watchlist["positions"].items()
    }
    enriched = attach_watchlist_price_evidence(watchlist, snapshot, range(1, 16))
    after = {
        position: [row["element"] for row in rows]
        for position, rows in enriched["positions"].items()
    }
    assert before == after
    assert enriched["price_evidence_coverage"] == {"expected": 20, "resolved": 20, "complete": True}
    assert all(
        row["price_evidence"]["source"] == "OFFICIAL_FPL"
        for rows in enriched["positions"].values()
        for row in rows
    )
    assert enriched["governance"]["price_evidence_may_not_change_membership"] is True
    assert enriched["governance"]["price_evidence_may_not_change_rank"] is True


def test_price_squeeze_models_01_02_with_governed_sell_value():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    bootstrap = _bootstrap(2)
    bootstrap["elements"] = [
        _player(
            10,
            now_cost=54,
            price_change_percent=-90.0,
            price_change_projections=[
                {"offset": 0, "projected_percent": -105.0, "likelihood": -4},
                {"offset": 1, "projected_percent": -110.0, "likelihood": -4},
                {"offset": 2, "projected_percent": -120.0, "likelihood": -5},
            ],
        ),
        _player(
            20,
            now_cost=53,
            price_change_percent=90.0,
            price_change_projections=[
                {"offset": 0, "projected_percent": 105.0, "likelihood": 4},
                {"offset": 1, "projected_percent": 110.0, "likelihood": 4},
                {"offset": 2, "projected_percent": 120.0, "likelihood": 5},
            ],
        ),
    ]
    snapshot = build_price_snapshot(bootstrap, now=now, observed_at=now, transport_health={"status": "LIVE"})
    by_id = {row["element_id"]: row for row in snapshot["prices"]["players"]}
    squeeze = price_squeeze(
        by_id[10],
        by_id[20],
        {
            "element": 10,
            "purchase_cost": 50,
            "sell_cost": 52,
            "finance_source": "initial_squad_baseline",
            "finance_exact": False,
        },
        1,
    )
    scenarios = {row["scenario"]: row for row in squeeze["scenarios"]}
    assert scenarios["BASE"]["affordable"] is True
    assert scenarios["BOTH_SQUEEZE_0_1"]["affordable"] is False
    assert scenarios["BOTH_SQUEEZE_0_1"]["sell_value_impact"] == -1
    assert scenarios["BOTH_SQUEEZE_0_1"]["structural_flexibility_impact"] == -2
    assert scenarios["BOTH_SQUEEZE_0_2"]["required_extra_budget"] >= 2
    assert squeeze["price_only_execution_authorized"] is False


def test_challenger_price_overlay_never_changes_football_classification():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    bootstrap = _bootstrap(25)
    snapshot = build_price_snapshot(bootstrap, now=now, observed_at=now, transport_health={"status": "LIVE"})
    comparator = {
        "candidate_count": 2,
        "pairs": [
            {
                "owned": {"element": 10, "name": "Owned"},
                "challenger": {"element": 20, "name": "Target"},
                "classification": "LEAN_TRANSFER",
                "horizons": {"5": {"raw_gain": 3.0}},
            }
        ],
        "governance": {},
    }
    team = {
        "finance": {
            "bank": 2,
            "players": [
                {
                    "element": 10,
                    "now_cost": 50,
                    "purchase_cost": 50,
                    "sell_cost": 50,
                    "finance_source": "initial_squad_baseline",
                    "finance_exact": False,
                }
            ],
        }
    }
    enriched = annotate_comparator(
        comparator,
        price=snapshot,
        team=team,
        transfer_state={"free_transfers": 1, "injury_news_risk_acceptable": False},
    )
    pair = enriched["pairs"][0]
    assert pair["classification"] == "LEAN_TRANSFER"
    assert pair["execution_timing"]["price_only_execution_authorized"] is False
    assert pair["execution_timing"]["classification_mutated_by_price"] is False
    assert enriched["governance"]["price_changes_timing_not_football_merit"] is True
