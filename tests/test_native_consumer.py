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
        elif section_id == "S08":
            content = "Current C: I; Current VC: Keeper; state LOCK.\n"
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
    assert result["native_pitch"]["captain"] == "I"
    assert result["native_pitch"]["vice_captain"] == "Keeper"
    assert result["native_pitch"]["captain_vice_in_xi"] is True
    assert result["native_pitch"]["structure_integrity"] == "PASS"
    assert result["native_pitch"]["structure_failures"] == []
    assert result["native_pitch"]["visual_contract"]["theme"] == "PREMIUM_DARK_GREEN"
    assert result["native_pitch"]["visual_contract"]["bench_orientation"] == "HORIZONTAL"
    assert result["native_pitch"]["visual_contract"]["captain_vice_badges"] == "SMALL_ADJACENT_TO_NAME"
    assert result["native_pitch"]["visual_contract"]["club_jersey_policy"] == "EXACT_OFFICIAL_CLUB_ID_REQUIRED"
    assert [item["name"] for item in result["native_pitch"]["horizontal_bench"]] == ["GK2", "K", "L", "M"]
    assert all(player["jersey"] is None
               for row in result["native_pitch"]["visual_rows"]
               for player in row["players"])
    assert result["native_pitch"]["visual_rows"][0]["players"][0]["badge"] == "C"
    assert result["native_pitch"]["visual_rows"][-1]["players"][0]["badge"] == "VC"
    assert result["native_pitch"]["visual_readiness"] == "PARTIAL_CLUB_JERSEYS_UNAVAILABLE"
    assert result["native_pitch"]["rows"][0]["players"] == ["I", "J"]
    assert all("<style>" not in str(block) for block in result["pitch"]["native_blocks"])
    assert result["rendered_section_ids"] == list(DEEP_MANDATORY_SECTIONS)
    assert result["section_count"] == 22
    assert result["pitch"]["section_id"] == "S06"
    assert len(result["tables"]["S15B"]["rows"]) == 60
    assert len(result["profiles"]["S16"]) == 15
    assert result["typed_panels"]["S18"]["status"] == "PRESENT"

    # Malformed visual payload must never be reported structurally complete.
    # This is a source-text fixture, not a natural or host-render acceptance.
    malformed = body.replace("Bench 1: K", "Bench 1: A")
    bad_artifact = build_lossless_native_content(
        canonical_body=malformed,
        report_slot="2026-10-12T20:00:00+07:00",
        canonical_body_sha256=sha256(malformed.encode()).hexdigest(),
    )
    bad_manifest, bad_files = build_manifest_chunks(bad_artifact, max_chunk_bytes=512)
    bad = consume_native_content(
        bad_manifest, bad_files, canonical_body=malformed,
        user_visible_acceptance=True, transport_status="PASS", remote_readback="PASS",
    )
    assert bad["native_pitch"]["structure_integrity"] == "FAIL"
    assert "BENCH_OVERLAPS_XI" in bad["native_pitch"]["structure_failures"]
    assert bad["acceptance"]["verification_status"] == "UNVERIFIED"


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

    # A structurally invalid pitch remains UNVERIFIED even with a correctly
    # signed *synthetic* host receipt and full byte-for-byte manifest parity.
    malformed = body.replace("Bench 1: K", "Bench 1: A")
    broken_artifact = build_lossless_native_content(
        canonical_body=malformed,
        report_slot=manifest["report_slot"],
        canonical_body_sha256=sha256(malformed.encode()).hexdigest(),
    )
    broken_manifest, broken_files = build_manifest_chunks(broken_artifact, max_chunk_bytes=512)
    broken_manifest["occurrence_path"] = manifest["occurrence_path"]
    broken = consume_native_content(
        broken_manifest, broken_files, canonical_body=malformed,
        user_visible_acceptance=True, transport_status="PASS", remote_readback="PASS",
        native_host_receipt=_signed_native_receipt(broken_manifest, key),
        native_host_verification_key=key,
    )
    assert broken["native_pitch"]["structure_integrity"] == "FAIL"
    assert broken["acceptance"]["verification_status"] == "UNVERIFIED"

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
