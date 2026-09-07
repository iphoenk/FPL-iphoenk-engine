from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDITIONS = ROOT / "config" / "v6" / "source_additions.json"


def _wikidata_source() -> dict:
    payload = json.loads(ADDITIONS.read_text(encoding="utf-8"))
    return next(row for row in payload["sources"] if row["id"] == "wikidata")


def test_wikidata_query_is_entity_typed_and_grouped_by_qid() -> None:
    source = _wikidata_source()
    query = source["requests"][0]["params"]["query"]

    assert "wdt:P118 wd:Q9448" in query
    assert "wdt:P31/wdt:P279* wd:Q476028" in query
    assert "SAMPLE(?website) AS ?website" in query
    assert "GROUP BY ?club ?clubLabel" in query
    assert "ORDER BY ?clubLabel" in query


def test_wikidata_scope_does_not_claim_current_season_membership_or_identity_authority() -> None:
    source = _wikidata_source()
    notes = source["notes"].lower()

    assert "not treated as proof of current-season membership" in notes
    assert "never supersede official fpl identity" in notes
    assert "never authorize fuzzy runtime joins" in notes
    assert source["category"] == "identity_bridge_reference"
    assert source["critical"] is False


def test_wikidata_remains_zero_cost_no_auth_public_only() -> None:
    source = _wikidata_source()
    access = source["access"]

    assert access["cost"] == "ZERO"
    assert access["account_required"] is False
    assert access["login_required"] is False
    assert access["private_api_key_required"] is False
    assert access["private_token_required"] is False
    assert access["shared_public_key"] is False
    assert source.get("auth") is None
