from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.domains.report_plane.report_compute import build_report_compute_contract
from src.runtime_v6.domains.report_plane.section_contract import validate_report_sections
from test_support.report_provenance import r5_partitions, r5_section_payloads
from test_support.report_rank20 import rank20_rows
from test_support.report_sections import r4_section_payloads


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


def _xi() -> list[int]:
    return [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14]


def _bench() -> list[int]:
    return [2, 7, 12, 15]


def _watchlist20() -> list[dict]:
    rows = []
    start = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for offset in range(5):
            rows.append({"element_id": start + offset, "position": position})
        start += 10
    return rows


def _full_sections() -> dict:
    our15 = _our15()
    return {
        "OUR15": our15,
        "XI_BENCH": {"starting_xi_ids": _xi(), "bench_ids": _bench()},
        "WATCHLIST20": _watchlist20(),
        "RISE20": rank20_rows(201, "RISE"),
        "FALL20": rank20_rows(301, "FALL"),
        **r4_section_payloads(our15),
    }


def _compute_kwargs() -> dict:
    our15 = _our15()
    facts, models, inferences = r5_partitions(
        fact_key="official_price",
        model_key="price_signal",
        fact_source="OFFICIAL_FPL",
        model_name="PRICE_PREDICTOR",
    )
    return {
        "scope_matrix_report_ready": True,
        "our15_rows": our15,
        "starting_xi_ids": _xi(),
        "bench_ids": _bench(),
        "watchlist_rows": _watchlist20(),
        "rise_rows": rank20_rows(201, "RISE"),
        "fall_rows": rank20_rows(301, "FALL"),
        "section_payloads": r5_section_payloads(our15),
        "facts": facts,
        "models": models,
        "inferences": inferences,
    }


def test_r4_complete_section_contract_passes_all_requested_sections():
    result = validate_report_sections(_full_sections())

    assert result["status"] == "PASS"
    assert result["section_contract_ready"] is True
    assert result["failures"] == []
    assert set(result["checks"]) == {
        "OUR15",
        "XI_BENCH",
        "WATCHLIST20",
        "RISE20",
        "FALL20",
        "WEATHER",
        "ICON14B",
        "ALL15_TACTICAL",
        "OPTIMIZER",
        "TRANSFER_STAGE",
        "PRICE_RISK",
    }


def test_r4_each_section_fails_closed_on_material_structural_gap():
    mutations = {
        "OUR15": lambda payload: payload["OUR15"].pop(),
        "XI_BENCH": lambda payload: payload["XI_BENCH"]["bench_ids"].pop(),
        "WATCHLIST20": lambda payload: payload["WATCHLIST20"].pop(),
        "RISE20": lambda payload: payload["RISE20"][0].pop("eta_human"),
        "FALL20": lambda payload: payload["FALL20"][0].pop("raw_payload_hash"),
        "WEATHER": lambda payload: payload["WEATHER"]["rows"][0].pop("fpl_impact"),
        "ICON14B": lambda payload: payload["ICON14B"].pop("direct_rival_equation"),
        "ALL15_TACTICAL": lambda payload: payload["ALL15_TACTICAL"][4].pop("coach_system_interaction"),
        "OPTIMIZER": lambda payload: payload["OPTIMIZER"]["routes"][0].pop("net_projected_gain"),
        "TRANSFER_STAGE": lambda payload: payload["TRANSFER_STAGE"].pop("reversal_conditions"),
        "PRICE_RISK": lambda payload: payload["PRICE_RISK"]["owned_rows"][3].pop("affordability_impact"),
    }

    for section, mutate in mutations.items():
        payload = _full_sections()
        mutate(payload)
        result = validate_report_sections(payload)
        assert result["status"] == "FAIL", section
        assert section in result["failures"], section
        assert result["checks"][section]["status"] == "FAIL", section


