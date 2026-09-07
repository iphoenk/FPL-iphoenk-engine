from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .http_client import utc_now

ROOT = Path(__file__).resolve().parents[2]
VENUE_CONFIG = ROOT / "config" / "v6" / "venue_geography.json"
NORMALIZATION_VERSION = "V6_NOAUTH_SOURCE_NATIVE_1"


def _request(payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    value = ((payload.get("data") or {}).get(request_id) or {})
    return dict(value) if isinstance(value, dict) else {}


def _snapshot_ids(payload: dict[str, Any]) -> list[str]:
    out: set[str] = set()
    for row in (payload.get("data") or {}).values():
        if not isinstance(row, dict):
            continue
        digest = row.get("sha256")
        if isinstance(digest, str) and digest:
            out.add(digest)
    return sorted(out)


def _dataset(
    *,
    source_id: str,
    payload: dict[str, Any],
    semantic_class: str,
    authority: str,
    record_groups: dict[str, list[dict[str, Any]]],
    model_author: str | None = None,
    authority_ceiling: str | None = None,
    record_semantics: dict[str, str] | None = None,
) -> dict[str, Any]:
    record_count = sum(len(rows) for rows in record_groups.values())
    out: dict[str, Any] = {
        "schema_version": 1,
        "normalization_version": NORMALIZATION_VERSION,
        "source_id": source_id,
        "generated_at": utc_now(),
        "effective_at": payload.get("checked_at"),
        "canonical": True,
        "semantic_class": semantic_class,
        "authority": authority,
        "source_snapshot_ids": _snapshot_ids(payload),
        "source_health": payload.get("health"),
        "source_effective_state": payload.get("effective_state"),
        "current_run_action": payload.get("current_run_action"),
        "normalization_status": "NORMALIZED" if record_count else "EMPTY_OR_SCHEMA_UNAVAILABLE",
        "record_count": record_count,
        "record_groups": record_groups,
        "governance": {
            "data_only": True,
            "source_native_records_preserved": True,
            "cross_source_synthesis": False,
            "silent_fuzzy_identity_join": False,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "may_override_official_fpl": False,
            "no_auth_public_source": True,
            "private_secret_required": False,
        },
    }
    if authority_ceiling:
        out["authority_ceiling"] = authority_ceiling
    if record_semantics:
        out["record_semantics"] = dict(record_semantics)
    if semantic_class == "UPSTREAM_MODEL_SIGNAL":
        out["model_author"] = model_author or authority
        out["v6_computation"] = "NONE"
        out["v6_transformation"] = "SOURCE_SPECIFIC_NORMALIZATION"
    return out


def _reep(payload: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    manifest = _request(payload, "latest_manifest").get("json")
    release_rows: list[dict[str, Any]] = []
    if isinstance(manifest, dict) and manifest:
        release_rows.append(
            {
                "manifest": manifest,
                "identity_role": "SECONDARY_DETERMINISTIC_IDENTITY_EVIDENCE",
                "keyed_api_used": False,
                "bulk_asset_downloaded": False,
            }
        )
    contract_body = _request(payload, "downloads_contract").get("body")
    contract_rows = []
    if isinstance(contract_body, str) and contract_body.strip():
        contract_rows.append(
            {
                "public_download_surface_available": True,
                "keyed_api_used": False,
                "bulk_asset_downloaded": False,
            }
        )
    return _dataset(
        source_id="reep_register",
        payload=payload,
        semantic_class="NORMALIZED_FACT",
        authority="REEP_REGISTER",
        authority_ceiling="IDENTITY_CORROBORATION_ONLY",
        record_groups={"release": release_rows, "access_contract": contract_rows},
        record_semantics={
            "release": "PUBLIC_RELEASE_METADATA_ONLY",
            "access_contract": "PUBLIC_NO_AUTH_ACCESS_CONTRACT",
        },
    )


def _binding_value(binding: dict[str, Any], key: str) -> Any:
    value = binding.get(key)
    if not isinstance(value, dict):
        return None
    return value.get("value")


def _wikidata(payload: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    raw = _request(payload, "premier_league_clubs").get("json")
    bindings = (((raw or {}).get("results") or {}).get("bindings") or []) if isinstance(raw, dict) else []
    teams: list[dict[str, Any]] = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        uri = _binding_value(binding, "club")
        qid = str(uri).rsplit("/", 1)[-1] if isinstance(uri, str) and uri else None
        teams.append(
            {
                "source_native_id": qid,
                "source_uri": uri,
                "label": _binding_value(binding, "clubLabel"),
                "official_website": _binding_value(binding, "website"),
                "official_team_id": None,
                "identity_status": "UNMAPPED",
            }
        )
    return _dataset(
        source_id="wikidata",
        payload=payload,
        semantic_class="NORMALIZED_FACT",
        authority="WIKIDATA",
        authority_ceiling="CORROBORATION_ONLY",
        record_groups={"teams": teams},
        record_semantics={"teams": "SECONDARY_IDENTITY_CORROBORATION"},
    )


def _venues() -> list[dict[str, Any]]:
    try:
        payload = json.loads(VENUE_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("venues") if isinstance(payload, dict) else []
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _open_meteo(payload: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    raw = _request(payload, "premier_league_venues").get("json")
    provider_rows = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) and raw else []
    venue_rows = _venues()
    weather: list[dict[str, Any]] = []
    for index, provider in enumerate(provider_rows):
        if not isinstance(provider, dict):
            continue
        venue = venue_rows[index] if index < len(venue_rows) else {}
        weather.append(
            {
                "source_native_id": index,
                "venue_index": index,
                "club": venue.get("club"),
                "venue": venue.get("venue"),
                "configured_latitude": venue.get("latitude"),
                "configured_longitude": venue.get("longitude"),
                "provider_latitude": provider.get("latitude"),
                "provider_longitude": provider.get("longitude"),
                "elevation": provider.get("elevation"),
                "timezone": provider.get("timezone"),
                "timezone_abbreviation": provider.get("timezone_abbreviation"),
                "utc_offset_seconds": provider.get("utc_offset_seconds"),
                "hourly_units": provider.get("hourly_units"),
                "hourly": provider.get("hourly"),
                "official_fixture_id": None,
                "identity_status": "UNMAPPED",
            }
        )
    dataset = _dataset(
        source_id="open_meteo",
        payload=payload,
        semantic_class="UPSTREAM_MODEL_SIGNAL",
        authority="OPEN_METEO",
        model_author="OPEN_METEO",
        authority_ceiling="CONTEXT_ONLY",
        record_groups={"venue_forecasts": weather},
        record_semantics={"venue_forecasts": "RAW_PROVIDER_WEATHER_FORECAST"},
    )
    dataset["governance"].update(
        {
            "weather_fpl_interpretation": "DOWNSTREAM_ONLY",
            "direct_xpts_multiplier": False,
            "transfer_trigger_authority": False,
            "venue_index_mapping": "CONFIGURED_DETERMINISTIC_ORDER",
        }
    )
    return dataset


def _sportsdb_event(row: dict[str, Any], request_role: str) -> dict[str, Any]:
    return {
        "source_native_id": row.get("idEvent"),
        "source_native_league_id": row.get("idLeague"),
        "event_name": row.get("strEvent"),
        "league_name": row.get("strLeague"),
        "season": row.get("strSeason"),
        "round": row.get("intRound"),
        "timestamp": row.get("strTimestamp"),
        "date_event": row.get("dateEvent"),
        "time_event": row.get("strTime"),
        "home": {"source_native_id": row.get("idHomeTeam"), "name": row.get("strHomeTeam")},
        "away": {"source_native_id": row.get("idAwayTeam"), "name": row.get("strAwayTeam")},
        "home_score": row.get("intHomeScore"),
        "away_score": row.get("intAwayScore"),
        "status": row.get("strStatus"),
        "request_role": request_role,
        "official_fixture_id": None,
        "identity_status": "UNMAPPED",
    }


def _thesportsdb(payload: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    league_raw = _request(payload, "league").get("json")
    leagues = league_raw.get("leagues") if isinstance(league_raw, dict) else []
    league_rows: list[dict[str, Any]] = []
    if isinstance(leagues, list):
        for row in leagues:
            if isinstance(row, dict):
                league_rows.append(
                    {
                        "source_native_id": row.get("idLeague"),
                        "name": row.get("strLeague"),
                        "alternate_name": row.get("strLeagueAlternate"),
                        "sport": row.get("strSport"),
                        "country": row.get("strCountry"),
                    }
                )

    events: list[dict[str, Any]] = []
    for request_id, role in (("next_event", "UPCOMING"), ("past_event", "PAST")):
        raw = _request(payload, request_id).get("json")
        rows = raw.get("events") if isinstance(raw, dict) else []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                events.append(_sportsdb_event(row, role))

    return _dataset(
        source_id="thesportsdb_v1",
        payload=payload,
        semantic_class="NORMALIZED_FACT",
        authority="THESPORTSDB",
        authority_ceiling="SECONDARY",
        record_groups={"competition": league_rows, "events": events},
        record_semantics={
            "competition": "SECONDARY_PROVIDER_METADATA",
            "events": "SECONDARY_FIXTURE_EVENT_METADATA_REQUIRES_OFFICIAL_CROSSCHECK",
        },
    )


Parser = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def build_noauth_source_native_datasets(
    results: dict[str, dict[str, Any]], identity_map: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    parsers: dict[str, Parser] = {
        "reep_register": _reep,
        "wikidata": _wikidata,
        "open_meteo": _open_meteo,
        "thesportsdb_v1": _thesportsdb,
    }
    datasets: dict[str, dict[str, Any]] = {}
    for source_id, parser in parsers.items():
        payload = results.get(source_id)
        if not isinstance(payload, dict):
            continue
        datasets[source_id] = parser(payload, identity_map)
    return datasets
