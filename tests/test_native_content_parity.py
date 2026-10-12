from __future__ import annotations

from hashlib import sha256

import pytest

from src.engines.v12_native_content_parity import (
    NativeContentParityError,
    build_manifest_chunks,
    build_native_ui_acceptance,
    build_lossless_native_content,
    validate_lossless_native_content,
)


def test_manifest_chunks_round_trip_and_small_chunk_boundaries():
    body = _source()
    artifact = build_lossless_native_content(
        canonical_body=body,
        report_slot="2026-10-12T18:57:00+07:00",
        canonical_body_sha256=sha256(body.encode()).hexdigest(),
    )
    manifest, files = build_manifest_chunks(artifact, max_chunk_bytes=256)
    assert manifest["transport_parity"] == "PASS"
    assert manifest["chunk_count"] == len(files) > len(DEEP_MANDATORY_SECTIONS)
    assert manifest["expected_section_count"] == 22
    assert all(len(value.encode()) <= 600 for value in files.values())


def test_manifest_records_canonical_bytes_and_keeps_encoded_chunks_under_limit():
    body = _source()
    artifact = build_lossless_native_content(
        canonical_body=body,
        report_slot="2026-10-12T18:57:00+07:00",
        canonical_body_sha256=sha256(body.encode()).hexdigest(),
    )
    manifest, files = build_manifest_chunks(artifact, max_chunk_bytes=256)
    assert manifest["canonical_body_bytes"] == len(body.encode())
    assert all(len(value.encode()) <= 256 for value in files.values())
    assert all(entry["byte_length"] == len(files[entry["path"]].encode()) for entry in manifest["chunks"])


def test_manifest_rejects_part_count_and_part_order_corruption():
    body = _source()
    artifact = build_lossless_native_content(
        canonical_body=body,
        report_slot="2026-10-12T18:57:00+07:00",
        canonical_body_sha256=sha256(body.encode()).hexdigest(),
    )
    manifest, files = build_manifest_chunks(artifact, max_chunk_bytes=256)
    if manifest["chunk_count"] < 2:
        pytest.fail("fixture must produce multiple chunks")
    manifest["chunks"][0]["part_count"] += 1
    with pytest.raises(NativeContentParityError, match="part count"):
        from src.engines.v12_native_content_parity import validate_manifest_chunks
        validate_manifest_chunks(manifest, files, canonical_body=body)


def test_manifest_rejects_noncanonical_section_catalog():
    body = _source()
    artifact = build_lossless_native_content(
        canonical_body=body,
        report_slot="2026-10-12T18:57:00+07:00",
        canonical_body_sha256=sha256(body.encode()).hexdigest(),
    )
    manifest, files = build_manifest_chunks(artifact, max_chunk_bytes=256)
    manifest["section_ids"] = list(reversed(manifest["section_ids"]))
    from src.engines.v12_native_content_parity import validate_manifest_chunks
    with pytest.raises(NativeContentParityError, match="section catalog"):
        validate_manifest_chunks(manifest, files, canonical_body=body)


def test_native_ui_acceptance_requires_transport_and_remote_readback():
    body = _source()
    artifact = build_lossless_native_content(
        canonical_body=body,
        report_slot="2026-10-12T18:57:00+07:00",
        canonical_body_sha256=sha256(body.encode()).hexdigest(),
    )
    manifest, files = build_manifest_chunks(artifact, max_chunk_bytes=256)
    receipt = build_native_ui_acceptance(
        manifest,
        rendered_section_ids=manifest["section_ids"],
        rendered_content=body,
        user_visible_acceptance=True,
        transport_status="PASS",
        remote_readback="UNVERIFIED",
        files=files,
        canonical_body=body,
    )
    assert receipt["verification_status"] == "UNVERIFIED"


def test_manifest_chunks_reject_missing_swapped_and_corrupt_chunks():
    body = _source()
    artifact = build_lossless_native_content(
        canonical_body=body,
        report_slot="2026-10-12T18:57:00+07:00",
        canonical_body_sha256=sha256(body.encode()).hexdigest(),
    )
    manifest, files = build_manifest_chunks(artifact, max_chunk_bytes=256)
    removed = dict(files)
    removed.pop(next(iter(removed)))
    with pytest.raises(NativeContentParityError, match="chunk count"):
        from src.engines.v12_native_content_parity import validate_manifest_chunks
        validate_manifest_chunks(manifest, removed, canonical_body=body)
    corrupt = dict(files)
    corrupt[next(iter(corrupt))] = corrupt[next(iter(corrupt))].replace("content", "CONTENT", 1)
    with pytest.raises(NativeContentParityError):
        validate_manifest_chunks(manifest, corrupt, canonical_body=body)


def test_native_ui_acceptance_remains_unverified_without_user_visible_ack():
    body = _source()
    artifact = build_lossless_native_content(
        canonical_body=body,
        report_slot="2026-10-12T18:57:00+07:00",
        canonical_body_sha256=sha256(body.encode()).hexdigest(),
    )
    receipt = build_native_ui_acceptance(
        artifact,
        rendered_section_ids=artifact["section_ids"],
        rendered_content=body,
        user_visible_acceptance=False,
    )
    assert receipt["verification_status"] == "UNVERIFIED"
from src.runtime_v6.domains.report_plane.delivery_integrity import (
    DEEP_MANDATORY_SECTIONS,
    DEEP_WITH_S16B_SECTIONS,
)


def _source(ids=DEEP_MANDATORY_SECTIONS):
    header = "FPL MASTER V12 — DEEP REPORT\nSlot: 2026-10-12T16:32:00+07:00\n\n"
    sections = []
    for section_id in ids:
        number = section_id[1:].lstrip("0")
        if section_id == "S06":
            body = (
                "Status: COMPLETE\n"
                "<style>.pitch { color: green; }</style>\n"
                "<section class='pitch'>C / VC</section>\n"
                "Captain: Haaland; Vice: Verbruggen\n"
            )
        elif section_id == "S15B":
            body = (
                "Status: COMPLETE\n"
                "| Player | Owned | Captain | EO |\n"
                "| --- | --- | --- | --- |\n"
                + "".join(
                    f"| Player {i} | {i}/58 | {i}/58 | {i}.0% |\n"
                    for i in range(58)
                )
            )
        elif section_id == "S16":
            body = "".join(
                f"### PLAYER {i} — Player {i}\n"
                f"P(start): {i / 100:.2f}; xMins: {i + 45}\n"
                for i in range(1, 16)
            )
        else:
            body = "Status: COMPLETE\nValue: 0.1234; UNAVAILABLE stays UNAVAILABLE\n"
        sections.append(f"## {number}. SECTION {section_id}\n{body}\n")
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
