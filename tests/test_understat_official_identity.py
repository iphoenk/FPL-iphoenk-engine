from __future__ import annotations

import json

from src.engines import understat_tactical_context as context


def _write_official(tmp_path) -> None:
    payload = {
        "bootstrap": {
            "teams": [
                {"id": 1, "name": "Arsenal", "short_name": "ARS"},
                {"id": 2, "name": "Hull City", "short_name": "HUL"},
                {"id": 3, "name": "Nott'm Forest", "short_name": "NFO"},
            ],
            "elements": [
                {
                    "id": 7,
                    "team": 1,
                    "element_type": 3,
                    "first_name": "Bukayo",
                    "second_name": "Saka",
                    "web_name": "Saka",
                },
                {
                    "id": 8,
                    "team": 2,
                    "element_type": 4,
                    "first_name": "Dominic",
                    "second_name": "Calvert-Lewin",
                    "web_name": "Calvert-Lewin",
                },
                {
                    "id": 9,
                    "team": 3,
                    "element_type": 2,
                    "first_name": "Murillo",
                    "second_name": "Santiago Costa dos Santos",
                    "web_name": "Murillo",
                },
            ],
        }
    }
    (tmp_path / "official_snapshot.json").write_text(json.dumps(payload), encoding="utf-8")


def test_official_universe_prefers_full_identity_over_abbreviated_web_name(monkeypatch, tmp_path):
    monkeypatch.setattr(context, "DATA", tmp_path)
    _write_official(tmp_path)

    universe = context._official_universe()
    by_id = {row["element"]: row for row in universe}

    assert by_id[7]["name"] == "Bukayo Saka"
    assert by_id[7]["web_name"] == "Saka"
    assert by_id[7]["name_variants"] == ["Bukayo Saka", "Saka", "Bukayo"]
    assert by_id[8]["name"] == "Dominic Calvert-Lewin"
    assert by_id[8]["position"] == "FWD"


def test_promoted_and_abbreviated_team_names_are_canonicalized_for_understat(monkeypatch, tmp_path):
    monkeypatch.setattr(context, "DATA", tmp_path)
    _write_official(tmp_path)

    universe = context._official_universe()
    by_id = {row["element"]: row for row in universe}

    assert by_id[8]["team"] == "Hull"
    assert by_id[9]["team"] == "Nottingham Forest"
    assert context._norm("Hull City") == context._norm("Hull")
    assert context._norm("Nott'm Forest") == context._norm("Nottingham Forest")


def test_identity_variants_are_deduplicated_after_normalization():
    variants = context._identity_variants(
        {
            "first_name": "João",
            "second_name": "Pedro",
            "web_name": "Joao Pedro",
        }
    )

    assert variants == ["João Pedro", "Pedro", "João"]


def test_fast_lane_reuses_normalized_tactical_snapshot_on_exact_fingerprint(monkeypatch, tmp_path):
    target = tmp_path / "understat_tactical_v3.json"
    monkeypatch.setattr(context, "OUT", target)
    raw = {
        "fetched_at": "2026-09-02T13:04:09+00:00",
        "transport_revision": "UNDERSTAT_XHR_JSON_V1",
        "source_availability": "AVAILABLE",
        "freshness": "FRESH",
        "schema_valid": True,
        "fallback": False,
        "provenance": {"provider": "Understat"},
    }
    universe = [{"element": 7, "name": "Bukayo Saka", "team": "Arsenal", "position": "MID"}]
    fixtures = [{"id": 99, "event": 3, "team_h": 1, "team_a": 2, "kickoff_time": "2026-09-04T17:30:00Z", "finished": False}]
    fingerprint = context._derived_cache_fingerprint(raw, universe, fixtures)
    cached = {
        "contract": "UNDERSTAT_TACTICAL_INTELLIGENCE_V1",
        "source": {"availability": "AVAILABLE"},
        "health": {"status": "AVAILABLE"},
        "native_integration": {
            "derived_cache_revision": context.DERIVED_CACHE_REVISION,
            "derived_cache_fingerprint": fingerprint,
        },
    }
    target.write_text(json.dumps(cached), encoding="utf-8")

    reused, observed = context._reusable_tactical(raw, universe, fixtures, "FAST_CACHE_ONLY")

    assert observed == fingerprint
    assert reused is not None
    assert reused["native_integration"]["derived_cache_reused"] is True
    assert reused["source"]["freshness"] == "FRESH"


def test_fast_lane_recomputes_when_identity_or_fixture_fingerprint_changes(monkeypatch, tmp_path):
    target = tmp_path / "understat_tactical_v3.json"
    monkeypatch.setattr(context, "OUT", target)
    raw = {
        "fetched_at": "2026-09-02T13:04:09+00:00",
        "transport_revision": "UNDERSTAT_XHR_JSON_V1",
    }
    universe = [{"element": 7, "name": "Bukayo Saka", "team": "Arsenal", "position": "MID"}]
    fixtures = [{"id": 99, "event": 3, "team_h": 1, "team_a": 2, "kickoff_time": "2026-09-04T17:30:00Z", "finished": False}]
    stale_fingerprint = context._derived_cache_fingerprint(raw, universe, fixtures)
    target.write_text(json.dumps({
        "contract": "UNDERSTAT_TACTICAL_INTELLIGENCE_V1",
        "native_integration": {
            "derived_cache_revision": context.DERIVED_CACHE_REVISION,
            "derived_cache_fingerprint": stale_fingerprint,
        },
    }), encoding="utf-8")
    changed_universe = [{"element": 7, "name": "Bukayo Saka", "team": "Arsenal", "position": "FWD"}]

    reused, current = context._reusable_tactical(raw, changed_universe, fixtures, "FAST_CACHE_ONLY")

    assert current != stale_fingerprint
    assert reused is None


def test_non_fast_profile_never_uses_derived_tactical_cache(monkeypatch, tmp_path):
    target = tmp_path / "understat_tactical_v3.json"
    monkeypatch.setattr(context, "OUT", target)
    raw = {"fetched_at": "2026-09-02T13:04:09+00:00", "transport_revision": "UNDERSTAT_XHR_JSON_V1"}
    universe = [{"element": 7, "name": "Bukayo Saka", "team": "Arsenal", "position": "MID"}]
    fixtures: list[dict] = []
    fingerprint = context._derived_cache_fingerprint(raw, universe, fixtures)
    target.write_text(json.dumps({
        "contract": "UNDERSTAT_TACTICAL_INTELLIGENCE_V1",
        "native_integration": {
            "derived_cache_revision": context.DERIVED_CACHE_REVISION,
            "derived_cache_fingerprint": fingerprint,
        },
    }), encoding="utf-8")

    reused, observed = context._reusable_tactical(raw, universe, fixtures, "GOVERNED_REFRESH_OR_CACHE")

    assert observed == fingerprint
    assert reused is None
