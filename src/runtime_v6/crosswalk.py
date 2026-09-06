from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIG = Path(__file__).resolve().parents[2] / "config" / "v6" / "verified_crosswalks.json"
JOINABLE = {"EXACT", "VERIFIED_MANUAL"}


class CrosswalkError(RuntimeError):
    pass


def _utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _same_instant(left: Any, right: Any) -> bool:
    a, b = _utc(left), _utc(right)
    return a is not None and b is not None and a == b


def load_verified_crosswalks(path: Path = CONFIG) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CrosswalkError("verified crosswalk config unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise CrosswalkError("verified crosswalk schema mismatch")
    if payload.get("canonical_authority") != "official_fpl":
        raise CrosswalkError("verified crosswalk canonical authority must be official_fpl")
    if payload.get("fuzzy_matching_allowed") is not False:
        raise CrosswalkError("verified crosswalk must forbid fuzzy matching")

    for source_id, source in (payload.get("sources") or {}).items():
        if not isinstance(source, dict):
            raise CrosswalkError(f"invalid crosswalk source: {source_id}")
        native_seen: set[str] = set()
        canonical_seen: set[int] = set()
        for row in source.get("teams") or []:
            if not isinstance(row, dict):
                raise CrosswalkError(f"invalid team crosswalk row: {source_id}")
            native = str(row.get("source_native_id"))
            try:
                canonical = int(row.get("official_fpl_team_id"))
            except (TypeError, ValueError) as exc:
                raise CrosswalkError(f"invalid canonical team id: {source_id}") from exc
            if native in native_seen:
                raise CrosswalkError(f"duplicate native team id: {source_id}:{native}")
            if canonical in canonical_seen:
                raise CrosswalkError(f"duplicate canonical team id: {source_id}:{canonical}")
            if canonical <= 0:
                raise CrosswalkError(f"non-positive canonical team id: {source_id}:{canonical}")
            native_seen.add(native)
            canonical_seen.add(canonical)
    return payload


def _team_config_map(config: dict[str, Any], source_id: str) -> dict[str, int]:
    source = ((config.get("sources") or {}).get(source_id) or {})
    out: dict[str, int] = {}
    for row in source.get("teams") or []:
        out[str(row["source_native_id"])] = int(row["official_fpl_team_id"])
    return out


def _identity_health(mapped: int, canonical: int, deterministic: bool) -> str:
    if not deterministic or canonical <= 0 or mapped <= 0:
        return "RED"
    if mapped == canonical:
        return "GREEN"
    return "AMBER"


def _link(source_id: str, native_id: Any, *, method: str, status: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_native_id": native_id,
        "external_id": native_id,
        "mapping_method": method,
        "method": method,
        "verification_status": status,
        "status": status,
        "confidence": 1.0,
        "verified": True,
        "joinable": True,
        "provenance": {"source_id": source_id, "crosswalk": "config/v6/verified_crosswalks.json"},
    }


def _annotate_existing_player_links(
    identity: dict[str, Any],
    datasets: dict[str, dict[str, Any]],
) -> None:
    by_source_native: dict[str, dict[str, tuple[int, str]]] = {}
    for element_id, row in (identity.get("mappings") or {}).items():
        try:
            canonical = int(element_id)
        except (TypeError, ValueError):
            continue
        for source_id, link in (row.get("links") or {}).items():
            status = str(link.get("verification_status") or link.get("status") or "")
            if status not in JOINABLE:
                continue
            native = link.get("source_native_id", link.get("external_id"))
            if native is None:
                continue
            by_source_native.setdefault(source_id, {})[str(native)] = (canonical, status)

    for source_id, dataset in datasets.items():
        lookup = by_source_native.get(source_id) or {}
        for record in dataset.get("players") or []:
            if not isinstance(record, dict) or record.get("source_native_id") is None:
                continue
            match = lookup.get(str(record["source_native_id"]))
            if not match:
                continue
            canonical, status = match
            record["official_fpl_element_id"] = canonical
            record["canonical_player_id"] = f"fpl:{canonical}"
            record["identity_status"] = status


def _apply_verified_team_crosswalks(
    identity: dict[str, Any],
    datasets: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    team_bridge = dict(((identity.get("entity_bridges") or {}).get("team")) or {})
    mappings = dict(team_bridge.get("mappings") or {})
    coverage = dict(team_bridge.get("coverage") or {})
    canonical_count = int(team_bridge.get("canonical_team_count") or len(mappings))
    report: dict[str, Any] = {}

    for source_id in (config.get("sources") or {}):
        crosswalk = _team_config_map(config, source_id)
        dataset = datasets.get(source_id) or {}
        observed = {
            str(row.get("source_native_id"))
            for row in dataset.get("teams") or []
            if isinstance(row, dict) and row.get("source_native_id") is not None
        }
        mapped = 0
        for record in dataset.get("teams") or []:
            if not isinstance(record, dict) or record.get("source_native_id") is None:
                continue
            official_id = crosswalk.get(str(record["source_native_id"]))
            if official_id is None or str(official_id) not in mappings:
                continue
            record["official_fpl_team_id"] = official_id
            record["canonical_team_id"] = f"fpl-team:{official_id}"
            record["identity_status"] = "VERIFIED_MANUAL"
            canonical = mappings[str(official_id)]
            links = dict(canonical.get("links") or {})
            links[source_id] = _link(
                source_id,
                record["source_native_id"],
                method="VERIFIED_MANUAL_CROSSWALK",
                status="VERIFIED_MANUAL",
            )
            canonical["links"] = links
            mappings[str(official_id)] = canonical
            mapped += 1

        deterministic = bool(crosswalk)
        coverage[source_id] = {
            "strategy": "VERIFIED_MANUAL_CROSSWALK" if deterministic else "UNRESOLVED_NO_VERIFIED_DETERMINISTIC_BRIDGE",
            "deterministic_bridge": deterministic,
            "identity_health": _identity_health(mapped, canonical_count, deterministic),
            "mapped_status": "VERIFIED_MANUAL" if mapped else "UNMAPPED",
            "mapped_team_count": mapped,
            "canonical_team_count": canonical_count,
            "coverage_ratio": round(mapped / canonical_count, 6) if canonical_count else 0.0,
            "unmapped_team_count": max(0, canonical_count - mapped),
            "join_allowed": mapped > 0,
            "configured_mapping_count": len(crosswalk),
            "observed_native_team_count": len(observed),
        }
        report[source_id] = dict(coverage[source_id])

    team_bridge["mappings"] = mappings
    team_bridge["coverage"] = coverage
    identity.setdefault("entity_bridges", {})["team"] = team_bridge
    return report


def _apply_vaastav_fixture_bridge(
    identity: dict[str, Any],
    datasets: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_id = "vaastav_fpl"
    dataset = datasets.get(source_id) or {}
    fixture_bridge = dict(((identity.get("entity_bridges") or {}).get("fixture")) or {})
    mappings = dict(fixture_bridge.get("mappings") or {})
    coverage = dict(fixture_bridge.get("coverage") or {})
    canonical_count = int(fixture_bridge.get("canonical_fixture_count") or len(mappings))
    mapped = 0

    for record in dataset.get("fixtures") or []:
        if not isinstance(record, dict) or record.get("source_native_id") is None:
            continue
        native = str(record["source_native_id"])
        official = mappings.get(native)
        if not official:
            continue
        if record.get("home_official_team_id_candidate") != official.get("official_fpl_team_h_id"):
            continue
        if record.get("away_official_team_id_candidate") != official.get("official_fpl_team_a_id"):
            continue
        if not _same_instant(record.get("kickoff_time"), official.get("kickoff_time")):
            continue
        record["official_fpl_fixture_id"] = int(native)
        record["canonical_fixture_id"] = f"fpl-fixture:{native}"
        record["identity_status"] = "EXACT"
        links = dict(official.get("links") or {})
        links[source_id] = _link(
            source_id,
            record["source_native_id"],
            method="FPL_FIXTURE_ID_TEAMS_KICKOFF_EXACT",
            status="EXACT",
        )
        official["links"] = links
        mappings[native] = official
        mapped += 1

    deterministic = bool(dataset.get("fixtures"))
    coverage[source_id] = {
        "strategy": "FPL_FIXTURE_ID_TEAMS_KICKOFF_EXACT",
        "deterministic_bridge": deterministic,
        "identity_health": _identity_health(mapped, canonical_count, deterministic),
        "mapped_status": "EXACT" if mapped else "UNMAPPED",
        "mapped_fixture_count": mapped,
        "canonical_fixture_count": canonical_count,
        "coverage_ratio": round(mapped / canonical_count, 6) if canonical_count else 0.0,
        "unmapped_fixture_count": max(0, canonical_count - mapped),
        "join_allowed": mapped > 0,
        "observed_native_fixture_count": len(dataset.get("fixtures") or []),
    }
    fixture_bridge["mappings"] = mappings
    fixture_bridge["coverage"] = coverage
    identity.setdefault("entity_bridges", {})["fixture"] = fixture_bridge
    return dict(coverage[source_id])


def apply_verified_crosswalks(
    identity_map: dict[str, Any],
    native_datasets: dict[str, dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    config = config or load_verified_crosswalks()
    identity = deepcopy(identity_map)
    datasets = deepcopy(native_datasets)
    _annotate_existing_player_links(identity, datasets)
    team_report = _apply_verified_team_crosswalks(identity, datasets, config)
    fixture_report = _apply_vaastav_fixture_bridge(identity, datasets)

    report = {
        "schema_version": 1,
        "canonical": True,
        "semantic_class": "IDENTITY_CROSSWALK",
        "authority": "V6_DETERMINISTIC_IDENTITY",
        "season": config.get("season"),
        "canonical_authority": "official_fpl",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "normalization_version": "v6-crosswalk-1",
        "fuzzy_matching_allowed": False,
        "team_coverage": team_report,
        "fixture_coverage": {"vaastav_fpl": fixture_report},
        "configured_sources": sorted((config.get("sources") or {}).keys()),
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "silent_name_matching_allowed": False,
            "joinable_statuses": sorted(JOINABLE),
            "unverified_records_remain_unmapped": True,
        },
    }
    return identity, datasets, report
