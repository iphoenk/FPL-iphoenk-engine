from __future__ import annotations

import copy
import json
from time import perf_counter

import pytest

from src.engines.team_value import sell_cost
from src.engines.v4_official_fact_integrity import (
    DataJoinDefect,
    build_publication_integrity,
    extract_public_fact,
    official_snapshot_metadata,
)
from src.engines import v4_serving_contract


SNAPSHOT = "official-fixture-snapshot"
FETCHED = "2026-08-31T05:30:00+00:00"
POSITION_COUNTS = {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}


def _fact(element: int, position: str, *, snapshot: str = SNAPSHOT) -> dict:
    now_cost = 45 + element % 60
    return {
        "element": element,
        "element_id": element,
        "name": f"P{element}",
        "team": f"T{element % 20}",
        "club": f"T{element % 20}",
        "team_id": element % 20 + 1,
        "position": position,
        "now_cost": now_cost,
        "price": round(now_cost / 10.0, 1),
        "ownership": f"{(element % 30) + 0.1:.1f}",
        "status": "a",
        "source": "bootstrap-static.elements",
        "source_snapshot_id": snapshot,
        "fetched_at": FETCHED,
        "observed_at": FETCHED,
        "freshness": "FRESH",
    }


def _tactical() -> dict:
    owned_positions = ["GK", "GK", "DEF", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD"]
    owned = [_fact(i + 1, position) for i, position in enumerate(owned_positions)]
    watchlist = []
    element = 100
    for position, count in POSITION_COUNTS.items():
        for _ in range(count):
            watchlist.append(_fact(element, position))
            element += 1
    return {
        "authoritative_owned_ids": [row["element_id"] for row in owned],
        "owned": owned,
        "watchlist": watchlist,
    }


def _latest(*, personal: str = "LIVE") -> dict:
    return {
        "endpoint_health": {
            "bootstrap": {"status": "LIVE", "fetched_at": FETCHED},
            "entry": {"status": personal},
            "history": {"status": personal},
            "transfers": {"status": personal},
            "picks": {"status": personal},
        },
        "official_context": {"player_rows": 700},
        "prediction_summary": {"players": 700},
    }


def _prices(status: str = "PASS") -> dict:
    return {"source": "OFFICIAL_FPL", "health": {"status": status}, "confirmed_changes": []}


def _integrity(tactical: dict | None = None, *, personal: str = "LIVE", predictor: str = "PASS") -> dict:
    return build_publication_integrity(
        tactical or _tactical(),
        _latest(personal=personal),
        _prices(predictor),
        {"resolution_id": "resolution-1"},
        framework_health={"overall": "GREEN"},
        weather={"status": "PASS"},
    )


def test_a_b_c_d_owned_watchlist_complete_exact_positions_and_no_overlap():
    out = _integrity()
    assert out["status"] == "PASS"
    assert out["owned"] == {"expected": 15, "resolved": 15, "official_fact_complete": 15, "status": "PASS"}
    assert out["owned_authority"]["matches_authoritative_squad"] is True
    assert out["watchlist"]["expected"] == 20
    assert out["watchlist"]["resolved"] == 20
    assert out["watchlist"]["official_fact_complete"] == 20
    assert out["watchlist"]["position_counts"] == POSITION_COUNTS
    assert out["watchlist"]["position_cardinality_exact"] is True
    assert out["watchlist"]["owned_overlap"] == []


def test_e_public_success_personal_failure_keeps_public_facts_publishable():
    out = _integrity(personal="FAILED")
    assert out["capabilities"]["official_public_pull"] == "PASS"
    assert out["capabilities"]["personal_auth_pull"] == "FAIL"
    assert out["owned"]["official_fact_complete"] == 15
    assert out["watchlist"]["official_fact_complete"] == 20
    assert out["status"] == "PASS"
    assert out["authority_separation"]["personal_auth_failure_does_not_erase_public_fact"] is True


def test_f_one_owned_unresolved_blocks():
    tactical = _tactical()
    tactical["owned"] = tactical["owned"][:-1]
    out = _integrity(tactical)
    assert out["owned"]["resolved"] == 14
    assert out["status"] == "BLOCKED"


def test_g_one_watchlist_unresolved_blocks():
    tactical = _tactical()
    tactical["watchlist"] = tactical["watchlist"][:-1]
    out = _integrity(tactical)
    assert out["watchlist"]["resolved"] == 19
    assert out["status"] == "BLOCKED"


@pytest.mark.parametrize("field", ["now_cost", "ownership"])
def test_h_i_resolved_player_missing_required_fact_is_data_join_defect(field):
    row = _fact(1, "MID")
    row[field] = None
    with pytest.raises(DataJoinDefect, match="DATA_JOIN_DEFECT"):
        extract_public_fact(row, expected_element=1)
    tactical = _tactical()
    tactical["owned"][0][field] = None
    out = _integrity(tactical)
    assert out["status"] == "BLOCKED"
    assert any(defect["classification"] == "DATA_JOIN_DEFECT" and field in defect["missing_fields"] for defect in out["defects"])


def test_j_mixed_official_snapshots_block():
    tactical = _tactical()
    tactical["watchlist"][0]["source_snapshot_id"] = "different-snapshot"
    out = _integrity(tactical)
    assert out["official_snapshot"]["single_coherent_snapshot"] is False
    assert out["status"] == "BLOCKED"


def test_k_stale_predictor_is_visible_but_does_not_replace_current_official_fact():
    out = _integrity(predictor="STALE")
    assert out["capabilities"]["market_predictor_freshness"] == "STALE"
    assert out["owned"]["official_fact_complete"] == 15
    assert out["status"] == "PASS"


def test_l_m_predictor_no_signal_and_unavailable_semantics_are_explicit_in_serving_contract_source():
    source = v4_serving_contract.__file__
    text = open(source, encoding="utf-8").read()
    assert '"no_signal_semantics": "NO_SIGNAL"' in text
    assert '"unavailable_semantics": "UNAVAILABLE"' in text
    assert '"stale_semantics": "STALE_WITH_TIMESTAMP_AND_AGE"' in text


def test_n_confirmed_official_price_change_remains_fact_lane():
    source = open(v4_serving_contract.__file__, encoding="utf-8").read()
    assert '"confirmed_official_price_changes": prices.get("confirmed_changes") or []' in source
    assert '"price_fact_and_model_evidence_separated": True' in source


def test_o_p_renderer_cardinality_14_and_19_are_fail_closed():
    for group in ("owned", "watchlist"):
        tactical = _tactical()
        tactical[group] = tactical[group][:-1]
        out = _integrity(tactical)
        assert out["status"] == "BLOCKED"
        assert out["capabilities"]["reporting"] == "BLOCKED"
        assert out["capabilities"]["serving"] == "BLOCKED"
        assert out["capabilities"]["overall"] == "BLOCKED"


def test_q_write_serving_overwrites_stale_complete_payload_with_blocked_envelope(monkeypatch, tmp_path):
    tactical = _tactical()
    tactical["owned"][0]["ownership"] = None
    out_file = tmp_path / "serving.json"
    integrity_file = tmp_path / "integrity.json"
    benchmark_file = tmp_path / "benchmark.json"
    out_file.write_text(json.dumps({"contract": "OLD_COMPLETE_REPORT", "owned_15": [1] * 15}), encoding="utf-8")
    monkeypatch.setattr(v4_serving_contract, "OUTFILE", out_file)
    monkeypatch.setattr(v4_serving_contract, "PUBLICATION_INTEGRITY", integrity_file)
    monkeypatch.setattr(v4_serving_contract, "BENCHMARK", benchmark_file)
    monkeypatch.setattr(v4_serving_contract, "FRAMEWORK_HEALTH", tmp_path / "framework.json")
    monkeypatch.setattr(v4_serving_contract, "WEATHER_EVIDENCE", tmp_path / "weather.json")
    with pytest.raises(RuntimeError, match="PUBLICATION_INTEGRITY_BLOCKED"):
        v4_serving_contract.write_serving_payload(
            {"resolution_id": "r1"}, {}, {"squad": []}, tactical, {}, _prices(), _latest(), {}
        )
    blocked = json.loads(out_file.read_text(encoding="utf-8"))
    integrity = json.loads(integrity_file.read_text(encoding="utf-8"))
    assert blocked["contract"] == "V4_HUMAN_SERVING_BLOCKED_V1"
    assert blocked["user_report"] is None
    assert blocked["stale_complete_report_reuse_forbidden"] is True
    assert integrity["status"] == "BLOCKED"


def test_r_execution_authorized_false_is_not_mutated_by_publication_integrity():
    decision = {"resolution_id": "r1", "execution_authorized": False}
    original = copy.deepcopy(decision)
    out = build_publication_integrity(_tactical(), _latest(), _prices(), decision)
    assert out["status"] == "PASS"
    assert decision == original
    assert out["authority_separation"]["execution_authorized_semantics_unchanged"] is True


def test_s_weather_and_price_health_do_not_mutate_xi_cvc_chip_inputs():
    lineup = {"xi": list(range(1, 12)), "captain": 1, "vice": 2, "chip": "NONE"}
    before = copy.deepcopy(lineup)
    build_publication_integrity(_tactical(), _latest(), _prices("STALE"), {"resolution_id": "r1"}, weather={"status": "EXTREME"})
    assert lineup == before


def test_t_sell_value_reconstruction_rule_regression():
    assert sell_cost(55, 50) == 52
    assert sell_cost(49, 50) == 49
    assert sell_cost(50, 50) == 50


def test_u_tactical_challenger_universe_is_not_reduced_by_fact_integrity():
    tactical = _tactical()
    before_owned = [row["element_id"] for row in tactical["owned"]]
    before_watch = [row["element_id"] for row in tactical["watchlist"]]
    out = _integrity(tactical)
    assert out["status"] == "PASS"
    assert [row["element_id"] for row in tactical["owned"]] == before_owned
    assert [row["element_id"] for row in tactical["watchlist"]] == before_watch


def test_v_integrity_gate_overhead_is_small_for_35_rows():
    tactical = _tactical()
    started = perf_counter()
    for _ in range(100):
        assert _integrity(tactical)["status"] == "PASS"
    elapsed_ms = (perf_counter() - started) * 1000.0
    assert elapsed_ms < 500.0


def test_snapshot_hash_is_deterministic_and_transport_freshness_is_explicit():
    bootstrap = {"elements": [{"id": 1, "now_cost": 50}], "teams": []}
    health = {"status": "LIVE", "fetched_at": FETCHED, "response_cache_age_seconds": 0}
    first = official_snapshot_metadata(bootstrap, health)
    second = official_snapshot_metadata(copy.deepcopy(bootstrap), health)
    assert first["source_snapshot_id"] == second["source_snapshot_id"]
    assert first["freshness"] == "FRESH"
    assert first["fetched_at"] == FETCHED


def test_wrong_owned_id_blocks_even_when_cardinality_is_still_fifteen():
    tactical = _tactical()
    tactical["owned"][0] = _fact(99, "GK")
    out = _integrity(tactical)
    assert out["owned"]["resolved"] == 15
    assert out["owned_authority"]["matches_authoritative_squad"] is False
    assert out["owned_authority"]["missing_from_tactical"] == [1]
    assert out["owned_authority"]["unexpected_in_tactical"] == [99]
    assert out["capabilities"]["owned_authority_binding"] == "FAIL"
    assert out["status"] == "BLOCKED"


def test_missing_authoritative_owned_binding_blocks_publication():
    tactical = _tactical()
    tactical.pop("authoritative_owned_ids")
    out = _integrity(tactical)
    assert out["owned_authority"]["required"] is True
    assert out["owned_authority"]["provided"] is False
    assert out["capabilities"]["owned_authority_binding"] == "FAIL"
    assert out["status"] == "BLOCKED"
    assert any("authoritative_owned_ids" in defect["missing_fields"] for defect in out["defects"])


def test_publication_integrity_is_registered_as_governance_contract():
    from src.utils import CONFIG

    services = json.loads((CONFIG / "service_registry.json").read_text(encoding="utf-8"))
    contracts = json.loads((CONFIG / "service_contract_registry.json").read_text(encoding="utf-8"))
    governance = next(row for row in services["services"] if row["id"] == "governance")
    assert "publication_integrity" in governance["produces"]
    contract = contracts["contracts"]["publication_integrity"]
    assert contract["path"] == "data/publication_integrity_v4.json"
    assert contract["equals"]["status"] == "PASS"
    assert services["guardrails"]["publication_failure_cannot_leave_green_visible_health"] is True
