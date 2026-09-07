from __future__ import annotations

import json
from pathlib import Path

from src.runtime_v6.registry import load_registry

ROOT = Path(__file__).resolve().parents[1]
ADDITIONS = ROOT / "config" / "v6" / "source_additions.json"
ACTIVATION = ROOT / "config" / "v6" / "source_activation.json"
VENUES = ROOT / "config" / "v6" / "venue_geography.json"

DECLARED_NO_AUTH_SOURCES = {"reep_register", "wikidata", "open_meteo", "thesportsdb_v1"}
ACTIVE_NO_AUTH_SOURCES = {"wikidata", "open_meteo", "thesportsdb_v1"}
ACTIVE_CORE = {"wikidata", "open_meteo"}
EXPECTED_2026_27_CLUBS = {
    "AFC Bournemouth",
    "Arsenal",
    "Aston Villa",
    "Brentford",
    "Brighton & Hove Albion",
    "Chelsea",
    "Coventry City",
    "Crystal Palace",
    "Everton",
    "Fulham",
    "Hull City",
    "Ipswich Town",
    "Leeds United",
    "Liverpool",
    "Manchester City",
    "Manchester United",
    "Newcastle United",
    "Nottingham Forest",
    "Sunderland",
    "Tottenham Hotspur",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_declared_source_wave_is_zero_cost_no_account_no_login_no_private_secret() -> None:
    additions = _json(ADDITIONS)
    activation = _json(ACTIVATION)
    by_id = {str(row["id"]): row for row in additions["sources"]}

    assert DECLARED_NO_AUTH_SOURCES.issubset(by_id)
    for source_id in DECLARED_NO_AUTH_SOURCES:
        row = by_id[source_id]
        access = row.get("access") or {}
        assert access.get("cost") == "ZERO"
        assert access.get("account_required") is False
        assert access.get("login_required") is False
        assert access.get("private_api_key_required") is False
        assert access.get("private_token_required") is False
        assert "auth" not in row
        assert row.get("critical") is False

    for source_id in ACTIVE_NO_AUTH_SOURCES:
        assert activation["constraints"][source_id] == "NO_AUTH_PUBLIC_ONLY"

    assert activation["tiers"]["thesportsdb_v1"] == "pilot"
    assert {source_id for source_id in ACTIVE_CORE if activation["tiers"][source_id] == "core"} == ACTIVE_CORE


def test_resolved_registry_preserves_active_no_auth_contract_and_prunes_unstable_reep() -> None:
    registry = load_registry()
    by_id = {str(row["id"]): row for row in registry["sources"]}
    assert ACTIVE_NO_AUTH_SOURCES.issubset(by_id)
    assert "reep_register" not in by_id
    for source_id in ACTIVE_NO_AUTH_SOURCES:
        assert by_id[source_id]["activation_constraint"] == "NO_AUTH_PUBLIC_ONLY"
        assert by_id[source_id].get("auth") is None

    reference_only = (registry.get("activation") or {}).get("reference_only_sources") or {}
    reason = str(reference_only.get("reep_register") or "")
    assert "HTTP_404" in reason
    assert "REENABLE_ONLY_AFTER_STABLE_PUBLIC_DOWNLOAD_REVALIDATION" in reason


def test_reep_declaration_uses_download_surface_not_keyed_api() -> None:
    additions = _json(ADDITIONS)
    reep = next(row for row in additions["sources"] if row["id"] == "reep_register")
    urls = [str(request["url"]) for request in reep["requests"]]
    assert any("data.reep.football" in url for url in urls)
    assert any("reep.football/downloads" in url for url in urls)
    assert all("/api/v1" not in url for url in urls)


def test_thesportsdb_only_uses_documented_public_v1_access_segment() -> None:
    additions = _json(ADDITIONS)
    source = next(row for row in additions["sources"] if row["id"] == "thesportsdb_v1")
    access = source["access"]
    assert access["shared_public_key"] is True
    assert access["public_shared_access_segment"] == "123"
    assert all("/api/v1/json/123/" in str(request["url"]) for request in source["requests"])


def test_venue_geography_matches_current_2026_27_pl_membership_and_open_meteo_order() -> None:
    venue_payload = _json(VENUES)
    venues = venue_payload["venues"]
    assert venue_payload["season"] == "2026-2027"
    assert len(venues) == 20
    assert {row["club"] for row in venues} == EXPECTED_2026_27_CLUBS
    assert len({row["club"] for row in venues}) == 20
    assert all(-90 <= float(row["latitude"]) <= 90 for row in venues)
    assert all(-180 <= float(row["longitude"]) <= 180 for row in venues)

    additions = _json(ADDITIONS)
    open_meteo = next(row for row in additions["sources"] if row["id"] == "open_meteo")
    params = open_meteo["requests"][0]["params"]
    latitudes = [float(value) for value in params["latitude"].split(",")]
    longitudes = [float(value) for value in params["longitude"].split(",")]
    assert latitudes == [float(row["latitude"]) for row in venues]
    assert longitudes == [float(row["longitude"]) for row in venues]


def test_weather_source_remains_raw_data_only() -> None:
    additions = _json(ADDITIONS)
    source = next(row for row in additions["sources"] if row["id"] == "open_meteo")
    notes = source["notes"].lower()
    assert "computes no fpl impact" in notes
    assert "xpts" in notes
    assert source["category"] == "fixture_weather_context"