def test_r4_all15_tactical_must_cover_exact_authoritative_owned_ids_not_just_count_15():
    payload = _full_sections()
    payload["ALL15_TACTICAL"][-1]["element_id"] = 999

    result = validate_report_sections(payload)

    assert result["status"] == "FAIL"
    assert "OWNED_ID_SET_MISMATCH" in result["checks"]["ALL15_TACTICAL"]["failures"]


def test_r4_price_risk_must_cover_all15_owned_ids():
    payload = _full_sections()
    payload["PRICE_RISK"]["owned_rows"] = payload["PRICE_RISK"]["owned_rows"][:-1]

    result = validate_report_sections(payload)

    assert result["status"] == "FAIL"
    assert "OWNED_ID_SET_MISMATCH" in result["checks"]["PRICE_RISK"]["failures"]


def test_r4_weather_degraded_is_contract_valid_only_when_explicit_and_explained():
    payload = _full_sections()
    payload["WEATHER"] = {
        "content_state": "DEGRADED",
        "source_status": "DEGRADED",
        "degradation_reason": "Weather tool unavailable at report time.",
        "rows": [],
    }

    valid = validate_report_sections(payload)
    assert valid["status"] == "PASS"
    assert valid["checks"]["WEATHER"]["content_state"] == "DEGRADED"

    broken = deepcopy(payload)
    broken["WEATHER"].pop("degradation_reason")
    invalid = validate_report_sections(broken)
    assert invalid["status"] == "FAIL"
    assert invalid["checks"]["WEATHER"]["status"] == "FAIL"


def test_r4_icon_partial_requires_full_shape_plus_explicit_degradation_metadata():
    payload = _full_sections()
    payload["ICON14B"]["content_state"] = "PARTIAL"
    payload["ICON14B"]["missing_fields"] = ["eo"]
    payload["ICON14B"]["degradation_reason"] = "One rival exposure is unavailable."
    payload["ICON14B"]["eo"] = "UNAVAILABLE"

    valid = validate_report_sections(payload)
    assert valid["status"] == "PASS"
    assert valid["checks"]["ICON14B"]["content_state"] == "PARTIAL"

    broken = deepcopy(payload)
    broken["ICON14B"].pop("eo")
    invalid = validate_report_sections(broken)
    assert invalid["status"] == "FAIL"


def test_r4_optimizer_partial_must_be_truthful_and_cannot_claim_pass_with_broken_route():
    payload = _full_sections()
    payload["OPTIMIZER"] = {
        "content_state": "PARTIAL",
        "degradation_reason": "Exact frontier unavailable; no route is claimed as complete.",
        "routes": [],
    }
    assert validate_report_sections(payload)["status"] == "PASS"

    broken = _full_sections()
    broken["OPTIMIZER"]["routes"][0].pop("legality")
    invalid = validate_report_sections(broken)
    assert invalid["status"] == "FAIL"
    assert invalid["checks"]["OPTIMIZER"]["status"] == "FAIL"


def test_r4_report_compute_cannot_pass_when_extra_section_contract_is_broken():
    kwargs = _compute_kwargs()
    kwargs["section_payloads"]["ALL15_TACTICAL"][0].pop("player_style_fit")

    result = build_report_compute_contract(**kwargs)

    assert result["status"] == "FAIL"
    assert result["compute_ready"] is False
    assert "SECTION_CONTRACT" in result["failures"]
    assert result["SECTION_CONTRACT"]["checks"]["ALL15_TACTICAL"]["status"] == "FAIL"


def test_r4_compute_fingerprint_changes_when_section_semantics_change():
    base = _compute_kwargs()
    changed = deepcopy(base)
    changed["section_payloads"]["TRANSFER_STAGE"]["trigger"] = "Act only if confirmed starter news arrives."

    result_a = build_report_compute_contract(**base)
    result_b = build_report_compute_contract(**changed)

    assert result_a["status"] == "PASS"
    assert result_b["status"] == "PASS"
    assert result_a["compute_fingerprint"] != result_b["compute_fingerprint"]
