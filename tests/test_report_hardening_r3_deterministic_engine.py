from __future__ import annotations

import random
from copy import deepcopy

import pytest

from src.runtime_v6.domains.report_plane.delivery_integrity import validate_rank20
from src.runtime_v6.domains.report_plane.rank20_engine import (
    Rank20EngineError,
    build_rank20_tables,
)
from src.runtime_v6.domains.report_plane.report_compute import (
    build_report_compute_contract_from_universe,
)
from test_support.report_sections import r4_section_payloads


def _universe(count: int = 60) -> list[dict]:
    return [
        {
            "element_id": element_id,
            "player_name": f"Synthetic Player {element_id}",
            "current_price": round(4.0 + element_id / 10.0, 1),
            "ownership_percent": round(element_id / 3.0, 1),
        }
        for element_id in range(1, count + 1)
    ]


def _predictor(count: int = 60) -> list[dict]:
    rows = []
    for element_id in range(1, count + 1):
        offset = float(element_id - 30)
        rows.append(
            {
                "element_id": element_id,
                "current_progress_percent": round(100.0 + offset, 3),
                "projection_offset_0_percent": offset,
                "predicted_change_cycle": "NEXT_UPDATE",
                "predicted_change_at": None,
                "eta_human": "NO RELIABLE ETA",
                "model_urgency": "HIGH" if abs(offset) >= 20 else "WATCH",
                "confidence": "HIGH" if abs(offset) >= 15 else "MEDIUM",
            }
        )
    return rows


def _snapshot() -> dict:
    return {
        "source": "SYNTHETIC_PRICE_MODEL",
        "observed_at": "2026-09-16T20:00:00+07:00",
        "raw_payload_hash": "a" * 64,
    }


def _build(*, universe=None, predictor=None, owned_ids=()):
    return build_rank20_tables(
        universe_rows=_universe() if universe is None else universe,
        predictor_rows=_predictor() if predictor is None else predictor,
        owned_ids=owned_ids,
        snapshot=_snapshot(),
    )


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


def test_r3_scans_full_universe_and_returns_exact_top20_each_direction():
    result = _build()

    assert [row["element_id"] for row in result["RISE20"]] == list(range(60, 40, -1))
    assert [row["element_id"] for row in result["FALL20"]] == list(range(1, 21))
    assert [row["rank"] for row in result["RISE20"]] == list(range(1, 21))
    assert [row["rank"] for row in result["FALL20"]] == list(range(1, 21))
    assert result["universe_count"] == 60
    assert result["predictor_coverage_count"] == 60
    assert result["full_universe_coverage"] is True

    assert validate_rank20(result["RISE20"], label="RISE20")["status"] == "PASS"
    assert validate_rank20(result["FALL20"], label="FALL20")["status"] == "PASS"


def test_r3_is_input_order_invariant_and_uses_element_id_as_final_tie_breaker():
    universe = _universe()
    predictor = _predictor()

    predictor[49]["projection_offset_0_percent"] = 99.0  # element 50
    predictor[50]["projection_offset_0_percent"] = 99.0  # element 51
    predictor[9]["projection_offset_0_percent"] = -99.0  # element 10
    predictor[10]["projection_offset_0_percent"] = -99.0  # element 11

    expected = build_rank20_tables(
        universe_rows=universe,
        predictor_rows=predictor,
        owned_ids=(),
        snapshot=_snapshot(),
    )

    shuffled_universe = deepcopy(universe)
    shuffled_predictor = deepcopy(predictor)
    random.Random(7).shuffle(shuffled_universe)
    random.Random(11).shuffle(shuffled_predictor)
    actual = build_rank20_tables(
        universe_rows=shuffled_universe,
        predictor_rows=shuffled_predictor,
        owned_ids=(),
        snapshot=_snapshot(),
    )

    assert actual == expected
    rise_ids = [row["element_id"] for row in actual["RISE20"]]
    fall_ids = [row["element_id"] for row in actual["FALL20"]]
    assert rise_ids.index(50) < rise_ids.index(51)
    assert fall_ids.index(10) < fall_ids.index(11)


