from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any


PUBLIC_SOURCE = "bootstrap-static.elements"
REQUIRED_FACT_FIELDS = (
    "element_id",
    "team",
    "position",
    "now_cost",
    "ownership",
    "status",
)
REQUIRED_PROVENANCE_FIELDS = (
    "source",
    "source_snapshot_id",
    "fetched_at",
    "observed_at",
    "freshness",
)
EXPECTED_WATCHLIST_COUNTS = {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}


class DataJoinDefect(RuntimeError):
    """A resolved element cannot be hydrated from the canonical Official snapshot."""


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def official_snapshot_metadata(bootstrap: dict, bootstrap_health: dict | None = None) -> dict:
    """Describe the one bootstrap representation used by the current V4 run."""
    health = bootstrap_health or {}
    fetched_at = health.get("fetched_at")
    transport_live = str(health.get("status") or "").upper() == "LIVE"
    return {
        "source": PUBLIC_SOURCE,
        "source_snapshot_id": _canonical_hash(bootstrap),
        "fetched_at": fetched_at,
        "observed_at": fetched_at,
        "freshness": "FRESH" if transport_live and fetched_at else "UNAVAILABLE",
        "transport_status": health.get("status"),
        "response_cache_age_seconds": health.get("response_cache_age_seconds"),
    }


def build_public_fact(
    player: dict,
    teams: dict,
    positions: dict,
    snapshot: dict,
) -> dict:
    """Hydrate one canonical public FACT row directly from bootstrap-static."""
    element_id = player.get("id")
    team_id = player.get("team")
    element_type = player.get("element_type")
    now_cost = player.get("now_cost")
    return {
        "element": element_id,
        "element_id": element_id,
        "name": player.get("web_name"),
        "team": teams.get(team_id),
        "club": teams.get(team_id),
        "team_id": team_id,
        "position": positions.get(element_type),
        "now_cost": now_cost,
        "price": round(float(now_cost) / 10.0, 1) if now_cost is not None else None,
        "ownership": player.get("selected_by_percent"),
        "status": player.get("status"),
        "source": snapshot.get("source"),
        "source_snapshot_id": snapshot.get("source_snapshot_id"),
        "fetched_at": snapshot.get("fetched_at"),
        "observed_at": snapshot.get("observed_at"),
        "freshness": snapshot.get("freshness"),
    }


def fact_defects(row: dict, expected_element: int | None = None) -> list[dict]:
    element_id = row.get("element_id")
    defects: list[dict] = []
    if expected_element is not None:
        try:
            actual = int(element_id) if element_id is not None else None
        except (TypeError, ValueError):
            actual = None
        if actual != int(expected_element):
            defects.append(
                {
                    "classification": "DATA_JOIN_DEFECT",
                    "element_id": expected_element,
                    "missing_fields": ["element_id"] if actual is None else [],
                    "detail": f"canonical element_id mismatch: expected={expected_element} actual={actual}",
                }
            )
    missing = [
        field
        for field in (*REQUIRED_FACT_FIELDS, *REQUIRED_PROVENANCE_FIELDS)
        if row.get(field) is None or row.get(field) == ""
    ]
    if missing:
        defects.append(
            {
                "classification": "DATA_JOIN_DEFECT",
                "element_id": expected_element if expected_element is not None else element_id,
                "missing_fields": missing,
                "detail": "resolved element missing required fresh Official FACT/provenance",
            }
        )
    if row.get("freshness") != "FRESH":
        defects.append(
            {
                "classification": "DATA_JOIN_DEFECT",
                "element_id": expected_element if expected_element is not None else element_id,
                "missing_fields": [],
                "detail": f"Official FACT freshness is {row.get('freshness') or 'ABSENT'}",
            }
        )
    return defects


