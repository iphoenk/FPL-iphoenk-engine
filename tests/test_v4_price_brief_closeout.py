from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from src.engines.price_radar import _normalise_player, _raw_payload_hash, _served_evidence
from src.engines.v4_decision_arbitration import _attach_price_timing
from src.engines.v4_price_context import build_market_context, refresh_price_context
from src.services.prediction_model_cache import semantic_fingerprint


def _player(element: int = 1, **overrides) -> dict:
    row = {
        "id": element,
        "first_name": "Test",
        "second_name": "Player",
        "web_name": f"P{element}",
        "team": 1,
        "element_type": 3,
        "now_cost": 55,
        "selected_by_percent": "10.0",
        "transfers_in": 1000,
        "transfers_in_event": 100,
        "transfers_out": 500,
        "transfers_out_event": 20,
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


def _bootstrap(*players: dict) -> dict:
    return {
        "elements": list(players),
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"},
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
        "total_players": 10_000_000,
    }


def _normalise(player: dict, *, now: datetime | None = None) -> dict:
    current = now or datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    return _normalise_player(
        player,
        position_by_type={1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"},
        observed_at=current,
        now=current,
        raw_payload_hash=_raw_payload_hash([player]),
    )


def test_missing_runtime_dependency_materializes_blocked_health(tmp_path):
    result = refresh_price_context(raw={}, team={"squad": []}, data_dir=tmp_path)

    assert result["health"]["status"] == "BLOCKED"
    assert result["health"]["reason"] == "RUNTIME_DEPENDENCY_UNAVAILABLE"
    assert result["players"] == []
    assert result["provenance"]["network_refetch"] is False

    persisted = json.loads((tmp_path / "prices.json").read_text(encoding="utf-8"))
    assert persisted["health"]["status"] == "BLOCKED"
    assert persisted["players"] == []


def test_prematerialized_fallback_is_partial_with_provenance(tmp_path):
    observed = datetime.now(timezone.utc).isoformat()
    mirror_player = _player(element=101, price_change_projections=[
        {"offset": 0, "projected_percent": 107.1, "likelihood": 4},
        {"offset": 1, "projected_percent": 120.0, "likelihood": 5},
        {"offset": 2, "projected_percent": 130.0, "likelihood": 5},
    ])
    raw = {
        "endpoint_health": {"bootstrap": {"status": "FAIL"}},
        "price_predictor_fallbacks": {
            "OFFICIAL_MIRROR": {
                "bootstrap": _bootstrap(mirror_player),
                "observed_at": observed,
                "health": {"status": "LIVE_MIRROR"},
                "reason": "OFFICIAL_PRIMARY_UNAVAILABLE",
            }
        },
    }
    result = refresh_price_context(
        raw=raw,
        team={"squad": [{"element": 101}]},
        data_dir=tmp_path,
    )

    assert result["source"] == "OFFICIAL_MIRROR"
    assert result["health"]["status"] == "PARTIAL"
    assert result["health"]["reason"] == "OFFICIAL_PRIMARY_UNAVAILABLE"
    assert result["provenance"]["fallback_used"] is True
    assert result["provenance"]["selected_source"] == "OFFICIAL_MIRROR"
    assert result["provenance"]["observed_at"] is not None
    assert result["players"][0]["source"] == "OFFICIAL_MIRROR"
    assert result["players"][0]["fallback_reason"] == "OFFICIAL_PRIMARY_UNAVAILABLE"
    assert result["players"][0]["projection_offset_0_likelihood"] == 4
    assert result["players"][0]["confidence"] == "MEDIUM"


def test_fresh_official_cannot_be_overwritten_by_lower_authority(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    official = _player(element=1, now_cost=60)
    mirror = _player(element=1, now_cost=40)
    raw = {
        "generated_at": now,
        "official": {"bootstrap": _bootstrap(official)},
        "endpoint_health": {"bootstrap": {"status": "LIVE"}},
        "price_predictor_fallbacks": {
            "OFFICIAL_MIRROR": {
                "bootstrap": _bootstrap(mirror),
                "observed_at": now,
                "health": {"status": "LIVE_MIRROR"},
                "reason": "SHOULD_NOT_OVERRIDE_FRESH_OFFICIAL",
            }
        },
    }
    result = refresh_price_context(
        raw=raw,
        team={"squad": [{"element": 1}]},
        data_dir=tmp_path,
    )

    assert result["source"] == "OFFICIAL_FPL"
    assert result["health"]["status"] == "PASS"
    assert result["players"][0]["now_cost"] == 60
    assert result["provenance"]["fallback_used"] is False


def test_real_zero_stale_and_schema_drift_remain_distinct():
    now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)

    zero = build_market_context(
        _bootstrap(_player(price_change_percent=0, price_change_hourly_rate=0, price_change_projections=[
            {"offset": 0, "projected_percent": 0, "likelihood": 0},
            {"offset": 1, "projected_percent": 0, "likelihood": 0},
            {"offset": 2, "projected_percent": 0, "likelihood": 0},
        ])),
        observed_at=now,
        now=now,
        transport_health={"status": "LIVE"},
    )
    assert zero["health"]["status"] == "PASS"
    assert zero["players"][0]["evidence_state"] == "REAL_ZERO"
    assert zero["players"][0]["current_progress_percent"] == 0

    stale = build_market_context(
        _bootstrap(_player()),
        observed_at=now - timedelta(minutes=20),
        now=now,
        transport_health={"status": "LIVE"},
    )
    assert stale["health"]["status"] == "STALE"
    assert stale["players"][0]["evidence_state"] == "STALE"

    broken = _player()
    broken.pop("now_cost")
    schema = build_market_context(
        _bootstrap(broken),
        observed_at=now,
        now=now,
        transport_health={"status": "LIVE"},
    )
    assert schema["health"]["status"] == "FAIL"
    assert schema["players"][0]["evidence_state"] in {"FIELD_MISSING", "SCHEMA_CHANGED"}
    assert schema["players"][0]["current_price"] is None


def test_football_valid_transfer_may_accelerate_only_when_price_squeeze_is_material():
    outgoing = _normalise(_player(
        element=10,
        now_cost=54,
        price_change_percent=-90.0,
        price_change_projections=[
            {"offset": 0, "projected_percent": -105.0, "likelihood": -4},
            {"offset": 1, "projected_percent": -110.0, "likelihood": -4},
            {"offset": 2, "projected_percent": -120.0, "likelihood": -5},
        ],
    ))
    incoming = _normalise(_player(
        element=20,
        now_cost=53,
        price_change_percent=90.0,
        price_change_projections=[
            {"offset": 0, "projected_percent": 105.0, "likelihood": 4},
            {"offset": 1, "projected_percent": 110.0, "likelihood": 4},
            {"offset": 2, "projected_percent": 120.0, "likelihood": 5},
        ],
    ))
    prices = {"health": {"status": "PASS"}, "players": [outgoing, incoming]}
    team = {
        "team_value_ledger": [{"element": 10, "purchase_cost": 50, "sell_cost": 52}],
        "totals": {"itb": 1},
    }
    transfer = {
        "action": "CHANGE",
        "execution_authorized": True,
        "replacements": 1,
        "out": [{"element": 10, "position": "MID"}],
        "in": [{"element": 20, "position": "MID"}],
    }

    enriched = _attach_price_timing(transfer, prices, team)

    assert enriched["action"] == "CHANGE"
    assert enriched["execution_authorized"] is True
    assert enriched["price_context"]["affordability_or_optionality_risk"] is True
    assert enriched["price_context"]["execution_timing"] == "EARLY_EXECUTION_SUPPORTED"
    assert enriched["price_context"]["price_only_execution_authorized"] is False
    assert enriched["price_context"]["alternatives_evaluated_by_optimizer_package"] is True


def test_visible_price_copy_is_natural_and_does_not_leak_internal_identifiers():
    row = _normalise(_player(element=7))
    visible = _served_evidence(row, owned=True)
    text = " ".join(str(visible.get(key) or "") for key in ("narrative", "action"))

    assert "bukan jaminan" in text or "Pantau" in text
    for forbidden in (
        "PRICE_FOMO",
        "STRUCTURAL_PRICE_PROTECTION",
        "NEXT_UPDATE_RISK",
        "execution_authorized",
    ):
        assert forbidden not in text


def test_price_predictor_changes_do_not_invalidate_xpts_cache_but_model_inputs_do():
    base = _bootstrap(_player(element=11, now_cost=55))
    base["teams"] = [{
        "id": 1,
        "strength_defence_home": 1200,
        "strength_defence_away": 1180,
        "strength_overall_home": 1210,
        "strength_overall_away": 1190,
    }]
    base["events"] = []

    price_only = deepcopy(base)
    price_only["elements"][0].update({
        "price_change_percent": 99.9,
        "price_change_hourly_rate": 8.4,
        "price_change_projections": [
            {"offset": 0, "projected_percent": 118.0, "likelihood": 5},
            {"offset": 1, "projected_percent": 132.0, "likelihood": 5},
            {"offset": 2, "projected_percent": 145.0, "likelihood": 5},
        ],
        "price_change_locked_until": "2026-09-01T00:00:00Z",
        "price_change_calibrating": True,
    })

    assert semantic_fingerprint(base, [], None) == semantic_fingerprint(price_only, [], None)

    model_input = deepcopy(base)
    model_input["elements"][0]["now_cost"] = 56
    assert semantic_fingerprint(base, [], None) != semantic_fingerprint(model_input, [], None)
