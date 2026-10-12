from __future__ import annotations

"""Strict native component consumer for V12 manifest/chunk content.

This module produces structured component data for a native UI. It does not
treat Markdown, HTML, or CSS as rendering proof; the caller must provide a
separate user-visible acceptance acknowledgement.
"""

import re
from typing import Any, Mapping

from src.engines.v12_native_content_parity import (
    NativeContentParityError,
    build_native_ui_acceptance,
    validate_manifest_chunks,
)


_TABLE_LINE = re.compile(r"^\|.*\|\s*$")
_PROFILE_HEADING = re.compile(r"^###\s+", re.MULTILINE)


def _section_sources(manifest: Mapping[str, Any], files: Mapping[str, str]) -> dict[str, str]:
    grouped: dict[str, list[tuple[int, str]]] = {}
    for entry in manifest.get("chunks") or []:
        payload = __import__("json").loads(files[entry["path"]])
        grouped.setdefault(str(payload["section_id"]), []).append(
            (int(payload["part_index"]), str(payload["content"]))
        )
    return {
        section_id: "".join(content for _, content in sorted(parts))
        for section_id, parts in grouped.items()
    }


def consume_native_content(
    manifest: Mapping[str, Any],
    files: Mapping[str, str],
    *,
    canonical_body: str,
    user_visible_acceptance: bool,
    transport_status: str,
    remote_readback: str,
) -> dict[str, Any]:
    expected = list(manifest.get("section_ids") or [])
    rendered_ids: list[str] = []
    sources: dict[str, str] = {}
    valid = True
    try:
        validate_manifest_chunks(manifest, files, canonical_body=canonical_body)
        sources = _section_sources(manifest, files)
        rendered_ids = expected.copy()
    except (NativeContentParityError, KeyError, ValueError, TypeError):
        valid = False

    components = []
    tables: dict[str, dict[str, Any]] = {}
    profiles: dict[str, list[str]] = {}
    typed_panels: dict[str, dict[str, str]] = {}
    for section_id in rendered_ids:
        source = sources[section_id]
        lines = source.splitlines()
        rows = [line for line in lines if _TABLE_LINE.match(line)]
        if rows:
            tables[section_id] = {"rows": rows, "row_count": len(rows)}
        if section_id == "S16":
            profiles[section_id] = [line for line in lines if _PROFILE_HEADING.match(line)]
        typed_panels[section_id] = {"status": "PRESENT", "content": source}
        components.append({
            "section_id": section_id,
            "component": "native_section",
            "content": source,
            "blocks": source.splitlines(keepends=True),
        })

    rendered_content = str(manifest.get("prefix") or "") + "".join(
        component["content"] for component in components
    )
    if not valid:
        rendered_content = ""
        rendered_ids = []
    acceptance = build_native_ui_acceptance(
        manifest,
        rendered_section_ids=rendered_ids,
        rendered_content=rendered_content,
        user_visible_acceptance=user_visible_acceptance,
        transport_status=transport_status,
        remote_readback=remote_readback,
        files=files if valid else {},
        canonical_body=canonical_body,
    )
    return {
        "section_count": len(rendered_ids),
        "rendered_section_ids": rendered_ids,
        "components": components,
        "pitch": next((item for item in components if item["section_id"] == "S06"), None),
        "tables": tables,
        "profiles": profiles,
        "typed_panels": typed_panels,
        "verification_indicators": {
            "transport": str(transport_status).upper(),
            "remote_readback": str(remote_readback).upper(),
            "native_ui": acceptance["native_ui_consumer"],
        },
        "acceptance": acceptance,
    }
