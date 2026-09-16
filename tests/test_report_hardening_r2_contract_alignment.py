from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.report_compute import build_report_compute_contract
from src.runtime_v6.report_delivery_integrity import validate_rank20


_HASH = "a" * 64


def _rank20(start: int, direction: str) -> list[dict]:
    rows = []
    for index in range(20):
        rank = index + 1
        rows.append(
            {
                "rank": rank,
                "element_id": start + index,
                "player_name": f"P{start + index}",
                "current_price": 5.0 + (index / 10),
                "ownership_percent": 1.0 + index,
                "ownership_tag": "NON_OWNED",
                "direction": direction,
                "current_progress_percent": 70.0 if direction == "RISE" else -70.0,
                "projection_offset_0_percent": 95.0 if direction == "RISE" else -95.0,
                "predicted_change_cycle": "NEXT_UPDATE",
                "predicted_change_at": "2026-09-17T06:00:00+07:00",
                "eta_human": "next price cycle",
                "model_urgency": "HIGH",
                "confidence": "HIGH",
                "source": "OFFICIAL_FPL",
                "observed_at": "2026-09-16T20:00:00+07:00",
                "raw_payload_hash": _HASH,
            }
        )
    return rows


def _our15() -> list[dict]:
    rows = []
    for player_id in (1, 2):
        rows.append({"element_id": player_id, "position": "GK"})
    for player_id in range(3, 8):
        rows.append({"element_id": player_id, "position": "DEF"})
    for player_id in range(8, 13):
        rows.append({"element_id": player_id, "position": "MID"})
    for player_id in range(13, 16):
        rows.append({"element_id": player_id, "position": "FWD"})
    return rows


def _watchlist20() -> list[dict]:
    rows = []
    start = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for offset in range(5):
            rows.append({"element_id": start + offset, "position": position})
        start += 10
    return rows


def _compute_kwargs() -> dict:
    return {
        "scope_matrix_report_ready": True,
        "our15_rows": _our15(),
        "starting_xi_ids": [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        "bench_ids": [2, 7, 12, 15],
        "watchlist_rows": _watchlist20(),
        "rise_rows": _rank20(201, "RISE"),
        "fall_rows": _rank20(301, "FALL"),
        "facts": {"official_price": {"source": "OFFICIAL_FPL", "value": 7.5}},
        "models": {"price_signal": {"model": "PRICE_PREDICTOR", "value": 0.8}},
    }


def test_identity_only_exact_20_is_not_a_valid_rank20_contract():
    rows = [{"element_id": 1000 + index} for index in range(20)]

    result = validate_rank20(rows, label="RISE20")

    assert result["status"] == "FAIL"
    assert any(failure.startswith("ROW_SCHEMA_MISSING=") for failure in result["failures"])


def test_missing_eta_and_snapshot_provenance_fail_with_row_field_evidence():
    rows = _rank20(2000, "RISE")
    del rows[4]["eta_human"]
    del rows[4]["raw_payload_hash"]

    result = validate_rank20(rows, label="RISE20")

    assert result["status"] == "FAIL"
    assert "ROW_SCHEMA_MISSING=5:eta_human,raw_payload_hash" in result["failures"]


def test_rank_and_direction_integrity_are_fail_closed():
    rows = _rank20(3000, "RISE")
    rows[0]["rank"] = 2
    rows[1]["direction"] = "FALL"

    result = validate_rank20(rows, label="RISE20")

    assert result["status"] == "FAIL"
    assert "RANK_SEQUENCE_INVALID" in result["failures"]
    assert "ROW_DIRECTION_MISMATCH=2:FALL!=RISE" in result["failures"]


def test_complete_exact_20_schema_passes_for_each_direction():
    rise = validate_rank20(_rank20(4000, "RISE"), label="RISE20")
    fall = validate_rank20(_rank20(5000, "FALL"), label="FALL20")

    assert rise["status"] == "PASS"
    assert fall["status"] == "PASS"
    assert rise["row_schema_complete"] is True
    assert fall["row_schema_complete"] is True


def test_compute_fingerprint_changes_when_rank20_semantics_change_with_same_ids():
    base = _compute_kwargs()
    changed = deepcopy(base)
    changed["rise_rows"][0]["projection_offset_0_percent"] = 111.0
    changed["rise_rows"][0]["predicted_change_cycle"] = "PLUS_1_UPDATE"
    changed["rise_rows"][0]["eta_human"] = "one cycle later"
    changed["rise_rows"][0]["model_urgency"] = "WATCH"
    changed["rise_rows"][0]["raw_payload_hash"] = "b" * 64

    result_a = build_report_compute_contract(**base)
    result_b = build_report_compute_contract(**changed)

    assert result_a["status"] == "PASS"
    assert result_b["status"] == "PASS"
    assert result_a["compute_fingerprint"] != result_b["compute_fingerprint"]


def test_compute_contract_rejects_one_schema_incomplete_price_row_even_at_exact_20():
    kwargs = _compute_kwargs()
    del kwargs["fall_rows"][9]["ownership_tag"]

    result = build_report_compute_contract(**kwargs)

    assert result["status"] == "FAIL"
    assert result["compute_ready"] is False
    assert result["FALL20"]["status"] == "FAIL"
    assert "ROW_SCHEMA_MISSING=10:ownership_tag" in result["FALL20"]["failures"]
