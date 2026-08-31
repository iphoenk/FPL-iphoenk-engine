import json

import src.engines.dss_operationalization_overlay as operationalization


def _prices(status="PASS", **contract_overrides):
    contract = {
        "model_id": "official_price_radar_v3",
        "current_progress_field": "price_change_percent",
        "projected_progress_field": "price_change_projections",
        "likelihood_preserved_raw": True,
        "threshold_is_official_rule": False,
        "no_intra_cycle_crossing_eta": True,
    }
    contract.update(contract_overrides)
    row = {
        "element_id": 1,
        "current_price": 5.0,
        "ownership_percent": 10.0,
        "current_progress_percent": 50.0,
        "projection_offset_0_percent": 70.0,
        "projection_offset_0_likelihood": 3,
        "source": "OFFICIAL_FPL",
        "next_official_price_update_at": "2026-09-01T06:00:00+07:00",
        "trajectory_eta_hours": None,
        "trajectory_predicted_change_deadline": None,
    }
    return {
        "players": [row],
        "official_price_predictor_health": {"status": status, "source": "OFFICIAL_FPL"},
        "official_price_predictor_contract": contract,
    }


def test_price_intelligence_operationalizes_fresh_official_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(operationalization, "DATA", tmp_path)
    (tmp_path / "prices.json").write_text(json.dumps(_prices()), encoding="utf-8")
    (tmp_path / "price_alerts.json").write_text(json.dumps({"owned_price_radar_count": 15}), encoding="utf-8")

    ok, detail = operationalization._price_intelligence({"fallback": "explicit governed fallback"})

    assert ok is True
    assert detail["evidence_state"] == "AVAILABLE"
    assert detail["predictor_health"] == "PASS"
    assert detail["fresh_official_signal"] is True
    assert detail["coverage_ratio"] == 1.0
    assert detail["owned_price_radar_count"] == 15
    assert detail["external_predictor_override_allowed"] is False


def test_price_intelligence_can_operationalize_explicit_partial_signal_without_claiming_freshness(tmp_path, monkeypatch):
    monkeypatch.setattr(operationalization, "DATA", tmp_path)
    (tmp_path / "prices.json").write_text(json.dumps(_prices(status="PARTIAL")), encoding="utf-8")
    (tmp_path / "price_alerts.json").write_text(json.dumps({"owned_price_radar_count": 15}), encoding="utf-8")

    ok, detail = operationalization._price_intelligence({"fallback": "explicit governed fallback"})

    assert ok is True
    assert detail["evidence_state"] == "UNAVAILABLE_WITH_SAFE_FALLBACK"
    assert detail["fresh_official_signal"] is False


def test_price_intelligence_rejects_contract_that_allows_fabricated_crossing_eta(tmp_path, monkeypatch):
    monkeypatch.setattr(operationalization, "DATA", tmp_path)
    payload = _prices(no_intra_cycle_crossing_eta=False)
    (tmp_path / "prices.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "price_alerts.json").write_text("{}", encoding="utf-8")

    ok, detail = operationalization._price_intelligence({"fallback": "explicit governed fallback"})

    assert ok is False
    assert detail["evidence_state"] == "INSUFFICIENT"
    assert detail["no_intra_cycle_crossing_eta"] is False


def test_price_intelligence_rejects_failed_predictor_health(tmp_path, monkeypatch):
    monkeypatch.setattr(operationalization, "DATA", tmp_path)
    (tmp_path / "prices.json").write_text(json.dumps(_prices(status="FAIL")), encoding="utf-8")
    (tmp_path / "price_alerts.json").write_text("{}", encoding="utf-8")

    ok, detail = operationalization._price_intelligence({"fallback": "explicit governed fallback"})

    assert ok is False
    assert detail["predictor_health"] == "FAIL"
    assert detail["evidence_state"] == "INSUFFICIENT"