def extract_public_fact(row: dict, expected_element: int | None = None) -> dict:
    """Return the canonical FACT projection or fail as DATA_JOIN_DEFECT."""
    defects = fact_defects(row, expected_element=expected_element)
    if defects:
        first = defects[0]
        raise DataJoinDefect(
            "DATA_JOIN_DEFECT: "
            f"element_id={first.get('element_id')} "
            f"missing={first.get('missing_fields')} detail={first.get('detail')}"
        )
    element_id = int(row["element_id"])
    return {
        "element": element_id,
        "element_id": element_id,
        "name": row.get("name"),
        "team": row.get("team"),
        "club": row.get("club") or row.get("team"),
        "team_id": row.get("team_id"),
        "position": row.get("position"),
        "now_cost": row.get("now_cost"),
        "price": row.get("price") if row.get("price") is not None else round(float(row["now_cost"]) / 10.0, 1),
        "ownership": row.get("ownership"),
        "status": row.get("status"),
        "source": row.get("source"),
        "source_snapshot_id": row.get("source_snapshot_id"),
        "fetched_at": row.get("fetched_at"),
        "observed_at": row.get("observed_at"),
        "freshness": row.get("freshness"),
    }


def _endpoint_state(endpoint_health: dict, names: tuple[str, ...]) -> str:
    statuses = [str((endpoint_health.get(name) or {}).get("status") or "UNAVAILABLE").upper() for name in names]
    live = sum(status == "LIVE" for status in statuses)
    failed = sum(status == "FAILED" for status in statuses)
    if live and not failed:
        return "PASS"
    if live:
        return "PARTIAL"
    if failed:
        return "FAIL"
    return "UNAVAILABLE"


def _fact_group(rows: list[dict], expected: int) -> tuple[dict, list[dict]]:
    defects: list[dict] = []
    resolved_ids: list[int] = []
    complete = 0
    for row in rows:
        raw_element = row.get("element_id")
        try:
            element_id = int(raw_element) if raw_element is not None else -1
        except (TypeError, ValueError):
            element_id = -1
        row_defects = fact_defects(row, expected_element=element_id if element_id > 0 else None)
        defects.extend(row_defects)
        if element_id > 0:
            resolved_ids.append(element_id)
        if not row_defects:
            complete += 1
    return {
        "expected": expected,
        "resolved": len(set(resolved_ids)),
        "official_fact_complete": complete,
        "status": "PASS" if len(rows) == expected and len(set(resolved_ids)) == expected and complete == expected else "FAIL",
    }, defects


