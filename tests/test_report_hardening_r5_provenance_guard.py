from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

from src.runtime_v6.domains.report_plane.provenance_guard import validate_report_provenance
from src.runtime_v6.report_compute import build_report_compute_contract
from test_support.report_rank20 import rank20_rows
from test_support.report_sections import r4_section_payloads


def _digest(payload) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _snapshot(source: str, token: str) -> str:
    return f"{source}:payload:{sha256(token.encode('utf-8')).hexdigest()}"


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


def _valid_partitions():
    facts = {
        "official_price": {
            "source": "OFFICIAL_FPL",
            "effective_at": "2026-09-16T21:30:00+00:00",
            "source_snapshot_ids": [_snapshot("official_fpl", "price")],
            "value": 75,
        },
        "weather_forecast": {
            "source": "OPEN_METEO",
            "effective_at": "2026-09-16T21:30:00+00:00",
            "source_snapshot_ids": [_snapshot("open_meteo", "weather")],
            "value": "NORMAL",
        },
    }
    models = {
        "expected_points": {
            "model": "BAYESIAN",
            "computed_at": "2026-09-16T21:31:00+00:00",
            "input_snapshot_ids": [facts["official_price"]["source_snapshot_ids"][0]],
            "value": 6.8,
        }
    }
    inferences = {
        "transfer_implication": {
            "basis": "FACT_AND_MODEL",
            "fact_refs": ["official_price"],
            "model_refs": ["expected_points"],
            "value": "WAIT",
        }
    }
    return facts, models, inferences


def _valid_sections(our15):
    sections = r4_section_payloads(our15)
    sections["WEATHER"]["source_proof"] = {
        "fact_ref": "weather_forecast",
        "source": "OPEN_METEO",
        "effective_at": "2026-09-16T21:30:00+00:00",
        "source_snapshot_ids": [_snapshot("open_meteo", "weather")],
    }

    routes = sections["OPTIMIZER"]["routes"]
    optimizer_input = {"our15_ids": [row["element_id"] for row in our15]}
    sections["OPTIMIZER"]["execution_proof"] = {
        "optimizer": {
            "state": "EXECUTED",
            "run_id": "optimizer-run-1",
            "method": "MULTI_HORIZON_PACKAGE_OPTIMIZER",
            "executed_at": "2026-09-16T21:32:00+00:00",
            "input_fingerprint": _digest(optimizer_input),
            "output_fingerprint": _digest(routes),
        },
        "monte_carlo": {
            "state": "EXECUTED",
            "run_id": "mc-run-1",
            "method": "MONTE_CARLO",
            "executed_at": "2026-09-16T21:32:30+00:00",
            "input_fingerprint": _digest(optimizer_input),
            "output_fingerprint": _digest({"route_ids": [row["route_id"] for row in routes]}),
            "actual_paths": 500000,
        },
        "frontier": {
            "state": "PARTIAL",
            "run_id": "frontier-run-1",
            "method": "SEARCH_FRONTIER",
            "executed_at": "2026-09-16T21:32:45+00:00",
            "input_fingerprint": _digest(optimizer_input),
            "output_fingerprint": _digest({"route_ids": [row["route_id"] for row in routes]}),
            "degradation_reason": "LOSSY_SEARCH_FRONTIER",
        },
    }
    return sections


