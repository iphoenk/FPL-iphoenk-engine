from hashlib import sha256

from src.engines.v12_native_consumer import consume_native_content
from src.engines.v12_native_content_parity import (
    build_lossless_native_content,
    build_manifest_chunks,
)
from src.runtime_v6.domains.report_plane.delivery_integrity import DEEP_MANDATORY_SECTIONS


def _body():
    sections = []
    for section_id in DEEP_MANDATORY_SECTIONS:
        number = section_id[1:].lstrip("0")
        if section_id == "S06":
            content = "Starting XI: Player A, Player B\nBench: Player C\nC: Player A\nVC: Player B\n"
        elif section_id == "S15B":
            content = "| Player | Owned | EO |\n| --- | --- | --- |\n" + "".join(
                f"| Player {i} | {i}/58 | {i}.0% |\n" for i in range(58)
            )
        elif section_id == "S16":
            content = "".join(
                f"### PROFILE {i}\nP(start): {i / 100:.2f}\n" for i in range(1, 16)
            )
        else:
            content = "Decision: HOLD\nEvidence: COMPLETE\n"
        sections.append(f"## {number}. SECTION {section_id}\n{content}\n")
    return "Report header\n\n" + "".join(sections)


def test_native_consumer_renders_every_section_row_profile_and_pitch_surface():
    body = _body()
    artifact = build_lossless_native_content(
        canonical_body=body,
        report_slot="2026-10-12T20:00:00+07:00",
        canonical_body_sha256=sha256(body.encode()).hexdigest(),
    )
    manifest, files = build_manifest_chunks(artifact, max_chunk_bytes=512)
    result = consume_native_content(
        manifest,
        files,
        canonical_body=body,
        user_visible_acceptance=True,
        transport_status="PASS",
        remote_readback="PASS",
    )
    assert result["acceptance"]["verification_status"] == "VERIFIED"
    assert result["rendered_section_ids"] == list(DEEP_MANDATORY_SECTIONS)
    assert result["section_count"] == 22
    assert result["pitch"]["section_id"] == "S06"
    assert len(result["tables"]["S15B"]["rows"]) == 60
    assert len(result["profiles"]["S16"]) == 15
    assert result["typed_panels"]["S18"]["status"] == "PRESENT"


def test_native_consumer_rejects_partial_chunk_readback():
    body = _body()
    artifact = build_lossless_native_content(
        canonical_body=body,
        report_slot="2026-10-12T20:00:00+07:00",
        canonical_body_sha256=sha256(body.encode()).hexdigest(),
    )
    manifest, files = build_manifest_chunks(artifact, max_chunk_bytes=512)
    files.pop(next(iter(files)))
    result = consume_native_content(
        manifest,
        files,
        canonical_body=body,
        user_visible_acceptance=True,
        transport_status="PASS",
        remote_readback="PASS",
    )
    assert result["acceptance"]["verification_status"] == "UNVERIFIED"