def test_r3_derives_ownership_and_truthful_eta_without_inventing_a_clock_time():
    predictor = _predictor()
    predictor[59]["predicted_change_at"] = "2026-09-16T23:00:00+00:00"  # element 60
    predictor[59]["eta_human"] = ""
    predictor[58]["predicted_change_at"] = None  # element 59
    predictor[58]["eta_human"] = ""

    result = _build(predictor=predictor, owned_ids={1, 60})
    rise_by_id = {row["element_id"]: row for row in result["RISE20"]}
    fall_by_id = {row["element_id"]: row for row in result["FALL20"]}

    assert rise_by_id[60]["ownership_tag"] == "OWNED"
    assert fall_by_id[1]["ownership_tag"] == "OWNED"
    assert rise_by_id[59]["ownership_tag"] == "NON_OWNED"
    assert rise_by_id[60]["eta_human"] == "2026-09-17 06:00 WIB"
    assert rise_by_id[59]["eta_human"] == "NO RELIABLE ETA"


def test_r3_stamps_one_snapshot_provenance_across_all_40_rows():
    result = _build()
    all_rows = result["RISE20"] + result["FALL20"]

    assert {row["source"] for row in all_rows} == {"SYNTHETIC_PRICE_MODEL"}
    assert {row["observed_at"] for row in all_rows} == {"2026-09-16T20:00:00+07:00"}
    assert {row["raw_payload_hash"] for row in all_rows} == {"a" * 64}


def test_r3_fails_closed_when_full_universe_predictor_coverage_is_incomplete():
    predictor = _predictor()[:-1]

    with pytest.raises(Rank20EngineError, match="FULL_UNIVERSE_PREDICTOR_COVERAGE"):
        _build(predictor=predictor)


def test_r3_fails_closed_on_duplicate_stable_ids_or_missing_projection():
    universe = _universe()
    universe.append(deepcopy(universe[-1]))
    with pytest.raises(Rank20EngineError, match="UNIVERSE_ID_DUPLICATE"):
        _build(universe=universe)

    predictor = _predictor()
    predictor[4]["projection_offset_0_percent"] = None
    with pytest.raises(Rank20EngineError, match="PROJECTION_OFFSET_MISSING"):
        _build(predictor=predictor)


def test_r3_rejects_mixed_snapshot_lineage_in_predictor_rows():
    predictor = _predictor()
    predictor[0]["raw_payload_hash"] = "b" * 64

    with pytest.raises(Rank20EngineError, match="SNAPSHOT_PROVENANCE_MISMATCH"):
        _build(predictor=predictor)


def test_report_compute_canonical_entrypoint_builds_rank20_from_full_universe():
    our15 = _our15()
    result = build_report_compute_contract_from_universe(
        scope_matrix_report_ready=True,
        our15_rows=our15,
        starting_xi_ids=[1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        bench_ids=[2, 7, 12, 15],
        watchlist_rows=_watchlist20(),
        universe_rows=_universe(),
        predictor_rows=_predictor(),
        rank_snapshot=_snapshot(),
        section_payloads=r4_section_payloads(our15),
        facts={"official_price": {"source": "OFFICIAL_FPL", "value": 7.5}},
        models={"price_signal": {"model": "PRICE_PREDICTOR", "value": 0.8}},
    )

    assert result["status"] == "PASS"
    assert result["compute_ready"] is True
    assert result["SECTION_CONTRACT"]["status"] == "PASS"
    assert result["RANK20_ENGINE"]["full_universe_coverage"] is True
    assert result["RANK20_ENGINE"]["universe_count"] == 60
    assert [row["element_id"] for row in result["RISE20_ROWS"]] == list(range(60, 40, -1))
    assert [row["element_id"] for row in result["FALL20_ROWS"]] == list(range(1, 21))
    assert result["FALL20_ROWS"][0]["ownership_tag"] == "OWNED"
