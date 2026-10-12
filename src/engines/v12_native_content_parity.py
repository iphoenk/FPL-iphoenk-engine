from __future__ import annotations

"""Lossless DEEP section transport for a native ChatGPT presentation consumer.

This is a PRIVATE, occurrence-bound content artifact, not an HTML renderer or
proof that the ChatGPT UI has displayed anything. The consumer must acknowledge
actual native rendering separately. All source bytes remain reconstructable.
"""

from hashlib import sha256
import re
from typing import Any, Mapping, Sequence

from src.runtime_v6.domains.report_plane.delivery_integrity import (
    DEEP_MANDATORY_SECTIONS,
    DEEP_WITH_S16B_SECTIONS,
)


class NativeContentParityError(ValueError):
    """A DEEP source cannot be transported without content loss."""


_HEADING = re.compile(r"^## ([0-9]+[A-Z]?)\\. ([^\\n]+)(?:\\n|$)", re.MULTILINE)


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
