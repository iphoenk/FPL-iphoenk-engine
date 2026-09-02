from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from typing import Any

from src.intelligence.understat_tactical import build_understat_tactical
from src.sources import understat
from src.utils import DATA, atomic_json, iso_now, read_json

OUT = DATA / "understat_tactical_v3.json"
HEALTH_OUT = DATA / "understat_tactical_health_v3.json"
RAW_CACHE = DATA / "stats" / "understat_epl_2026.json"
TEAM_PROFILE = DATA / "tactical_team_profiles.json"
ROLE_PROFILE = DATA / "player_role_profiles.json"
POSITION_BY_TYPE = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
DERIVED_CACHE_REVISION = "UNDERSTAT_V3_OFFICIAL_IDENTITY_V1"
OFFICIAL_TO_UNDERSTAT_TEAM = {
    "Coventry City": "Coventry",
    "Hull City": "Hull",
    "Ipswich Town": "Ipswich",
    "Nott'm Forest": "Nottingham Forest",
}


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
    aliases = {
        "man utd": "manchester united",
        "man united": "manchester united",
        "man city": "manchester city",
        "spurs": "tottenham",
        "tottenham hotspur": "tottenham",
        "wolves": "wolverhampton wanderers",
        "newcastle": "newcastle united",
        "west ham": "west ham united",
        "brighton": "brighton and hove albion",
        "coventry city": "coventry",
        "hull city": "hull",
        "ipswich town": "ipswich",
        "nott m forest": "nottingham forest",
    }
    return aliases.get(text, text)


def _identity_variants(player: dict[str, Any]) -> list[str]:
    first = str(player.get("first_name") or "").strip()
    second = str(player.get("second_name") or "").strip()
    web = str(player.get("web_name") or "").strip()
    full = " ".join(part for part in (first, second) if part).strip()
    variants: list[str] = []
    seen: set[str] = set()
    for value in (full, web, second, first):
        key = _norm(value)
        if value and key and key not in seen:
            seen.add(key)
            variants.append(value)
    return variants


def _official_universe() -> list[dict[str, Any]]:
    """Build the full FPL universe from the already-owned Official snapshot.

    tactical_context must not depend on market_state merely to obtain universe.json.
    Official bootstrap already owns player identity/team/position and is the correct
    authority for Understat mapping. Full Official identity is retained so an
    abbreviated FPL web_name cannot unnecessarily suppress a valid source match.
    """
    official = read_json(DATA / "official_snapshot.json", {})
    bootstrap = official.get("bootstrap") or {}
    teams = {
        int(row.get("id") or -1): OFFICIAL_TO_UNDERSTAT_TEAM.get(
            str(row.get("name") or row.get("short_name") or row.get("id")),
            str(row.get("name") or row.get("short_name") or row.get("id")),
        )
        for row in bootstrap.get("teams") or []
        if row.get("id") is not None
    }
    rows: list[dict[str, Any]] = []
    for player in bootstrap.get("elements") or []:
        try:
            element = int(player.get("id") or 0)
            team_id = int(player.get("team") or 0)
            element_type = int(player.get("element_type") or 0)
        except (TypeError, ValueError):
            continue
        if element <= 0 or team_id <= 0:
            continue
        variants = _identity_variants(player)
        rows.append({
            "element": element,
            "name": variants[0] if variants else str(element),
            "web_name": player.get("web_name"),
            "first_name": player.get("first_name"),
            "second_name": player.get("second_name"),
            "name_variants": variants,
            "team": teams.get(team_id),
            "team_id": team_id,
            "position": POSITION_BY_TYPE.get(element_type),
        })
    return rows


def _raw_snapshot() -> tuple[dict[str, Any], str]:
    profile = str(os.getenv("FPL_EXECUTION_PROFILE") or "").strip().lower()
    # FAST decision is deterministic/cache-only: optional enrichment must never
    # spend network budget inside the hard serving SLO.
    if profile == "fast_decision":
        raw = understat.load()
        mode = "FAST_CACHE_ONLY"
        if raw.get("source_availability") == "UNAVAILABLE":
            raw["refresh_error"] = "network_refresh_deferred_in_fast_decision"
        return raw, mode
    return understat.sync(), "GOVERNED_REFRESH_OR_CACHE"


