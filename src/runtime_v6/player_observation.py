from __future__ import annotations

import re
from copy import deepcopy
from html.parser import HTMLParser
from typing import Any

from .http_client import utc_now

NORMALIZATION_VERSION = "V6_PLAYER_OBSERVATION_1"
_STATMUSE_PLAYER_RE = re.compile(r"/fc/player/[^\"'?#/]*-(\d+)(?:[/?#]|$)", re.IGNORECASE)


def _request(payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    value = ((payload.get("data") or {}).get(request_id) or {})
    return dict(value) if isinstance(value, dict) else {}


def _int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _reverse_player_links(identity_map: dict[str, Any], source_id: str) -> dict[str, tuple[int, str]]:
    reverse: dict[str, tuple[int, str]] = {}
    conflicts: set[str] = set()
    for element_key, mapping in (identity_map.get("mappings") or {}).items():
        if not isinstance(mapping, dict):
            continue
        link = ((mapping.get("links") or {}).get(source_id) or {})
        if not isinstance(link, dict) or link.get("joinable") is not True:
            continue
        native = link.get("source_native_id")
        if native is None:
            continue
        key = str(native)
        element_id = _int(mapping.get("official_fpl_element_id") or element_key)
        if element_id is None:
            continue
        if key in reverse and reverse[key][0] != element_id:
            conflicts.add(key)
            continue
        reverse[key] = (element_id, str(link.get("status") or "UNMAPPED"))
    for key in conflicts:
        reverse.pop(key, None)
    return reverse


def _identity_fields(reverse: dict[str, tuple[int, str]], native_id: Any) -> dict[str, Any]:
    if native_id is None:
        return {"official_element_id": None, "identity_status": "UNMAPPED", "join_ready": False}
    resolved = reverse.get(str(native_id))
    if resolved is None:
        return {"official_element_id": None, "identity_status": "UNMAPPED", "join_ready": False}
    return {
        "official_element_id": resolved[0],
        "identity_status": resolved[1],
        "join_ready": resolved[1] in {"EXACT", "VERIFIED_MANUAL"},
    }


def _snapshot_ids(payload: dict[str, Any]) -> list[str]:
    ids: set[str] = set()
    for row in (payload.get("data") or {}).values():
        if isinstance(row, dict) and isinstance(row.get("sha256"), str) and row.get("sha256"):
            ids.add(str(row["sha256"]))
    return sorted(ids)


def _dataset(source_id: str, payload: dict[str, Any], players: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "normalization_version": NORMALIZATION_VERSION,
        "source_id": source_id,
        "generated_at": utc_now(),
        "effective_at": payload.get("checked_at"),
        "canonical": True,
        "semantic_class": "NORMALIZED_FACT",
        "authority": source_id.upper(),
        "source_snapshot_ids": _snapshot_ids(payload),
        "source_health": payload.get("health"),
        "source_effective_state": payload.get("effective_state"),
        "current_run_action": payload.get("current_run_action"),
        "normalization_status": "NORMALIZED" if players else "EMPTY_OR_SCHEMA_UNAVAILABLE",
        "record_count": len(players),
        "record_groups": {"players": players},
        "governance": {
            "data_only": True,
            "source_native_records_preserved": True,
            "cross_source_synthesis": False,
            "silent_fuzzy_identity_join": False,
            "identity_join_requires_verified_provider_native_id": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "may_override_official_fpl": False,
        },
    }


def _walk_fotmob_stats(value: Any, out: dict[int, dict[str, Any]]) -> None:
    if isinstance(value, dict):
        native_id = _int(value.get("id"))
        name = value.get("name") or value.get("playerName")
        team_id = _int(value.get("teamId"))
        has_player_shape = native_id is not None and isinstance(name, str) and bool(name.strip()) and (
            team_id is not None
            or "value" in value
            or "statValue" in value
            or "minutesPlayed" in value
        )
        if has_player_shape:
            row = out.setdefault(native_id, {"source_native_id": native_id, "player_name": name})
            if team_id is not None:
                row["source_team_id"] = team_id
            for key in ("value", "statValue", "minutesPlayed", "teamName"):
                if key in value and value.get(key) is not None:
                    row[key] = value.get(key)
        for child in value.values():
            _walk_fotmob_stats(child, out)
    elif isinstance(value, list):
        for child in value:
            _walk_fotmob_stats(child, out)


def _fotmob_players(payload: dict[str, Any], identity_map: dict[str, Any]) -> list[dict[str, Any]]:
    raw = _request(payload, "league").get("json")
    raw = raw if isinstance(raw, dict) else {}
    stats = raw.get("stats")
    observed: dict[int, dict[str, Any]] = {}
    if stats is not None:
        _walk_fotmob_stats(stats, observed)
    reverse = _reverse_player_links(identity_map, "fotmob")
    players: list[dict[str, Any]] = []
    for native_id in sorted(observed):
        row = dict(observed[native_id])
        row.update(_identity_fields(reverse, native_id))
        players.append(row)
    return players


class _StatMuseTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self._in_row = False
        self._in_cell = False
        self._cell_kind: str | None = None
        self._cell_parts: list[str] = []
        self._cells: list[str] = []
        self._native_ids: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower == "tr":
            self._in_row = True
            self._cells = []
            self._native_ids = []
        elif self._in_row and lower in {"td", "th"}:
            self._in_cell = True
            self._cell_kind = lower
            self._cell_parts = []
        elif self._in_row and lower == "a":
            href = next((value for key, value in attrs if key.lower() == "href"), None)
            if isinstance(href, str):
                match = _STATMUSE_PLAYER_RE.search(href)
                if match:
                    native_id = _int(match.group(1))
                    if native_id is not None:
                        self._native_ids.append(native_id)

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if self._in_cell and lower == self._cell_kind:
            text = " ".join("".join(self._cell_parts).split())
            self._cells.append(text)
            self._in_cell = False
            self._cell_kind = None
            self._cell_parts = []
        elif lower == "tr" and self._in_row:
            self.rows.append({"cells": list(self._cells), "native_ids": list(dict.fromkeys(self._native_ids))})
            self._in_row = False
            self._cells = []
            self._native_ids = []


def _statmuse_players(payload: dict[str, Any], identity_map: dict[str, Any]) -> list[dict[str, Any]]:
    body = _request(payload, "player_xg").get("body")
    if not isinstance(body, str) or not body.strip():
        return []
    parser = _StatMuseTableParser()
    parser.feed(body)

    headers: list[str] | None = None
    reverse = _reverse_player_links(identity_map, "statmuse")
    players: dict[int, dict[str, Any]] = {}
    for parsed in parser.rows:
        cells = [str(cell).strip() for cell in parsed.get("cells") or []]
        upper = [cell.upper() for cell in cells]
        if "NAME" in upper and "XG" in upper:
            headers = cells
            continue
        native_ids = parsed.get("native_ids") or []
        if not headers or len(native_ids) != 1 or not cells:
            continue
        native_id = _int(native_ids[0])
        if native_id is None:
            continue
        values = cells[-len(headers):] if len(cells) >= len(headers) else cells
        if len(values) != len(headers):
            continue
        mapped = {headers[index].strip().upper(): values[index] for index in range(len(headers))}
        name = mapped.get("NAME")
        if not name:
            continue
        row = {
            "source_native_id": native_id,
            "player_name": name,
            "club": mapped.get("CLUB"),
            "season": mapped.get("SEASON"),
            "xg": _float(mapped.get("XG")),
            "xa": _float(mapped.get("XA")),
            "minutes": _int(mapped.get("MIN")),
            "starts": _int(mapped.get("START")),
            "goals": _int(mapped.get("G")),
            "assists": _int(mapped.get("A")),
            "shots": _int(mapped.get("SH")),
            "shots_on_target": _int(mapped.get("SOT")),
            "touches": _int(mapped.get("TCH")),
            "touches_box": _int(mapped.get("TCH-BOX")),
            **_identity_fields(reverse, native_id),
        }
        players[native_id] = row
    return [players[key] for key in sorted(players)]


def _merge_player_group(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    groups = out.setdefault("record_groups", {})
    existing = groups.get("players") if isinstance(groups.get("players"), list) else []
    observed = ((overlay.get("record_groups") or {}).get("players") or [])
    by_native: dict[str, dict[str, Any]] = {}
    for row in [*existing, *observed]:
        if not isinstance(row, dict) or row.get("source_native_id") is None:
            continue
        by_native[str(row["source_native_id"])] = dict(row)
    groups["players"] = list(by_native.values())
    out["record_count"] = sum(len(rows) for rows in groups.values() if isinstance(rows, list))
    if groups["players"]:
        out["normalization_status"] = "NORMALIZED"
    governance = out.setdefault("governance", {})
    governance["player_observation_normalization_version"] = NORMALIZATION_VERSION
    governance["player_identity_is_provider_native_only"] = True
    return out


def augment_source_native_datasets(
    results: dict[str, dict[str, Any]],
    identity_map: dict[str, Any],
    datasets: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out = dict(datasets)
    for source_id, parser in (("fotmob", _fotmob_players), ("statmuse", _statmuse_players)):
        payload = results.get(source_id)
        if not isinstance(payload, dict):
            continue
        overlay = _dataset(source_id, payload, parser(payload, identity_map))
        if source_id in out:
            out[source_id] = _merge_player_group(out[source_id], overlay)
        else:
            out[source_id] = overlay
    return out
