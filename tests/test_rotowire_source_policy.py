from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_rotowire_is_registered_once_in_v6_below_understat_and_noncritical():
    registry = _load("config/v6/source_registry.json")
    sources = registry["sources"]
    ids = [source["id"] for source in sources]

    assert ids.count("rotowire") == 1
    assert ids.index("understat") < ids.index("rotowire")

    rotowire = next(source for source in sources if source["id"] == "rotowire")
    assert rotowire["category"] == "availability_lineups"
    assert rotowire["critical"] is False
    assert rotowire["independence_group"] == "rotowire"
    assert rotowire["requests"][0]["url"] == "https://www.rotowire.com/soccer/lineups.php"


def test_rotowire_report_time_fallback_is_secondary_and_advisory_only():
    registry = _load("config/sources/report_time_registry.json")
    sources = registry["sources"]
    rotowire = next(source for source in sources if source["id"] == "rotowire")

    assert registry["policy"]["secondary_availability_sources_are_advisory_only"] is True
    assert registry["policy"]["secondary_availability_requires_primary_crosscheck"] is True
    assert registry["consensus"]["freshness_hours"]["SECONDARY_AVAILABILITY"] == 12

    assert rotowire["enabled"] is True
    assert rotowire["retrieval"] == "REPORT_TIME_WEB"
    assert rotowire["class"] == "SECONDARY_AVAILABILITY"
    assert rotowire["consensus_vote"] is False
    assert rotowire["authority_ceiling"] == "ADVISORY"
    assert "rotowire.com" in rotowire["domains"]
    assert {"predicted_lineups", "availability_signal", "injury_signal"}.issubset(
        set(rotowire["capabilities"])
    )


def test_rotowire_never_replaces_primary_or_verified_authority():
    report_registry = _load("config/sources/report_time_registry.json")
    rotowire = next(source for source in report_registry["sources"] if source["id"] == "rotowire")

    assert report_registry["policy"]["official_fpl_remains_native_authority"] is True
    assert report_registry["policy"]["report_time_sources_never_override_verified_facts"] is True
    assert rotowire["authority_ceiling"] != "VERIFIED_CONTEXT"
    assert rotowire["consensus_vote"] is False