def _derived_cache_fingerprint(raw: dict[str, Any], universe: list[dict[str, Any]], fixtures: list[dict[str, Any]]) -> str:
    identity = [
        [
            int(row.get("element") or 0),
            _norm(row.get("name")),
            _norm(row.get("team")),
            str(row.get("position") or ""),
        ]
        for row in universe
    ]
    future_fixtures = [
        [
            row.get("id"),
            row.get("event"),
            row.get("team_h"),
            row.get("team_a"),
            row.get("kickoff_time"),
        ]
        for row in fixtures
        if not row.get("finished")
    ]
    material = {
        "revision": DERIVED_CACHE_REVISION,
        "source_fetched_at": raw.get("fetched_at"),
        "transport_revision": raw.get("transport_revision"),
        "identity": identity,
        "future_fixtures": future_fixtures,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reusable_tactical(
    raw: dict[str, Any],
    universe: list[dict[str, Any]],
    fixtures: list[dict[str, Any]],
    acquisition_mode: str,
) -> tuple[dict[str, Any] | None, str]:
    fingerprint = _derived_cache_fingerprint(raw, universe, fixtures)
    if acquisition_mode != "FAST_CACHE_ONLY":
        return None, fingerprint
    cached = read_json(OUT, {}) or {}
    native = cached.get("native_integration") or {}
    if (
        cached.get("contract") != "UNDERSTAT_TACTICAL_INTELLIGENCE_V1"
        or native.get("derived_cache_revision") != DERIVED_CACHE_REVISION
        or native.get("derived_cache_fingerprint") != fingerprint
    ):
        return None, fingerprint

    source = cached.setdefault("source", {})
    source.update({
        "availability": raw.get("source_availability"),
        "freshness": raw.get("freshness"),
        "fetched_at": raw.get("fetched_at"),
        "source_timestamp": raw.get("source_timestamp"),
        "schema_valid": raw.get("schema_valid"),
        "schema_defects": raw.get("schema_defects") or [],
        "fallback": bool(raw.get("fallback")),
        "cache_age_minutes": raw.get("cache_age_minutes"),
        "request_count": raw.get("request_count"),
        "provenance": raw.get("provenance") or {},
    })
    health = cached.setdefault("health", {})
    health["fallback_state"] = "LAST_KNOWN_GOOD" if raw.get("fallback") else "NONE"
    health["degradation_reason"] = raw.get("refresh_error") or raw.get("error")
    native["derived_cache_reused"] = True
    native["derived_cache_reused_at"] = iso_now()
    cached["native_integration"] = native
    return cached, fingerprint


def _window(team_evidence: dict[str, Any]) -> dict[str, Any]:
    windows = team_evidence.get("windows") or {}
    recent = windows.get("last_5") or {}
    if int(recent.get("matches") or 0) > 0:
        return recent
    return windows.get("season_to_date") or {}


def _team_route_context(team_evidence: dict[str, Any]) -> dict[str, list[str]]:
    """Translate multi-metric Understat evidence into existing tactical route labels.

    Route labels are emitted only when two coherent team metrics agree. PPDA is
    retained as a style proxy and never becomes a positive FPL route by itself.
    """
    window = _window(team_evidence)
    metrics = window.get("metrics_adjusted_per_match") or {}
    league = window.get("league_mean") or {}
    vulnerabilities: list[str] = []
    strengths: list[str] = []
    styles: list[str] = []

    xga, deep_allowed = _f(metrics.get("xga")), _f(metrics.get("deep_allowed"))
    league_xga, league_deep_allowed = _f(league.get("xga")), _f(league.get("deep_allowed"))
    if None not in (xga, deep_allowed, league_xga, league_deep_allowed):
        if xga > league_xga and deep_allowed > league_deep_allowed:
            vulnerabilities.extend(["box_pressure", "final_third_progression"])
        elif xga < league_xga and deep_allowed < league_deep_allowed:
            strengths.extend(["box_pressure", "final_third_progression"])

    xg, deep = _f(metrics.get("xg")), _f(metrics.get("deep"))
    league_xg, league_deep = _f(league.get("xg")), _f(league.get("deep"))
    if None not in (xg, deep, league_xg, league_deep):
        if xg > league_xg and deep > league_deep:
            styles.extend(["high_chance_generation", "high_deep_access"])
        elif xg < league_xg and deep < league_deep:
            styles.extend(["low_chance_generation", "low_deep_access"])

    ppda, league_ppda = _f(metrics.get("ppda")), _f(league.get("ppda"))
    if ppda is not None and league_ppda is not None:
        styles.append("high_press_activity_proxy" if ppda < league_ppda else "low_press_activity_proxy")

    return {
        "vulnerabilities": sorted(set(vulnerabilities)),
        "strengths": sorted(set(strengths)),
        "style_proxies": sorted(set(styles)),
    }


def _metric_value(season: dict[str, Any], name: str) -> float | None:
    raw = (season.get("metrics") or {}).get(name)
    if isinstance(raw, dict):
        return _f(raw.get("value"))
    return _f(raw)


def _player_return_routes(player_evidence: dict[str, Any]) -> list[str]:
    season = player_evidence.get("season_to_date") or {}
    if not season:
        return []
    routes: list[str] = []
    xg = _metric_value(season, "xg")
    shots = _metric_value(season, "shots")
    xa = _metric_value(season, "xa")
    key_passes = _metric_value(season, "key_passes")
    chain = _metric_value(season, "xgchain")
    buildup = _metric_value(season, "xgbuildup")
    if (xg or 0.0) > 0.0 or (shots or 0.0) > 0.0:
        routes.extend(["shot_volume", "box_pressure"])
    if (xa or 0.0) > 0.0 or (key_passes or 0.0) > 0.0:
        routes.append("chance_creation")
    if (chain or 0.0) > 0.0 or (buildup or 0.0) > 0.0:
        routes.append("final_third_progression")
    return sorted(set(routes))


def _compact_matchup(row: dict[str, Any]) -> dict[str, Any]:
    dimensions = row.get("dimensions") or {}
    return {
        "state": row.get("state") or "INSUFFICIENT_EVIDENCE",
        "confidence": row.get("confidence") or 0.0,
        "freshness": row.get("freshness"),
        "sample_size": row.get("sample_size") or {},
        "opponent": (row.get("opponent_evidence") or {}).get("team") or row.get("opponent"),
        "supporting_signals": list(row.get("supporting_signals") or [])[:4],
        "conflicting_signals": list(row.get("conflicting_signals") or [])[:4],
        "dimensions": {
            name: (value or {}).get("state")
            for name, value in dimensions.items()
            if isinstance(value, dict)
        },
        "uncertainty": row.get("uncertainty") or {},
        "provenance": row.get("provenance") or {},
    }


def _extend(values: Any, additions: list[str]) -> list[str]:
    existing = [str(value) for value in (values or []) if value]
    return sorted(set(existing) | set(additions))


def _merge_canonical_tactical_artifacts(tactical: dict[str, Any]) -> dict[str, int]:
    """Enrich the existing tactical owner rather than creating a second consumer.

    Prediction and decision layers continue to consume only canonical tactical
    profiles. Understat contributes evidence to those profiles; it never owns a
    second lineup/watchlist/report decision path.
    """
    teams_payload = read_json(TEAM_PROFILE, {})
    roles_payload = read_json(ROLE_PROFILE, {})
    team_rows = teams_payload.get("teams") if isinstance(teams_payload, dict) else {}
    role_rows = roles_payload.get("players") if isinstance(roles_payload, dict) else {}
    if not isinstance(team_rows, dict) or not isinstance(role_rows, dict):
        raise RuntimeError("canonical tactical artifacts unavailable for Understat enrichment")

    understat_teams = tactical.get("team_evidence") or {}
    understat_players = tactical.get("player_evidence") or {}
    matchups = tactical.get("tactical_matchups") or {}
    source = tactical.get("source") or {}

    team_index = {
        _norm((row or {}).get("team")): row
        for row in understat_teams.values()
        if isinstance(row, dict) and (row or {}).get("team")
    }
    team_enriched = 0
    for team in team_rows.values():
        if not isinstance(team, dict):
            continue
        evidence = team_index.get(_norm(team.get("team_name")))
        if not evidence:
            continue
        route_context = _team_route_context(evidence)
        team["vulnerabilities"] = _extend(team.get("vulnerabilities"), route_context["vulnerabilities"])
        team["strengths"] = _extend(team.get("strengths"), route_context["strengths"])
        team["observed_style_proxies"] = _extend(team.get("observed_style_proxies"), route_context["style_proxies"])
        team["understat_tactical"] = {
            "source": "Understat",
            "source_availability": source.get("availability"),
            "freshness": source.get("freshness"),
            "understat_team_id": evidence.get("understat_team_id"),
            "history_matches": evidence.get("history_matches"),
            "windows": evidence.get("windows") or {},
            "canonical_route_contribution": route_context,
            "ppda_is_context_not_direct_fpl_value": True,
        }
        team.setdefault("evidence", {})["understat_enrichment"] = {
            "contract": "UNDERSTAT_TACTICAL_INTELLIGENCE_V1",
            "source_observed_vs_derived_explicit": True,
            "small_sample_shrinkage_explicit": True,
            "direct_xpts_mutation": False,
        }
        team_enriched += 1

    player_enriched = 0
    route_enriched = 0
    for key, role in role_rows.items():
        if not isinstance(role, dict):
            continue
        try:
            element = int(role.get("element") or key)
        except (TypeError, ValueError):
            continue
        player = understat_players.get(str(element)) or {}
        matchup = matchups.get(str(element)) or {}
        if not player:
            continue
        additions = _player_return_routes(player)
        if additions:
            role["return_routes"] = _extend(role.get("return_routes"), additions)
            route_enriched += 1
        role["understat_tactical"] = {
            "mapping": player.get("mapping") or {},
            "season_to_date": player.get("season_to_date"),
            "rolling_windows": player.get("rolling_windows") or {},
            "return_route_contribution": additions,
            "next_matchup": _compact_matchup(matchup),
            "source": {
                "provider": "Understat",
                "availability": source.get("availability"),
                "freshness": source.get("freshness"),
            },
        }
        role.setdefault("evidence", {})["understat_enrichment"] = {
            "contract": "UNDERSTAT_TACTICAL_INTELLIGENCE_V1",
            "mapping_state": (player.get("mapping") or {}).get("state"),
            "decision_influence": "EXISTING_TACTICAL_CLOSE_CALL_PATH_ONLY",
            "direct_xpts_mutation": False,
            "direct_xmins_mutation": False,
        }
        player_enriched += 1

    teams_payload.setdefault("governance", {}).update({
        "understat_extends_canonical_tactical_evidence": True,
        "understat_does_not_create_second_tactical_authority": True,
        "understat_ppda_direct_xpts_conversion_forbidden": True,
    })
    roles_payload.setdefault("governance", {}).update({
        "understat_extends_existing_return_route_evidence": True,
        "understat_player_mapping_unresolved_is_neutral": True,
        "understat_direct_xpts_xmins_mutation_forbidden": True,
    })
    atomic_json(TEAM_PROFILE, teams_payload)
    atomic_json(ROLE_PROFILE, roles_payload)
    return {
        "team_profiles_enriched": team_enriched,
        "player_profiles_enriched": player_enriched,
        "player_return_routes_enriched": route_enriched,
    }


def build() -> dict[str, Any]:
    official = read_json(DATA / "official_snapshot.json", {})
    universe = _official_universe()
    raw, acquisition_mode = _raw_snapshot()
    # Always persist a truthfully shaped cache artifact so an optional source
    # outage cannot turn a declared runtime artifact into an integrity failure.
    atomic_json(RAW_CACHE, raw)

    fixtures = list(official.get("fixtures") or [])
    snapshot = {"official": {"fixtures": fixtures}}
    tactical, cache_fingerprint = _reusable_tactical(raw, universe, fixtures, acquisition_mode)
    derived_cache_reused = tactical is not None
    if tactical is None:
        tactical = build_understat_tactical(raw, snapshot, universe)
        tactical["engine"] = "V3"
        for matchup in (tactical.get("tactical_matchups") or {}).values():
            if not isinstance(matchup, dict):
                continue
            interaction = matchup.get("player_role_interaction")
            if isinstance(interaction, dict):
                interaction["xmins_authority"] = "V3_PREDICTION_NOT_UNDERSTAT"

    canonical_merge = _merge_canonical_tactical_artifacts(tactical)
    native = tactical.setdefault("native_integration", {})
    native.update({
        "architecture": "V3_CANONICAL_DOMAIN_PIPELINE",
        "owner": "tactical_context",
        "acquisition_mode": acquisition_mode,
        "official_fpl_identity_and_fixture_authority_preserved": True,
        "official_universe_derived_from_existing_official_snapshot": True,
        "canonical_tactical_artifacts_enriched": canonical_merge,
        "existing_tactical_decision_consumption_reused": True,
        "second_decision_consumer_created": False,
        "direct_xpts_mutation": False,
        "direct_xmins_mutation": False,
        "captaincy_semantics_unchanged": True,
        "derived_cache_revision": DERIVED_CACHE_REVISION,
        "derived_cache_fingerprint": cache_fingerprint,
        "derived_cache_reused": derived_cache_reused,
    })

    health = {
        "schema_version": 1,
        "contract": "V3_UNDERSTAT_TACTICAL_HEALTH_V1",
        "generated_at": tactical.get("generated_at"),
        "status": (tactical.get("health") or {}).get("status") or "UNAVAILABLE",
        "optional_enrichment": True,
        "source": tactical.get("source") or {},
        "coverage": tactical.get("health") or {},
        "canonical_merge": canonical_merge,
        "acquisition_mode": acquisition_mode,
        "derived_cache_reused": derived_cache_reused,
        "production_blocking": False,
        "governance": {
            "official_fpl_authority_preserved": True,
            "missing_is_unknown_not_zero": True,
            "stale_never_labeled_fresh": True,
            "fast_decision_network_io_forbidden": True,
            "understat_failure_does_not_block_unrelated_v3": True,
            "ppda_direct_xpts_conversion_forbidden": True,
            "existing_tactical_decision_path_reused": True,
            "duplicate_decision_authority_forbidden": True,
            "fast_reuses_normalized_tactical_snapshot_when_fingerprint_matches": True,
        },
    }
    return {"tactical": tactical, "health": health}


def run() -> dict[str, Any]:
    out = build()
    atomic_json(OUT, out["tactical"])
    atomic_json(HEALTH_OUT, out["health"])
    latest = read_json(DATA / "latest.json", {})
    if latest:
        latest.setdefault("files", {}).update({
            "understat_tactical": "data/understat_tactical_v3.json",
            "understat_tactical_health": "data/understat_tactical_health_v3.json",
        })
        health = out["health"]
        coverage = health.get("coverage") or {}
        latest["understat_tactical_summary"] = {
            "status": health.get("status"),
            "source_availability": (health.get("source") or {}).get("availability"),
            "freshness": (health.get("source") or {}).get("freshness"),
            "player_mapping_coverage": coverage.get("player_mapping_coverage"),
            "tactical_matchup_coverage": coverage.get("tactical_matchup_coverage"),
            "full_universe_count": coverage.get("official_universe_count"),
            "canonical_merge": health.get("canonical_merge") or {},
            "derived_cache_reused": health.get("derived_cache_reused"),
            "optional_enrichment": True,
        }
        atomic_json(DATA / "latest.json", latest)
    print(json.dumps({
        "status": out["health"].get("status"),
        "coverage": out["health"].get("coverage"),
        "canonical_merge": out["health"].get("canonical_merge"),
        "acquisition_mode": out["health"].get("acquisition_mode"),
        "derived_cache_reused": out["health"].get("derived_cache_reused"),
    }, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()