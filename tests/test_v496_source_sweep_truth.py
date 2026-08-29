import json
from pathlib import Path

from src.engines.source_sweep_status import build_source_sweep_status

ROOT = Path(__file__).resolve().parents[1]


def test_every_governed_deadline_source_has_explicit_truth_status():
    policy = json.loads((ROOT / "config/checkpoint_policy_registry.json").read_text())
    expected = {
        source
        for sources in (policy["source_sweep"]["tiers"] or {}).values()
        for source in sources
    }
    out = build_source_sweep_status({"bootstrap": {"status": "LIVE"}})
    rows = {row["source_id"]: row for row in out["statuses"]}
    assert set(rows) == expected
    assert out["all_governance_sources_accounted_for"] is True
    assert rows["official_fpl_native"]["status"] == "AVAILABLE"
    assert rows["official_fpl_native"]["runtime_wired"] is True
    for source_id, row in rows.items():
        if source_id != "official_fpl_native":
            assert row["status"] == "UNAVAILABLE"
            assert row["runtime_wired"] is False


def test_failed_official_endpoints_are_never_reported_fully_available():
    out = build_source_sweep_status({
        "bootstrap": {"status": "LIVE"},
        "fixtures": {"status": "FAILED"},
    })
    official = next(row for row in out["statuses"] if row["source_id"] == "official_fpl_native")
    assert official["status"] == "PARTIAL"


def test_external_sweep_can_upgrade_only_with_explicit_valid_evidence():
    out = build_source_sweep_status(
        {"bootstrap": {"status": "LIVE"}},
        external_evidence={
            "official_clubs": {"status": "NO MATERIAL UPDATE", "evidence": "report_time_verified_club_sweep"},
            "reddit": {"status": "PARTIAL", "evidence": "report_time_verified_community_sweep"},
        },
    )
    rows = {row["source_id"]: row for row in out["statuses"]}
    assert rows["official_clubs"]["status"] == "NO MATERIAL UPDATE"
    assert rows["reddit"]["status"] == "PARTIAL"
    assert rows["onefpl"]["status"] == "UNAVAILABLE"
