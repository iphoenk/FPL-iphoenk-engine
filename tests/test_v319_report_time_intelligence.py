from __future__ import annotations

from datetime import datetime, timezone

from src.engines.report_time_intelligence import build_pundit_consensus, validate_evidence, validate_registry
from src.utils import ROOT

NOW = datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)


def _signal(source_id: str, source_class: str, subject: str, stance: str, *, hours_ago: int = 1, topic: str = "transfer") -> dict:
    observed = datetime(2026, 8, 26, 23 - hours_ago + 1, 0, tzinfo=timezone.utc)
    return {
        "source_id": source_id,
        "source_class": source_class,
        "topic": topic,
        "subject": subject,
        "stance": stance,
        "observed_at": observed.isoformat(),
        "source_url": f"https://example.com/{source_id}",
        "summary": f"{source_id} {stance} {subject}",
    }


def test_report_time_registry_has_separated_source_classes():
    health = validate_registry()
    assert health["integrity_ok"] is True
    registry = (ROOT / "config" / "sources" / "report_time_registry.json").read_text()
    assert '"onefpl"' in registry
    assert '"ben_crellin"' in registry
    assert '"reddit_fantasypl"' in registry
    assert '"PUNDIT_CONSENSUS"' in registry
    assert '"FIXTURE_STRATEGY_EXPERT"' in registry
    assert '"COMMUNITY_SIGNAL"' in registry


def test_pundit_consensus_aligns_with_dss_watchlist():
    payload = {
        "contract": "report_time_evidence_v1",
        "signals": [
            _signal("fpl_harry", "PUNDIT_CONSENSUS", "Example Player", "BUY"),
            _signal("fpl_focal", "PUNDIT_CONSENSUS", "Example Player", "BUY"),
            _signal("lets_talk_fpl", "PUNDIT_CONSENSUS", "Example Player", "BUY"),
        ],
    }
    validated = validate_evidence(payload, now=NOW)
    rows = build_pundit_consensus(
        validated["accepted"],
        {"exampleplayer": {"state": "WATCHLIST", "element": 999}},
        __import__("json").loads((ROOT / "config" / "sources" / "report_time_registry.json").read_text()),
    )
    assert len(rows) == 1
    assert rows[0]["winner"] == "BUY"
    assert rows[0]["strength"] == "STRONG"
    assert rows[0]["alignment_with_dss"] == "ALIGN"
    assert rows[0]["dss_state"] == "WATCHLIST"


def test_pundit_consensus_surfaces_divergence_instead_of_mutating_dss():
    payload = {
        "contract": "report_time_evidence_v1",
        "signals": [
            _signal("fpl_harry", "PUNDIT_CONSENSUS", "Outside Player", "BUY"),
            _signal("fpl_focal", "PUNDIT_CONSENSUS", "Outside Player", "BUY"),
        ],
    }
    validated = validate_evidence(payload, now=NOW)
    registry = __import__("json").loads((ROOT / "config" / "sources" / "report_time_registry.json").read_text())
    rows = build_pundit_consensus(validated["accepted"], {}, registry)
    assert rows[0]["alignment_with_dss"] == "DIVERGE"
    assert rows[0]["advisory_only"] is True


def test_ben_crellin_and_reddit_do_not_vote_in_pundit_consensus():
    payload = {
        "contract": "report_time_evidence_v1",
        "signals": [
            _signal("ben_crellin", "FIXTURE_STRATEGY_EXPERT", "GW8", "FIXTURE_ALERT", topic="fixtures"),
            _signal("reddit_fantasypl", "COMMUNITY_SIGNAL", "Example Player", "ROLE_POSITIVE", topic="role"),
            _signal("fpl_harry", "PUNDIT_CONSENSUS", "Example Player", "BUY"),
        ],
    }
    validated = validate_evidence(payload, now=NOW)
    registry = __import__("json").loads((ROOT / "config" / "sources" / "report_time_registry.json").read_text())
    assert build_pundit_consensus(validated["accepted"], {}, registry) == []
    by_source = {row["source_id"]: row for row in validated["accepted"]}
    assert by_source["ben_crellin"]["consensus_eligible"] is False
    assert by_source["reddit_fantasypl"]["consensus_eligible"] is False


def test_stale_pundit_signal_is_not_counted_as_current_consensus():
    payload = {
        "contract": "report_time_evidence_v1",
        "signals": [
            {
                **_signal("fpl_harry", "PUNDIT_CONSENSUS", "Example Player", "BUY"),
                "observed_at": "2026-08-20T00:00:00+00:00",
            },
            _signal("fpl_focal", "PUNDIT_CONSENSUS", "Example Player", "BUY"),
        ],
    }
    validated = validate_evidence(payload, now=NOW)
    registry = __import__("json").loads((ROOT / "config" / "sources" / "report_time_registry.json").read_text())
    assert build_pundit_consensus(validated["accepted"], {}, registry) == []


def test_report_time_evidence_rejects_source_class_mismatch():
    payload = {
        "contract": "report_time_evidence_v1",
        "signals": [
            _signal("ben_crellin", "PUNDIT_CONSENSUS", "GW8", "BUY"),
        ],
    }
    result = validate_evidence(payload, now=NOW)
    assert result["accepted_count"] == 0
    assert result["rejected"][0]["reason"] == "SOURCE_CLASS_MISMATCH"
