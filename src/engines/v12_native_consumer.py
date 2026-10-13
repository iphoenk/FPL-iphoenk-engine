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



def _native_blocks(source: str) -> list[dict[str, Any]]:
    """Parse report prose into host-ready component descriptors.

    HTML/CSS remains in the canonical source for byte parity, but is never
    treated as a native component or as evidence of user-visible rendering.
    """
    blocks: list[dict[str, Any]] = []
    lines = source.splitlines()
    cursor = 0
    while cursor < len(lines):
        line = lines[cursor]
        stripped = line.strip()
        if not stripped:
            cursor += 1
            continue
        if stripped.startswith("<style") or stripped.startswith("<section"):
            cursor += 1
            continue
        if _TABLE_LINE.match(line):
            rows: list[list[str]] = []
            while cursor < len(lines) and _TABLE_LINE.match(lines[cursor]):
                rows.append([cell.strip() for cell in lines[cursor].strip().strip("|").split("|")])
                cursor += 1
            if len(rows) > 1 and all(
                set(cell.replace(":", "").replace("-", "")) == set()
                for cell in rows[1]
            ):
                rows.pop(1)
            blocks.append({"kind": "table", "rows": rows})
            continue
        if stripped.startswith("#### "):
            blocks.append({"kind": "subheading", "level": 4, "text": stripped[5:]})
        elif stripped.startswith("### "):
            blocks.append({"kind": "subheading", "level": 3, "text": stripped[4:]})
        elif stripped.startswith("## "):
            blocks.append({"kind": "heading", "text": stripped[3:]})
        elif stripped.startswith("- "):
            blocks.append({"kind": "list_item", "text": stripped[2:]})
        else:
            blocks.append({"kind": "paragraph", "text": line})
        cursor += 1
    return blocks


def _native_pitch(source: str, captain_source: str | None = None) -> dict[str, Any]:
    """Use the canonical textual XI/bench fields, never the source HTML."""
    fields: dict[str, str] = {}
    for line in source.splitlines():
        for key in ("Formation", "GK", "DEF", "MID", "FWD", "Bench GK", "Bench 1", "Bench 2", "Bench 3", "C/VC decision authority"):
            if line.startswith(key + ":"):
                fields[key] = line[len(key) + 1:].strip()
                break
    current = re.search(
        r"(?m)^Current C:\\s*([^;\\n]+);\\s*Current VC:\\s*([^;\\n]+)",
        captain_source or "",
    )
    captain = current.group(1).strip() if current else None
    vice_captain = current.group(2).strip() if current else None
    xi_players = {
        name.strip()
        for role in ("GK", "DEF", "MID", "FWD")
        for name in fields.get(role, "").split(",")
        if name.strip()
    }
    return {
        "kind": "pitch",
        "captain": captain,
        "vice_captain": vice_captain,
        "captain_vice_in_xi": bool(captain and vice_captain and captain != vice_captain and captain in xi_players and vice_captain in xi_players),
        "formation": fields.get("Formation"),
        "rows": [
            {"position": position, "players": [p.strip() for p in fields.get(position, "").split(",") if p.strip()]}
            for position in ("FWD", "MID", "DEF", "GK")
        ],
        "bench_gk": fields.get("Bench GK"),
        "bench": [fields.get(f"Bench {i}") for i in range(1, 4)],
        "captain_authority": fields.get("C/VC decision authority"),
        "source": "CANONICAL_S06_TEXT",
    }


def consume_native_content(
    manifest: Mapping[str, Any],
    files: Mapping[str, str],
    *,
    canonical_body: str,
    user_visible_acceptance: bool,
    transport_status: str,
    remote_readback: str,
    native_host_receipt: Mapping[str, Any] | None = None,
    native_host_verification_key: bytes | None = None,
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
            "native_blocks": _native_blocks(source),
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
        native_host_receipt=native_host_receipt,
        native_host_verification_key=native_host_verification_key,
    )
    return {
        "section_count": len(rendered_ids),
        "rendered_section_ids": rendered_ids,
        "components": components,
        "pitch": next((item for item in components if item["section_id"] == "S06"), None),
        "native_pitch": _native_pitch(sources["S06"], sources.get("S08")) if "S06" in sources and valid else None,
        "consumed_chunk_paths": [str(e["path"]) for e in manifest.get("chunks") or []] if valid else [],
        "native_component_count": len(components),
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