def _valid_compute_kwargs():
    our15 = _our15()
    facts, models, inferences = _valid_partitions()
    return {
        "scope_matrix_report_ready": True,
        "our15_rows": our15,
        "starting_xi_ids": [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        "bench_ids": [2, 7, 12, 15],
        "watchlist_rows": _watchlist20(),
        "rise_rows": rank20_rows(201, "RISE"),
        "fall_rows": rank20_rows(301, "FALL"),
        "section_payloads": _valid_sections(our15),
        "facts": facts,
        "models": models,
        "inferences": inferences,
    }


def _validate(kwargs):
    return validate_report_provenance(
        section_payloads=kwargs["section_payloads"],
        facts=kwargs["facts"],
        models=kwargs["models"],
        inferences=kwargs["inferences"],
    )


def test_r5_valid_provenance_contract_passes():
    result = _validate(_valid_compute_kwargs())

    assert result["status"] == "PASS"
    assert result["partition"]["status"] == "PASS"
    assert result["weather"]["status"] == "PASS"
    assert result["execution"]["status"] == "PASS"


def test_r5_fact_model_inference_namespaces_are_pairwise_disjoint():
    kwargs = _valid_compute_kwargs()
    kwargs["inferences"]["official_price"] = kwargs["inferences"].pop("transfer_implication")

    result = _validate(kwargs)

    assert result["status"] == "FAIL"
    assert "PARTITION_OVERLAP=official_price" in result["partition"]["failures"]


def test_r5_model_input_snapshots_must_be_grounded_in_current_fact_lineage():
    kwargs = _valid_compute_kwargs()
    kwargs["models"]["expected_points"]["input_snapshot_ids"] = [
        _snapshot("unrelated_source", "fabricated-but-well-formed")
    ]

    result = _validate(kwargs)

    assert result["status"] == "FAIL"
    assert "MODEL_INPUT_PROVENANCE_UNLINKED=expected_points" in result["partition"]["failures"]


def test_r5_weather_pass_without_immutable_source_proof_is_rejected():
    kwargs = _valid_compute_kwargs()
    kwargs["section_payloads"]["WEATHER"].pop("source_proof")

    result = _validate(kwargs)

    assert result["status"] == "FAIL"
    assert result["weather"]["status"] == "FAIL"
    assert "WEATHER_SOURCE_PROOF_MISSING" in result["weather"]["failures"]


def test_r5_weather_proof_must_bind_to_declared_weather_fact_not_any_fact_snapshot():
    kwargs = _valid_compute_kwargs()
    proof = kwargs["section_payloads"]["WEATHER"]["source_proof"]
    proof["source_snapshot_ids"] = kwargs["facts"]["official_price"]["source_snapshot_ids"]

    result = _validate(kwargs)

    assert result["status"] == "FAIL"
    assert "WEATHER_FACT_PROVENANCE_MISMATCH=weather_forecast" in result["weather"]["failures"]


def test_r5_optimizer_claim_cannot_be_pass_without_execution_proof():
    kwargs = _valid_compute_kwargs()
    kwargs["section_payloads"]["OPTIMIZER"].pop("execution_proof")

    result = _validate(kwargs)

    assert result["status"] == "FAIL"
    assert "OPTIMIZER_EXECUTION_PROOF_MISSING" in result["execution"]["failures"]


def test_r5_monte_carlo_executed_claim_requires_actual_path_count():
    kwargs = _valid_compute_kwargs()
    kwargs["section_payloads"]["OPTIMIZER"]["execution_proof"]["monte_carlo"].pop("actual_paths")

    result = _validate(kwargs)

    assert result["status"] == "FAIL"
    assert "MONTE_CARLO_ACTUAL_PATHS_INVALID" in result["execution"]["failures"]


def test_r5_optimizer_proof_requires_explicit_state_for_mc_and_frontier():
    for component in ("monte_carlo", "frontier"):
        kwargs = _valid_compute_kwargs()
        kwargs["section_payloads"]["OPTIMIZER"]["execution_proof"].pop(component)

        result = _validate(kwargs)

        assert result["status"] == "FAIL", component
        assert f"{component.upper()}_EXECUTION_PROOF_MISSING" in result["execution"]["failures"]


def test_r5_truthful_not_run_monte_carlo_does_not_require_fake_run_identity():
    kwargs = _valid_compute_kwargs()
    kwargs["section_payloads"]["OPTIMIZER"]["execution_proof"]["monte_carlo"] = {
        "state": "NOT_RUN",
        "reason": "NOT_REQUIRED_FOR_THIS_REPORT",
    }

    result = _validate(kwargs)

    assert result["status"] == "PASS"


def test_r5_optimizer_output_tampering_breaks_execution_binding():
    kwargs = _valid_compute_kwargs()
    original = _validate(kwargs)
    assert original["status"] == "PASS"

    tampered = deepcopy(kwargs["section_payloads"])
    tampered["OPTIMIZER"]["routes"][0]["net_projected_gain"] = 99.0
    kwargs["section_payloads"] = tampered
    result = _validate(kwargs)

    assert result["status"] == "FAIL"
    assert "OPTIMIZER_OUTPUT_FINGERPRINT_MISMATCH" in result["execution"]["failures"]


def test_r5_report_compute_requires_provenance_and_binds_inference_to_fingerprint():
    kwargs_a = _valid_compute_kwargs()
    kwargs_b = _valid_compute_kwargs()
    kwargs_b["inferences"]["transfer_implication"]["value"] = "ACT"

    result_a = build_report_compute_contract(**kwargs_a)
    result_b = build_report_compute_contract(**kwargs_b)

    assert result_a["status"] == "PASS"
    assert result_a["PROVENANCE"]["status"] == "PASS"
    assert result_b["status"] == "PASS"
    assert result_a["compute_fingerprint"] != result_b["compute_fingerprint"]