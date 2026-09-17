from __future__ import annotations

from src.runtime_v6.delivery_integrity import MANDATORY_SECTIONS
from src.runtime_v6.report_qa import validate_post_render_qa, validate_pre_render_qa


def _compute_contract() -> dict:
    return {
        "status": "PASS",
        "compute_ready": True,
        "delivery_ready": False,
        "next_action": "PRE_RENDER_QA",
        "legacy_fallback_allowed": False,
        "compute_fingerprint": "a" * 64,
        "OUR15": {"status": "PASS", "total": 15},
        "XI": {"status": "PASS", "total": 11},
        "BENCH": {"status": "PASS", "total": 4},
        "WATCHLIST20": {"status": "PASS", "total": 20},
        "RISE20": {"status": "PASS", "total": 20},
        "FALL20": {"status": "PASS", "total": 20},
        "FACT_MODEL": {
            "status": "PASS",
            "overlap": [],
            "fact_keys": ["official_price"],
            "model_keys": ["price_projection"],
            "inference_keys": ["transfer_call"],
        },
    }


def _pre_render() -> dict:
    return validate_pre_render_qa(
        compute_contract=_compute_contract(),
        section_manifest=[
            {"section_id": section_id, "status": "COMPLETE"}
            for section_id in MANDATORY_SECTIONS
        ],
        mini_league_denominator_complete=True,
        weather_required=True,
        weather_direct_chat_present=True,
    )


def _table(header: str, rows: list[tuple[str, ...]]) -> list[str]:
    columns = header.split("|")
    return [
        f"| {header} |",
        "| " + " | ".join("---" for _ in columns) + " |",
        *["| " + " | ".join(row) + " |" for row in rows],
    ]


def _valid_body(*, rise_count: int = 20, include_14b: bool = True, include_inference: bool = True) -> str:
    lines = ["# 04:30 MORNING DEEP REVIEW"]
    titles = {
        "S02": "OUR15 MANUAL FPL STATE",
        "S05": "EXACT FORMATION / XI / BENCH",
        "S10": "WATCHLIST20",
        "S11": "RISE20",
        "S12": "FALL20",
        "S14": "EVIDENCE",
        "S14B": "ICON+ MINI LEAGUE",
        "S15": "ALL15 NEXT-GW TACTICAL",
        "S16": "SOURCE HEALTH",
    }
    for section_id in MANDATORY_SECTIONS:
        if section_id == "S14B" and not include_14b:
            continue
        display = section_id.removeprefix("S")
        lines.append(f"## SECTION {display} — {titles.get(section_id, 'REPORT SECTION')}")
        if section_id == "S02":
            positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
            lines.extend(_table("#|Player|Pos", [(str(i), f"OWN{i:02d}", pos) for i, pos in enumerate(positions, 1)]))
        elif section_id == "S05":
            lines.append("XI: " + ", ".join(f"OWN{i:02d}" for i in range(1, 12)))
            lines.append("BENCH: " + ", ".join(f"OWN{i:02d}" for i in range(12, 16)))
        elif section_id == "S10":
            positions = ["GK"] * 5 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 5
            lines.extend(_table("#|Player|Pos", [(str(i), f"WATCH{i:02d}", pos) for i, pos in enumerate(positions, 1)]))
        elif section_id == "S11":
            lines.extend(_table("#|Player", [(str(i), f"RISE{i:02d}") for i in range(1, rise_count + 1)]))
        elif section_id == "S12":
            lines.extend(_table("#|Player", [(str(i), f"FALL{i:02d}") for i in range(1, 21)]))
        elif section_id == "S14":
            lines.append("FACT: official_price")
            lines.append("MODEL: price_projection")
            if include_inference:
                lines.append("INFERENCE: transfer_call")
        elif section_id == "S14B":
            lines.append("MINI_LEAGUE_DENOMINATOR: COMPLETE")
            lines.append("Current rank and direct-rival equation are shown.")
        elif section_id == "S15":
            lines.extend(_table("#|Player|Matchup", [(str(i), f"OWN{i:02d}", "B") for i in range(1, 16)]))
        elif section_id == "S16":
            lines.append("WEATHER: DIRECT_CHATGPT")
            lines.append("Source health current.")
        else:
            lines.append("Material section content.")
    return "\n".join(lines) + "\n"


def _post(body: str, **overrides) -> dict:
    pre = _pre_render()
    kwargs = {
        "pre_render_qa": pre,
        "rendered_body": body,
        "rendered_section_ids": list(pre["expected_section_ids"]),
        "rendered_section_states": {row["section_id"]: row["status"] for row in pre["section_manifest"]},
        "rendered_compute_fingerprint": pre["compute_fingerprint"],
        "render_contract_token": pre["render_contract_token"],
        "rendered_counts": dict(pre["expected_counts"]),
        "rendered_fact_keys": list(pre["expected_fact_keys"]),
        "rendered_model_keys": list(pre["expected_model_keys"]),
        "rendered_mini_league_denominator_complete": True,
        "rendered_weather_direct_chat_present": True,
        "truncated": False,
    }
    kwargs.update(overrides)
    return validate_post_render_qa(**kwargs)


def test_valid_visible_body_passes_r6_and_only_advances_to_delivery_proof():
    result = _post(_valid_body())

    assert result["status"] == "PASS"
    assert result["qa_passed"] is True
    assert result["delivery_ready"] is False
    assert result["next_action"] == "BUILD_DELIVERY_PROOF"
    assert result["visible_body_validated"] is True


def test_metadata_cannot_false_pass_a_progress_only_visible_body():
    result = _post("# 04:30 MORNING DEEP REVIEW\nGenerating report...\n")

    assert result["status"] == "FAIL"
    assert result["qa_passed"] is False
    assert "VISIBLE_BODY_PROGRESS_PLACEHOLDER" in result["failures"]
    assert any(item.startswith("VISIBLE_SECTIONS_MISSING=") for item in result["failures"])


def test_visible_body_missing_14b_fails_even_when_metadata_claims_complete():
    result = _post(_valid_body(include_14b=False))

    assert result["status"] == "FAIL"
    assert "VISIBLE_SECTIONS_MISSING=S14B" in result["failures"]


def test_visible_rise20_must_really_have_twenty_rows():
    result = _post(_valid_body(rise_count=19))

    assert result["status"] == "FAIL"
    assert "VISIBLE_COUNT_MISMATCH=RISE20:19!=20" in result["failures"]


def test_visible_fact_model_inference_partition_cannot_drop_inference():
    result = _post(_valid_body(include_inference=False))

    assert result["status"] == "FAIL"
    assert "VISIBLE_INFERENCE_KEYS_MISMATCH" in result["failures"]


def test_visible_body_truncation_marker_fails_even_when_truncated_flag_is_false():
    result = _post(_valid_body() + "[TRUNCATED]\n")

    assert result["status"] == "FAIL"
    assert "VISIBLE_BODY_TRUNCATION_MARKER" in result["failures"]
