from __future__ import annotations

from src.runtime_v6.delivery_integrity import MANDATORY_SECTIONS
from src.runtime_v6.report_compute import build_report_compute_contract
from src.runtime_v6.report_qa import validate_post_render_qa, validate_pre_render_qa
from test_support.report_provenance import r5_partitions, r5_section_payloads
from test_support.report_rank20 import rank20_rows
from test_support.report_visible_body import valid_visible_body


def _our15():
    rows = []
    for player_id in range(1, 3):
        rows.append({"id": player_id, "position": "GK"})
    for player_id in range(3, 8):
        rows.append({"id": player_id, "position": "DEF"})
    for player_id in range(8, 13):
        rows.append({"id": player_id, "position": "MID"})
    for player_id in range(13, 16):
        rows.append({"id": player_id, "position": "FWD"})
    return rows


def _watchlist20():
    rows = []
    next_id = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for _ in range(5):
            rows.append({"id": next_id, "position": position})
            next_id += 1
    return rows


def _compute():
    our15 = _our15()
    facts, models, inferences = r5_partitions(
        fact_key="price_fact",
        model_key="price_model",
        fact_source="OFFICIAL_FPL",
        model_name="V6_PRICE_MODEL",
    )
    return build_report_compute_contract(
        scope_matrix_report_ready=True,
        our15_rows=our15,
        starting_xi_ids=[1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        bench_ids=[2, 7, 12, 15],
        watchlist_rows=_watchlist20(),
        rise_rows=rank20_rows(201, "RISE"),
        fall_rows=rank20_rows(301, "FALL"),
        section_payloads=r5_section_payloads(our15),
        facts=facts,
        models=models,
        inferences=inferences,
    )


def _manifest():
    return [{"section_id": section_id, "status": "COMPLETE"} for section_id in MANDATORY_SECTIONS]


def _pre(*, report_mode: str, weather_contract_state: str):
    return validate_pre_render_qa(
        compute_contract=_compute(),
        section_manifest=_manifest(),
        mini_league_denominator_complete=True,
        report_mode=report_mode,
        weather_contract_state=weather_contract_state,
    )


def _post(pre, *, state: str):
    return validate_post_render_qa(
        pre_render_qa=pre,
        rendered_body=valid_visible_body(pre, weather_state_override=state),
        rendered_section_ids=pre["expected_section_ids"],
        rendered_section_states={row["section_id"]: row["status"] for row in pre["section_manifest"]},
        rendered_compute_fingerprint=pre["compute_fingerprint"],
        render_contract_token=pre["render_contract_token"],
        rendered_counts=pre["expected_counts"],
        rendered_fact_keys=pre["expected_fact_keys"],
        rendered_model_keys=pre["expected_model_keys"],
        rendered_mini_league_denominator_complete=True,
        rendered_weather_contract_state=state,
        truncated=False,
    )


def test_deep_accepts_visible_degraded_weather_block_when_tool_is_unavailable():
    pre = _pre(report_mode="DEEP", weather_contract_state="SOURCE_DEGRADED")
    post = _post(pre, state="SOURCE_DEGRADED")

    assert pre["status"] == "PASS"
    assert pre["weather_contract_state"] == "SOURCE_DEGRADED"
    assert post["status"] == "PASS"
    assert post["weather_contract_state"] == "SOURCE_DEGRADED"


def test_price_accepts_only_explicit_price_not_in_scope_or_actual_weather():
    explicit = _pre(report_mode="PRICE", weather_contract_state="PRICE_NOT_IN_SCOPE")
    actual = _pre(report_mode="PRICE", weather_contract_state="DIRECT_CHATGPT")
    missing = _pre(report_mode="PRICE", weather_contract_state="MISSING")

    assert explicit["status"] == "PASS"
    assert actual["status"] == "PASS"
    assert missing["status"] == "FAIL"
    assert "WEATHER_CONTRACT_INVALID=PRICE:MISSING" in missing["failures"]


def test_deep_rejects_price_only_weather_escape_hatch():
    outcome = _pre(report_mode="DEEP", weather_contract_state="PRICE_NOT_IN_SCOPE")

    assert outcome["status"] == "FAIL"
    assert "WEATHER_CONTRACT_INVALID=DEEP:PRICE_NOT_IN_SCOPE" in outcome["failures"]


def test_match_accepts_current_weather_or_explicit_degraded_line():
    current = _pre(report_mode="MATCH", weather_contract_state="MATCH_CURRENT")
    degraded = _pre(report_mode="MATCH", weather_contract_state="SOURCE_DEGRADED")

    assert current["status"] == "PASS"
    assert degraded["status"] == "PASS"


def test_post_render_rejects_weather_state_drift_from_approved_contract():
    pre = _pre(report_mode="DEEP", weather_contract_state="SOURCE_DEGRADED")
    post = _post(pre, state="DIRECT_CHATGPT")

    assert pre["status"] == "PASS"
    assert post["status"] == "FAIL"
    assert "WEATHER_CONTRACT_STATE_MISMATCH=DIRECT_CHATGPT!=SOURCE_DEGRADED" in post["failures"]
    assert "VISIBLE_WEATHER_CONTRACT_STATE_MISMATCH=DIRECT_CHATGPT!=SOURCE_DEGRADED" in post["failures"]
