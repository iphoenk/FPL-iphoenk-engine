from __future__ import annotations

from hashlib import sha256

import pytest

from src.engines.v12_native_content_parity import (
    NativeContentParityError,
    build_lossless_native_content,
    validate_lossless_native_content,
)
from src.runtime_v6.domains.report_plane.delivery_integrity import (
    DEEP_MANDATORY_SECTIONS,
    DEEP_WITH_S16B_SECTIONS,
)


def _source(ids=DEEP_MANDATORY_SECTIONS):
    header = "FPL MASTER V12 — DEEP REPORT\\nSlot: 2026-10-12T16:32:00+07:00\\n\\n"
    sections = []
    for section_id in ids:
        number = section_id[1:].lstrip("0")
        if section_id == "S06":
            body = (
                "Status: COMPLETE\\n"
                "<style>.pitch { color: green; }</style>\\n"
                "<section class='pitch'>C / VC</section>\\n"
                "Captain: Haaland; Vice: Verbruggen\\n"
            )
        elif section_id == "S15B":
            body = (
                "Status: COMPLETE\\n"
                "| Player | Owned | Captain | EO |\\n"
                "| --- | --- | --- | --- |\\n"
                + "".join(
                    f"| Player {i} | {i}/58 | {i}/58 | {i}.0% |\\n"
                    for i in range(58)
                )
            )
        elif section_id == "S16":
            body = "".join(
                f"### PLAYER {i} — Player {i}\\n"
                f"P(start): {i / 100:.2f}; xMins: {i + 45}\\n"
                for i in range(1, 16)
            )
        else:
            body = "Status: COMPLETE\\nValue: 0.1234; UNAVAILABLE stays UNAVAILABLE\\n"
        sections.append(f"## {number}. SECTION {section_id}\\n{body}\\n")
    return header + "".join(sections)


@pytest.mark.parametrize("ids", [DEEP_MANDATORY_SECTIONS, DEEP_WITH_S16B_SECTIONS])
def test_all_sections_lossless_with_tables_and_profiles(ids):
    body = _source(ids)
    manifest = build_lossless_native_content(
        canonical_body=body,
        report_slot="2026-10-12T16:32:00+07:00",
        canonical_body_sha256=sha256(body.encode("utf-8")).hexdigest(),
    )
    assert manifest["transport_parity"] == "PASS"
    assert manifest["native_chatgpt_render_acceptance"] == "UNVERIFIED"
    assert manifest["section_count"] == len(ids)
    assert manifest["section_ids"] == list(ids)
    assert manifest["source_bytes"] == len(body.encode("utf-8"))
    assert "".join([manifest["prefix"]] + [s["source"] for s in manifest["sections"]]) == body
    league = next(s for s in manifest["sections"] if s["section_id"] == "S15B")
    assert league["table_line_count"] == 60
    assert "Player 57" in league["source"]
    all15 = next(s for s in manifest["sections"] if s["section_id"] == "S16")
    assert all15["source"].count("### PLAYER") == 15
    pitch = next(s for s in manifest["sections"] if s["section_id"] == "S06")
    assert pitch["source_markup_present"] is True
    assert manifest["source_markup_is_native_proof"] is False


def test_reject_missing_section_instead_of_claiming_22():
    body = _source().replace("## 11. SECTION S11", "### 11. SECTION S11")
    with pytest.raises(NativeContentParityError, match="order/count"):
        build_lossless_native_content(
            canonical_body=body,
            report_slot="2026-10-12T16:32:00+07:00",
            canonical_body_sha256=sha256(body.encode()).hexdigest(),
        )


def test_reject_mismatched_canonical_hash():
    with pytest.raises(NativeContentParityError, match="SHA256"):
        build_lossless_native_content(
            canonical_body=_source(),
            report_slot="2026-10-12T16:32:00+07:00",
            canonical_body_sha256="0" * 64,
        )


def test_reject_truncated_section_block_even_if_source_is_retained():
    body = _source()
    manifest = build_lossless_native_content(
        canonical_body=body,
        report_slot="2026-10-12T16:32:00+07:00",
        canonical_body_sha256=sha256(body.encode()).hexdigest(),
    )
    manifest["sections"][1]["blocks"].pop()
    with pytest.raises(NativeContentParityError, match="block round-trip"):
        validate_lossless_native_content(manifest, canonical_body=body)
