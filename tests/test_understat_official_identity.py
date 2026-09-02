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
