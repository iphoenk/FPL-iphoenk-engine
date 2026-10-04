import json
from pathlib import Path

from src.engines.report_time_intelligence import validate_evidence, validate_registry


ROOT = Path(__file__).resolve().parents[1]


def test_six_source_registry_preserves_lane_and_authority_boundaries():
    challenger = json.loads((ROOT / "config/intelligence/challenger_registry.json").read_text())
    providers = {row["id"]: row for row in challenger["providers"]}
    assert providers["fpl_tactics"]["authority"] == "ADVISORY_ONLY"
    assert providers["fplratings"]["authority"] == "DIAGNOSTIC_ONLY"
    assert providers["fplanaly"]["authority"] == "ADVISORY_ONLY"
    assert challenger["governance"]["root_family_is_the_independence_unit"] is True

    report = json.loads((ROOT / "config/sources/report_time_registry.json").read_text())
    sources = {row["id"]: row for row in report["sources"]}
    assert sources["fpl_analytics_dashboard"]["consensus_vote"] is False
    assert sources["allaboutfpl"]["consensus_vote"] is False
    assert sources["fpl_analytics_dashboard"]["retrieval"] == "REPORT_TIME_TARGETED_WEB"

    health = validate_registry(report)
    assert health["integrity_ok"] is True, health


def test_report_time_registry_rejects_external_vote_authority():
    report = json.loads((ROOT / "config/sources/report_time_registry.json").read_text())
    for row in report["sources"]:
        if row["id"] in {"fpl_analytics_dashboard", "allaboutfpl"}:
            row["consensus_vote"] = True
    health = validate_registry(report)
    assert health["integrity_ok"] is False


def test_new_external_report_time_evidence_requires_lineage_metadata():
    payload = {
        "contract": "report_time_evidence_v1",
        "signals": [{
            "source_id": "fpl_analytics_dashboard",
            "source_class": "MODEL_CHALLENGER",
            "topic": "distribution",
            "subject": "Player A",
            "stance": "CAPTAIN",
            "observed_at": "2026-10-04T11:30:00+00:00",
            "source_url": "https://fplanalyticsdashboard.com/players/player-a",
            "summary": "ceiling context",
        }],
    }
    result = validate_evidence(payload)
    assert result["accepted_count"] == 0
    assert result["rejected"][0]["reason"] == "MISSING_LINEAGE_FIELDS"


def test_cardstats_admission_is_explicit_and_nonblocking():
    admission = json.loads((ROOT / "config/v6/cardstats_admission.json").read_text())
    assert admission["decision"] == "PROMOTE_V6_NO"
    assert admission["failure_isolation"] == "CANDIDATE_NONBLOCKING_NOT_ACTIVE"
    assert admission["provenance"]["predictive_fields_admitted"] is False
    assert admission["identity"]["name_only_join_allowed"] is False
