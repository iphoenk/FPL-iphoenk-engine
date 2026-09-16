from __future__ import annotations

from collections import OrderedDict

from src.runtime_v6.report_compute import build_report_compute_contract
from test_support.report_provenance import (
    fact_row,
    inference_row,
    model_row,
    r5_section_payloads,
)
from test_support.report_rank20 import rank20_rows


def _our15():
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


def _watchlist20():
    rows = []
    start = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for offset in range(5):
            rows.append({"element_id": start + offset, "position": position})
        start += 10
    return rows


def _valid_kwargs():
    our15 = _our15()
    official_price = fact_row(source="OFFICIAL_FPL", token="official_price", value=75)
    ownership = fact_row(source="OFFICIAL_FPL", token="ownership", value=42.1)
    weather = fact_row(source="OPEN_METEO", token="weather", value="NORMAL")
    facts = {
        "official_price": official_price,
        "ownership": ownership,
        "weather_forecast": weather,
    }
    models = {
        "price_rise_probability": model_row(
            model="PRICE_PREDICTOR",
            input_snapshot_ids=official_price["source_snapshot_ids"],
            value=0.71,
        ),
        "expected_points": model_row(
            model="BAYESIAN",
            input_snapshot_ids=ownership["source_snapshot_ids"],
            value=6.8,
        ),
    }
    inferences = {
        "decision": inference_row(
            fact_refs=["official_price", "ownership"],
            model_refs=["price_rise_probability", "expected_points"],
        )
    }
    return {
        "scope_matrix_report_ready": True,
        "our15_rows": our15,
        "starting_xi_ids": [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        "bench_ids": [2, 7, 12, 15],
        "watchlist_rows": _watchlist20(),
        "rise_rows": rank20_rows(201, "RISE"),
        "fall_rows": rank20_rows(301, "FALL"),
        "section_payloads": r5_section_payloads(our15),
        "facts": facts,
        "models": models,
        "inferences": inferences,
    }


def test_valid_compute_contract_is_ready_only_for_pre_render_qa():
    result = build_report_compute_contract(**_valid_kwargs())

    assert result["status"] == "PASS"
    assert result["compute_ready"] is True
    assert result["next_action"] == "PRE_RENDER_QA"
    assert result["delivery_ready"] is False
    assert result["legacy_fallback_allowed"] is False
    assert result["OUR15"]["status"] == "PASS"
    assert result["XI"]["status"] == "PASS"
    assert result["BENCH"]["status"] == "PASS"
    assert result["WATCHLIST20"]["status"] == "PASS"
    assert result["RISE20"]["status"] == "PASS"
    assert result["FALL20"]["status"] == "PASS"
    assert result["FACT_MODEL"]["status"] == "PASS"
    assert result["SECTION_CONTRACT"]["status"] == "PASS"
    assert result["PROVENANCE"]["status"] == "PASS"


def test_scope_resolver_failure_blocks_compute_before_any_report_math():
    kwargs = _valid_kwargs()
    kwargs["scope_matrix_report_ready"] = False

    result = build_report_compute_contract(**kwargs)

    assert result["status"] == "BLOCKED"
    assert result["compute_ready"] is False
    assert result["next_action"] == "RESOLVE_REPORT_SCOPES"
    assert result["failures"] == ["SCOPE_MATRIX_NOT_READY"]
    assert result["delivery_ready"] is False


def test_our15_requires_exact_unique_legal_fpl_squad_composition():
    kwargs = _valid_kwargs()
    kwargs["our15_rows"] = kwargs["our15_rows"][:-1] + [
        {"element_id": 7, "position": "DEF"}
    ]

    result = build_report_compute_contract(**kwargs)

    assert result["compute_ready"] is False
    assert result["OUR15"]["status"] == "FAIL"
    assert "IDENTITY_DUPLICATE" in result["OUR15"]["failures"]
    assert "DEF=6" in result["OUR15"]["failures"]
    assert "FWD=2" in result["OUR15"]["failures"]
    assert result["next_action"] == "RECOMPUTE"


def test_starting_xi_requires_11_unique_owned_players_and_legal_formation():
    kwargs = _valid_kwargs()
    kwargs["starting_xi_ids"] = [1, 3, 4, 8, 9, 10, 11, 12, 13, 14, 15]

    result = build_report_compute_contract(**kwargs)

    assert result["compute_ready"] is False
    assert result["XI"]["status"] == "FAIL"
    assert "DEF=2" in result["XI"]["failures"]
    assert result["delivery_ready"] is False


def test_bench_must_be_exact_four_player_complement_of_our15_and_include_one_gk():
    kwargs = _valid_kwargs()
    kwargs["bench_ids"] = [2, 7, 12, 14]

    result = build_report_compute_contract(**kwargs)

    assert result["compute_ready"] is False
    assert result["BENCH"]["status"] == "FAIL"
    assert "NOT_EXACT_OUR15_COMPLEMENT" in result["BENCH"]["failures"]
    assert result["next_action"] == "RECOMPUTE"


def test_watchlist_and_price_rank_sets_remain_fail_closed_at_exact_20_contract():
    kwargs = _valid_kwargs()
    kwargs["watchlist_rows"] = kwargs["watchlist_rows"][:-1]
    kwargs["rise_rows"] = kwargs["rise_rows"][:-1]

    result = build_report_compute_contract(**kwargs)

    assert result["compute_ready"] is False
    assert result["WATCHLIST20"]["status"] == "FAIL"
    assert result["RISE20"]["status"] == "FAIL"
    assert result["FALL20"]["status"] == "PASS"
    assert result["delivery_ready"] is False


def test_fact_and_model_namespaces_must_be_explicit_and_non_overlapping():
    kwargs = _valid_kwargs()
    kwargs["models"] = {
        **kwargs["models"],
        "official_price": model_row(
            model="BAD_OVERLAP",
            input_snapshot_ids=kwargs["facts"]["official_price"]["source_snapshot_ids"],
            value=76,
        ),
    }

    result = build_report_compute_contract(**kwargs)

    assert result["compute_ready"] is False
    assert result["FACT_MODEL"]["status"] == "FAIL"
    assert result["FACT_MODEL"]["overlap"] == ["official_price"]
    assert "PARTITION_OVERLAP=official_price" in result["FACT_MODEL"]["failures"]


def test_compute_fingerprint_is_deterministic_for_equivalent_mapping_order():
    kwargs_a = _valid_kwargs()
    kwargs_b = _valid_kwargs()
    kwargs_b["facts"] = OrderedDict(reversed(list(kwargs_b["facts"].items())))
    kwargs_b["models"] = OrderedDict(reversed(list(kwargs_b["models"].items())))
    kwargs_b["inferences"] = OrderedDict(reversed(list(kwargs_b["inferences"].items())))

    result_a = build_report_compute_contract(**kwargs_a)
    result_b = build_report_compute_contract(**kwargs_b)

    assert result_a["status"] == "PASS"
    assert result_b["status"] == "PASS"
    assert result_a["compute_fingerprint"] == result_b["compute_fingerprint"]


def test_compute_failure_never_claims_delivery_ready_or_uses_legacy_fallback():
    kwargs = _valid_kwargs()
    kwargs["fall_rows"] = []

    result = build_report_compute_contract(**kwargs)

    assert result["status"] == "FAIL"
    assert result["compute_ready"] is False
    assert result["delivery_ready"] is False
    assert result["next_action"] == "RECOMPUTE"
    assert result["legacy_fallback_allowed"] is False