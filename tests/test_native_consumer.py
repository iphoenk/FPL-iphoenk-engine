from hashlib import sha256
import hmac
import json

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
            content = ("<style>legacy markup must not render</style>\n"
                       "Formation: 4-4-2\nGK: Keeper\nDEF: A, B, C, D\n"
                       "MID: E, F, G, H\nFWD: I, J\n"
                       "Bench GK: GK2\nBench 1: K\nBench 2: L\nBench 3: M\n")
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
    assert result["acceptance"]["verification_status"] == "UNVERIFIED"
    assert result["acceptance"]["native_ui_host_receipt"] == "UNVERIFIED"
    assert result["consumed_chunk_paths"] == [item["path"] for item in manifest["chunks"]]
    assert result["native_component_count"] == 22
    assert result["native_pitch"]["formation"] == "4-4-2"
    assert result["native_pitch"]["rows"][0]["players"] == ["I", "J"]
    assert all("<style>" not in str(block) for block in result["pitch"]["native_blocks"])
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


def _signed_native_receipt(manifest, key):
    """Synthetic test fixture only; never an actual ChatGPT host event."""
    payload = {
        "source": "CHATGPT_NATIVE_HOST",
        "render_surface": "CHATGPT_NATIVE_COMPONENTS",
        "user_visible": True,
        "host_render_event_id": "synthetic-unit-test-only",
        "report_slot": manifest["report_slot"],
        "occurrence_path": manifest["occurrence_path"],
        "canonical_body_sha256": manifest["canonical_body_sha256"],
        "rendered_section_ids": manifest["section_ids"],
        "consumed_chunk_paths": [item["path"] for item in manifest["chunks"]],
        "native_section_component_count": len(manifest["section_ids"]),
        "native_chunk_count": manifest["chunk_count"],
    }
    message = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    payload["signature_sha256"] = hmac.new(key, message, sha256).hexdigest()
    return payload


def test_native_host_receipt_gates_verified_and_rejects_tampering():
    body = _body()
    artifact = build_lossless_native_content(
        canonical_body=body,
        report_slot="2026-10-13T07:55:00+07:00",
        canonical_body_sha256=sha256(body.encode()).hexdigest(),
    )
    manifest, files = build_manifest_chunks(artifact, max_chunk_bytes=512)
    manifest["occurrence_path"] = "reports/2026-27/gw_7/unit_test_only"
    key = b"synthetic-host-test-verification-key-2026"
    receipt = _signed_native_receipt(manifest, key)
    options = dict(
        canonical_body=body, user_visible_acceptance=True,
        transport_status="PASS", remote_readback="PASS",
        native_host_receipt=receipt, native_host_verification_key=key,
    )
    accepted = consume_native_content(manifest, files, **options)
    assert accepted["acceptance"]["verification_status"] == "VERIFIED"
    assert accepted["acceptance"]["native_ui_all_chunks_consumed"] == "PASS"

    tampered = dict(receipt, native_chunk_count=receipt["native_chunk_count"] - 1)
    rejected = consume_native_content(manifest, files, **dict(options, native_host_receipt=tampered))
    assert rejected["acceptance"]["verification_status"] == "UNVERIFIED"

    rejected_missing_key = consume_native_content(
        manifest, files, **dict(options, native_host_verification_key=None)
    )
    assert rejected_missing_key["acceptance"]["verification_status"] == "UNVERIFIED"

    rejected_wrong_occurrence = consume_native_content(
        manifest, files, **dict(options, native_host_receipt=dict(receipt, report_slot="wrong"))
    )
    assert rejected_wrong_occurrence["acceptance"]["verification_status"] == "UNVERIFIED"