def build_publication_integrity(
    tactical: dict,
    latest: dict,
    prices: dict,
    decision: dict,
    *,
    framework_health: dict | None = None,
    weather: dict | None = None,
) -> dict:
    """Evaluate complete USER_REPORT eligibility without changing decision authority."""
    framework_health = framework_health or {}
    weather = weather or {}
    endpoint_health = latest.get("endpoint_health") or {}
    owned = list(tactical.get("owned") or [])
    watchlist = list(tactical.get("watchlist") or [])

    owned_counts, owned_defects = _fact_group(owned, 15)
    watch_counts, watch_defects = _fact_group(watchlist, 20)
    defects = [*owned_defects, *watch_defects]

    owned_ids = {int(row.get("element_id") or 0) for row in owned if row.get("element_id") is not None}
    watch_ids = {int(row.get("element_id") or 0) for row in watchlist if row.get("element_id") is not None}
    overlap = sorted(element for element in owned_ids & watch_ids if element > 0)
    position_counts = Counter(str(row.get("position") or "") for row in watchlist)
    positional_exact = all(position_counts.get(position, 0) == expected for position, expected in EXPECTED_WATCHLIST_COUNTS.items())
    if overlap:
        defects.append(
            {
                "classification": "PUBLICATION_CONTRACT_DEFECT",
                "element_id": None,
                "missing_fields": [],
                "detail": f"owned/watchlist overlap: {overlap}",
            }
        )
    if not positional_exact:
        defects.append(
            {
                "classification": "PUBLICATION_CONTRACT_DEFECT",
                "element_id": None,
                "missing_fields": [],
                "detail": f"watchlist positional cardinality={dict(position_counts)}",
            }
        )

    snapshot_ids = {
        str(row.get("source_snapshot_id"))
        for row in [*owned, *watchlist]
        if row.get("source_snapshot_id")
    }
    mixed_snapshots = len(snapshot_ids) != 1
    if mixed_snapshots:
        defects.append(
            {
                "classification": "DATA_JOIN_DEFECT",
                "element_id": None,
                "missing_fields": [],
                "detail": f"incompatible Official snapshots={sorted(snapshot_ids)}",
            }
        )

    public_pull_state = "PASS" if str((endpoint_health.get("bootstrap") or {}).get("status") or "").upper() == "LIVE" else "FAIL"
    resolver_pass = len(owned_ids) == 15 and len(watch_ids) == 20 and not overlap
    hydration_pass = not owned_defects and not watch_defects and not mixed_snapshots
    factual_gate_pass = (
        public_pull_state == "PASS"
        and owned_counts["status"] == "PASS"
        and watch_counts["status"] == "PASS"
        and positional_exact
        and not overlap
        and hydration_pass
    )

    predictor_status = str((prices.get("health") or {}).get("status") or "UNAVAILABLE").upper()
    predictor_state = predictor_status if predictor_status in {"PASS", "PARTIAL", "STALE", "FAIL"} else "UNAVAILABLE"
    weather_status = str((weather.get("health") or {}).get("status") or weather.get("status") or "UNAVAILABLE").upper()
    validation_status = str(framework_health.get("overall") or framework_health.get("pipeline_health") or "UNAVAILABLE").upper()

    publication_state = "PASS" if factual_gate_pass else "BLOCKED"
    return {
        "schema_version": 1,
        "contract": "V4_OFFICIAL_FACT_PUBLICATION_INTEGRITY_V1",
        "status": publication_state,
        "factual_gate_pass": factual_gate_pass,
        "owned": owned_counts,
        "watchlist": {
            **watch_counts,
            "position_counts": {position: position_counts.get(position, 0) for position in EXPECTED_WATCHLIST_COUNTS},
            "position_cardinality_exact": positional_exact,
            "owned_overlap": overlap,
        },
        "official_snapshot": {
            "source_snapshot_ids": sorted(snapshot_ids),
            "single_coherent_snapshot": not mixed_snapshots,
        },
        "defects": defects,
        "capabilities": {
            "official_public_pull": public_pull_state,
            "personal_auth_pull": _endpoint_state(endpoint_health, ("entry", "history", "transfers", "picks")),
            "element_id_resolver": "PASS" if resolver_pass else "FAIL",
            "official_fact_hydration": "PASS" if hydration_pass else "FAIL",
            "owned_fact_completeness": owned_counts["status"],
            "watchlist_fact_completeness": watch_counts["status"],
            "market_predictor_freshness": predictor_state,
            "football_context": "PASS" if latest.get("official_context") else "UNAVAILABLE",
            "weather_context": weather_status,
            "prediction": "PASS" if (latest.get("prediction_summary") or {}).get("players") else "UNAVAILABLE",
            "decision": "PASS" if decision.get("resolution_id") else "FAIL",
            "governance": "PASS" if decision.get("resolution_id") else "FAIL",
            "validation": validation_status,
            "publication_integrity": publication_state,
            "reporting": "PASS" if factual_gate_pass else "BLOCKED",
            "serving": "PASS" if factual_gate_pass else "BLOCKED",
            "overall": "PASS" if factual_gate_pass else "BLOCKED",
        },
        "authority_separation": {
            "public_official_fact_independent_of_personal_auth": True,
            "personal_auth_failure_does_not_erase_public_fact": True,
            "execution_authorized_semantics_unchanged": True,
            "price_predictor_is_model_evidence": True,
        },
    }
