from __future__ import annotations

"""Lossless DEEP section transport for a native ChatGPT presentation consumer.

This is a PRIVATE, occurrence-bound content artifact, not an HTML renderer or
proof that the ChatGPT UI has displayed anything. The consumer must acknowledge
actual native rendering separately. All source bytes remain reconstructable.
"""

from hashlib import sha256
import hmac
import json
import re
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from src.runtime_v6.domains.report_plane.delivery_integrity import (
    DEEP_MANDATORY_SECTIONS,
    DEEP_WITH_S16B_SECTIONS,
)


class NativeContentParityError(ValueError):
    """A DEEP source cannot be transported without content loss."""


MAX_NATIVE_CHUNK_BYTES = 16 * 1024


_HEADING = re.compile(r"^## ([0-9]+[A-Z]?)\. ([^\n]+)(?:\n|$)", re.MULTILINE)


def _id(number: str) -> str:
    digits = re.match(r"([0-9]+)([A-Z]?)$", number)
    if not digits:
        raise NativeContentParityError("invalid section heading")
    return f"S{int(digits.group(1)):02d}{digits.group(2)}"


def _line_kind(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith("|"):
        return "table_line"
    if stripped.startswith("### "):
        return "subheading"
    if stripped.startswith(("- ", "* ", "1. ", "2. ", "3. ")):
        return "list_line"
    if stripped.startswith(("<", "</", "<style", "<section")):
        return "source_markup"
    if stripped.startswith("```"):
        return "code_fence"
    return "text"


def _blocks(section_text: str) -> list[dict[str, Any]]:
    # Each block owns its exact source substring; no strip(), markdown
    # reserialization, CSS minification, or invisible row cap is permitted.
    blocks: list[dict[str, Any]] = []
    for line in section_text.splitlines(keepends=True):
        kind = _line_kind(line)
        if blocks and blocks[-1]["kind"] == kind:
            blocks[-1]["source"] += line
            blocks[-1]["line_count"] += 1
        else:
            blocks.append({"kind": kind, "source": line, "line_count": 1})
    return blocks


def build_lossless_native_content(
    *,
    canonical_body: str,
    report_slot: str,
    canonical_body_sha256: str,
    canonical_sections: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Produce all 22/23 DEEP sections with exact source and typed blocks.

    Canonical section payloads are optional because older serving bundles may
    not expose them; their absence must be declared, never fabricated.
    """
    if not isinstance(canonical_body, str) or not canonical_body:
        raise NativeContentParityError("canonical DEEP body missing")
    digest = sha256(canonical_body.encode("utf-8")).hexdigest()
    if digest != canonical_body_sha256:
        raise NativeContentParityError("canonical body SHA256 mismatch")
    headings = list(_HEADING.finditer(canonical_body))
    if not headings:
        raise NativeContentParityError("DEEP headings missing")
    found = [_id(m.group(1)) for m in headings]
    expected = (
        list(DEEP_WITH_S16B_SECTIONS)
        if "S16B" in found
        else list(DEEP_MANDATORY_SECTIONS)
    )
    if found != expected:
        raise NativeContentParityError(
            f"DEEP section order/count mismatch: found={found} expected={expected}"
        )
    canonical = {
        str(section.get("section_id") or ""): section
        for section in (canonical_sections or [])
        if isinstance(section, Mapping)
    }
    prefix = canonical_body[: headings[0].start()]
    sections: list[dict[str, Any]] = []
    for i, match in enumerate(headings):
        section_id = found[i]
        source = canonical_body[
            match.start() : headings[i + 1].start()
            if i + 1 < len(headings) else len(canonical_body)
        ]
        blocks = _blocks(source)
        if "".join(block["source"] for block in blocks) != source:
            raise NativeContentParityError(f"block content lost: {section_id}")
        section: dict[str, Any] = {
            "section_id": section_id,
            "label": match.group(2),
            "source": source,
            "source_sha256": sha256(source.encode("utf-8")).hexdigest(),
            "blocks": blocks,
            "source_bytes": len(source.encode("utf-8")),
            "table_line_count": sum(
                block["line_count"] for block in blocks
                if block["kind"] == "table_line"
            ),
            "source_markup_present": any(
                block["kind"] == "source_markup" for block in blocks
            ),
        }
        if section_id in canonical:
            section["canonical_content"] = canonical[section_id].get("content")
            section["canonical_state"] = canonical[section_id].get("state")
        else:
            section["canonical_content_status"] = "NOT_PROVIDED"
        sections.append(section)
    artifact = {
        "schema": "V12_DEEP_NATIVE_LOSSLESS_CONTENT_V1",
        "report_slot": report_slot,
        "canonical_body_sha256": digest,
        "section_ids": found,
        "section_count": len(sections),
        "prefix": prefix,
        "sections": sections,
        "source_bytes": len(canonical_body.encode("utf-8")),
        "transport_parity": "PASS",
        "native_chatgpt_render_acceptance": "UNVERIFIED",
        "source_markup_is_native_proof": False,
        "content_truncation_allowed": False,
    }
    validate_lossless_native_content(artifact, canonical_body=canonical_body)
    return artifact


def validate_lossless_native_content(
    artifact: Mapping[str, Any], *, canonical_body: str
) -> None:
    sections = artifact.get("sections") or []
    rebuilt = str(artifact.get("prefix") or "") + "".join(
        str(section.get("source") or "") for section in sections
    )
    if rebuilt != canonical_body:
        raise NativeContentParityError("canonical content round-trip mismatch")
    if sha256(rebuilt.encode("utf-8")).hexdigest() != artifact.get(
        "canonical_body_sha256"
    ):
        raise NativeContentParityError("canonical content hash mismatch")
    for section in sections:
        if "".join(
            str(block.get("source") or "") for block in section.get("blocks") or []
        ) != section.get("source"):
            raise NativeContentParityError(
                f"block round-trip mismatch: {section.get('section_id')}"
            )
        if sha256(section["source"].encode("utf-8")).hexdigest() != section.get(
            "source_sha256"
        ):
            raise NativeContentParityError(
                f"section hash mismatch: {section.get('section_id')}"
            )
    if artifact.get("section_count") != len(sections):
        raise NativeContentParityError("section count mismatch")


def _encode_chunk(
    section_id: str, part_index: int, part_count: int, content: str
) -> str:
    payload = {
        "section_id": section_id,
        "part_index": part_index,
        "part_count": part_count,
        "source_bytes": len(content.encode("utf-8")),
        "source_sha256": sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def _chunk_lines(
    section: Mapping[str, Any], max_bytes: int, *, section_id: str
) -> list[str]:
    lines = str(section.get("source") or "").splitlines(keepends=True)
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = current + line
        # Reserve enough metadata width for the final part count. This keeps
        # the serialized JSON file, not merely its content string, under the
        # connector-safe limit.
        encoded_size = len(
            _encode_chunk(section_id, 999999, 999999, candidate).encode("utf-8")
        )
        if current and encoded_size > max_bytes:
            chunks.append(current)
            current = line
        elif not current and encoded_size > max_bytes:
            raise NativeContentParityError(
                f"single Markdown line exceeds chunk limit: {section_id}"
            )
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current)
    return chunks


def build_manifest_chunks(
    artifact: Mapping[str, Any], *, max_chunk_bytes: int = MAX_NATIVE_CHUNK_BYTES
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build lossless, line-bound chunks and a compact verification manifest."""
    if max_chunk_bytes <= 0:
        raise NativeContentParityError("invalid chunk limit")
    section_ids = list(artifact.get("section_ids") or [])
    sections = list(artifact.get("sections") or [])
    if section_ids != [str(row.get("section_id") or "") for row in sections]:
        raise NativeContentParityError("section order mismatch")
    files: dict[str, str] = {}
    entries: list[dict[str, Any]] = []
    chunk_count = 0
    for section_id, section in zip(section_ids, sections):
        parts = _chunk_lines(section, max_chunk_bytes, section_id=section_id)
        for index, content in enumerate(parts):
            path = str(PurePosixPath("native_content") / f"{section_id}.part-{index:03d}.json")
            encoded = _encode_chunk(section_id, index, len(parts), content)
            if len(encoded.encode("utf-8")) > max_chunk_bytes:
                raise NativeContentParityError("serialized chunk exceeds chunk limit")
            files[path] = encoded
            entries.append({
                "path": path,
                "section_id": section_id,
                "part_index": index,
                "part_count": len(parts),
                "byte_length": len(encoded.encode("utf-8")),
                "sha256": sha256(encoded.encode("utf-8")).hexdigest(),
            })
            chunk_count += 1
    manifest = {
        "schema": "V12_DEEP_NATIVE_MANIFEST_CHUNKS_V1",
        "report_slot": artifact.get("report_slot"),
        "occurrence_path": None,
        "canonical_body_sha256": artifact.get("canonical_body_sha256"),
        "canonical_body_bytes": artifact.get("source_bytes"),
        "prefix": artifact.get("prefix") or "",
        "section_ids": section_ids,
        "expected_section_count": len(section_ids),
        "chunk_count": chunk_count,
        "chunks": entries,
        "transport_parity": "PASS",
        "remote_readback": "UNVERIFIED",
        "native_ui_acceptance": "UNVERIFIED",
        "verification_status": "TRANSPORT_PASS",
    }
    validate_manifest_chunks(manifest, files, canonical_body=str(artifact.get("prefix") or "") + "".join(str(s.get("source") or "") for s in sections))
    return manifest, files


def validate_manifest_chunks(
    manifest: Mapping[str, Any], files: Mapping[str, str], *, canonical_body: str
) -> None:
    entries = list(manifest.get("chunks") or [])
    if manifest.get("chunk_count") != len(entries) or len(files) != len(entries):
        raise NativeContentParityError("chunk count mismatch")
    if manifest.get("canonical_body_bytes") != len(canonical_body.encode("utf-8")):
        raise NativeContentParityError("canonical byte length mismatch")
    section_ids = list(manifest.get("section_ids") or [])
    expected_sections = (
        list(DEEP_WITH_S16B_SECTIONS)
        if "S16B" in section_ids
        else list(DEEP_MANDATORY_SECTIONS)
    )
    if section_ids != expected_sections or manifest.get("expected_section_count") != len(expected_sections):
        raise NativeContentParityError("section catalog mismatch")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        path = str(entry.get("path") or "")
        if path not in files:
            raise NativeContentParityError("chunk missing")
        raw = files[path]
        if entry.get("byte_length") != len(raw.encode("utf-8")):
            raise NativeContentParityError("chunk byte length mismatch")
        if sha256(raw.encode("utf-8")).hexdigest() != entry.get("sha256"):
            raise NativeContentParityError("chunk hash mismatch")
        payload = json.loads(raw)
        content = payload.get("content")
        if not isinstance(content, str) or not content:
            raise NativeContentParityError("chunk empty")
        for key in ("section_id", "part_index", "part_count"):
            if payload.get(key) != entry.get(key):
                label = key.replace("_", " ")
                raise NativeContentParityError(f"chunk {label} mismatch")
        if len(content.encode("utf-8")) != payload.get("source_bytes"):
            raise NativeContentParityError("chunk byte length mismatch")
        if sha256(content.encode("utf-8")).hexdigest() != payload.get("source_sha256"):
            raise NativeContentParityError("chunk source hash mismatch")
        grouped.setdefault(str(payload.get("section_id")), []).append(payload)
    if list(grouped) != section_ids:
        raise NativeContentParityError("section missing or duplicated")
    rebuilt = str(manifest.get("prefix") or "")
    for section_id in section_ids:
        parts = sorted(grouped[section_id], key=lambda row: int(row.get("part_index", -1)))
        expected = len(parts)
        if [p.get("part_index") for p in parts] != list(range(expected)):
            raise NativeContentParityError("chunk order mismatch")
        if any(p.get("part_count") != expected for p in parts):
            raise NativeContentParityError("chunk part count mismatch")
        rebuilt += "".join(p["content"] for p in parts)
    if rebuilt != canonical_body:
        raise NativeContentParityError("canonical round-trip mismatch")
    if sha256(rebuilt.encode("utf-8")).hexdigest() != manifest.get("canonical_body_sha256"):
        raise NativeContentParityError("canonical SHA256 mismatch")


def _valid_native_host_receipt(
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
    *,
    rendered_section_ids: Sequence[str],
    verification_key: bytes | None,
) -> bool:
    """Verify the *shape and occurrence binding* of a host-render event.

    Only the actual ChatGPT native UI host may issue this receipt. Backend
    tests, Python component construction, source Markdown/HTML, and a caller's
    boolean cannot substitute for an observed user-visible host event.
    """
    if not isinstance(receipt, Mapping) or not isinstance(verification_key, bytes) or len(verification_key) < 16:
        return False
    fields = (
        "source", "render_surface", "user_visible", "host_render_event_id",
        "report_slot", "occurrence_path", "canonical_body_sha256",
        "rendered_section_ids", "consumed_chunk_paths",
        "native_section_component_count", "native_chunk_count",
    )
    if any(field not in receipt for field in fields):
        return False
    message = json.dumps(
        {field: receipt[field] for field in fields},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    candidate = receipt.get("signature_sha256")
    if not isinstance(candidate, str) or not hmac.compare_digest(
        hmac.new(verification_key, message, sha256).hexdigest(), candidate,
    ):
        return False
    expected_sections = list(manifest.get("section_ids") or [])
    expected_paths = [
        str(entry.get("path") or "") for entry in (manifest.get("chunks") or [])
    ]
    event_id = receipt.get("host_render_event_id")
    return (
        receipt.get("source") == "CHATGPT_NATIVE_HOST"
        and receipt.get("render_surface") == "CHATGPT_NATIVE_COMPONENTS"
        and receipt.get("user_visible") is True
        and isinstance(event_id, str)
        and bool(event_id.strip())
        and isinstance(receipt.get("occurrence_path"), str)
        and bool(receipt.get("occurrence_path"))
        and receipt.get("report_slot") == manifest.get("report_slot")
        and receipt.get("occurrence_path") == manifest.get("occurrence_path")
        and receipt.get("canonical_body_sha256") == manifest.get("canonical_body_sha256")
        and receipt.get("rendered_section_ids") == expected_sections
        and list(rendered_section_ids) == expected_sections
        and receipt.get("consumed_chunk_paths") == expected_paths
        and receipt.get("native_section_component_count") == len(expected_sections)
        and receipt.get("native_chunk_count") == len(expected_paths)
        and len(expected_paths) == manifest.get("chunk_count")
        and len(set(expected_paths)) == len(expected_paths)
    )


def build_native_ui_acceptance(
    manifest: Mapping[str, Any], *, rendered_section_ids: Sequence[str],
    rendered_content: str, user_visible_acceptance: bool,
    transport_status: str = "UNVERIFIED", remote_readback: str = "UNVERIFIED",
    files: Mapping[str, str] | None = None, canonical_body: str | None = None,
    native_host_receipt: Mapping[str, Any] | None = None,
    native_host_verification_key: bytes | None = None,
) -> dict[str, Any]:
    """Fail closed unless the native UI host actually acknowledges this occurrence.

    The host receipt is a required external integration boundary, not an
    artefact this Python producer or its unit tests can generate in production.
    """
    expected = list(manifest.get("section_ids") or [])
    manifest_valid = False
    if files is not None and canonical_body is not None:
        try:
            validate_manifest_chunks(manifest, files, canonical_body=canonical_body)
            manifest_valid = True
        except (NativeContentParityError, KeyError, TypeError, ValueError):
            pass
    reconstructed_hash_valid = (
        sha256(rendered_content.encode("utf-8")).hexdigest()
        == manifest.get("canonical_body_sha256")
    )
    host_acknowledged = _valid_native_host_receipt(
        manifest,
        native_host_receipt,
        rendered_section_ids=rendered_section_ids,
        verification_key=native_host_verification_key,
    )
    status = "PASS" if (
        user_visible_acceptance
        and host_acknowledged
        and str(transport_status).upper() == "PASS"
        and str(remote_readback).upper() == "PASS"
        and manifest_valid
        and list(rendered_section_ids) == expected
        and reconstructed_hash_valid
    ) else "UNVERIFIED"
    return {
        "native_ui_consumer": "PASS" if status == "PASS" else "UNVERIFIED",
        "native_ui_section_count": len(rendered_section_ids),
        "native_ui_rendered_section_ids": list(rendered_section_ids),
        "native_ui_content_hash": sha256(rendered_content.encode("utf-8")).hexdigest(),
        "native_ui_matches_manifest": "PASS" if status == "PASS" else "UNVERIFIED",
        "native_ui_all_chunks_consumed": "PASS" if status == "PASS" else "UNVERIFIED",
        "native_ui_user_visible_acceptance": "PASS" if status == "PASS" else "UNVERIFIED",
        "native_ui_host_receipt": "PASS" if host_acknowledged and status == "PASS" else "UNVERIFIED",
        "verification_status": "VERIFIED" if status == "PASS" else "UNVERIFIED",
    }
