from __future__ import annotations

import json
from pathlib import Path

from src.runtime_v6.operational_reliability import densify_operational_slots
from src.runtime_v6.registry import load_registry, source_map
from src.runtime_v6.season_contract import load_season_contract, materialize_season_tokens
from src.runtime_v6.source_contract_doc import render_source_contract

ROOT = Path(__file__).resolve().parents[1]


def _workflow_paths(text: str, event: str) -> list[str]:
    lines = text.splitlines()
    event_line = next(i for i, line in enumerate(lines) if line == f"  {event}:")
    paths_line = next(i for i in range(event_line + 1, len(lines)) if lines[i].strip() == "paths:")
    values: list[str] = []
    for line in lines[paths_line + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) < 6:
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            values.append(stripped[2:].strip().strip('"'))
    return values


def test_generated_source_contract_is_exactly_registry_derived() -> None:
    expected = render_source_contract()
    actual = (ROOT / "docs" / "V6_SOURCE_CONTRACT_GENERATED.md").read_text(encoding="utf-8")
    assert actual == expected
    assert "Configured source definitions | 38" in actual
    assert "Active scheduled sources | 22" in actual
    assert "Temporary source overrides | 0" in actual


def test_adaptive_policy_does_not_hand_maintain_source_counts() -> None:
    policy = (ROOT / "docs" / "V6_ADAPTIVE_INGESTION_POLICY.md").read_text(encoding="utf-8")
    assert "base catalogue contains 27" not in policy
    assert "active scheduled acquisition set contains 20" not in policy
    assert "V6_SOURCE_CONTRACT_GENERATED.md" in policy


def test_v6_ci_pull_request_and_push_path_filters_are_identical() -> None:
    workflow = (ROOT / ".github" / "workflows" / "v6-ci.yml").read_text(encoding="utf-8")
    assert _workflow_paths(workflow, "pull_request") == _workflow_paths(workflow, "push")


def test_season_contract_derives_provider_notations_deterministically() -> None:
    contract = load_season_contract()
    assert contract["values"] == {
        "competition": "EPL",
        "start_year": "2026",
        "end_year": "2027",
        "end_year_short": "27",
        "canonical": "2026-2027",
        "slash_full": "2026/2027",
        "slash_short": "2026/27",
        "hyphen_short": "2026-27",
        "compact_short": "2627",
    }
    rendered = materialize_season_tokens(
        {
            "season": "{{season.canonical}}",
            "understat": "{{season.start_year}}",
            "fotmob": "{{season.slash_full}}",
            "vaastav": "{{season.hyphen_short}}",
            "football_data": "{{season.compact_short}}",
        }
    )
    assert rendered == {
        "season": "2026-2027",
        "understat": "2026",
        "fotmob": "2026/2027",
        "vaastav": "2026-27",
        "football_data": "2627",
    }


def test_provider_season_bindings_are_tokenized_and_resolve_from_one_contract() -> None:
    raw = (ROOT / "config" / "v6" / "source_registry.json").read_text(encoding="utf-8")
    for stale_literal in ("2026-2027", "2026/2027", "2026/27", "2026-27", "/2627/"):
        assert stale_literal not in raw
    assert "{{season." in raw

    registry = load_registry()
    sources = source_map(registry)
    assert registry["season"] == "2026-2027"
    understat = sources["understat"]["requests"]
    assert understat[0]["url"].endswith("/league/EPL/2026")
    assert understat[1]["form"]["season"] == "2026"
    assert sources["fotmob"]["requests"][0]["params"]["season"] == "2026/2027"
    assert "/2026-27/" in sources["vaastav_fpl"]["requests"][0]["url"]

    consumer = json.loads((ROOT / "config" / "v6" / "consumer_context.json").read_text(encoding="utf-8"))
    assert consumer["season"] == load_season_contract()["values"]["canonical"]


def test_operational_reliability_counts_retrospective_missing_slots() -> None:
    ledger = {
        "schema_version": 1,
        "slots": [
            {"slot": "2026-09-07T15:00:00+00:00", "fulfilled_by": "RECOVERY"},
            {"slot": "2026-09-07T16:00:00+00:00", "fulfilled_by": "PRIMARY"},
            {"slot": "2026-09-07T19:00:00+00:00", "fulfilled_by": "RECOVERY"},
            {"slot": "2026-09-07T20:00:00+00:00", "fulfilled_by": "PRIMARY"},
        ],
    }
    dense = densify_operational_slots(ledger, interval_minutes=60)
    summary = dense["summary"]
    assert summary["tracked_operational_slots"] == 6
    assert summary["fulfilled_operational_slots"] == 4
    assert summary["missing_operational_slots"] == 2
    assert summary["natural_fulfillment_ratio"] == 0.6667
    assert summary["operational_fulfillment_ratio"] == 0.6667
    assert summary["health"] == "RED"
    missing = [row for row in dense["slots"] if row["fulfilled_by"] == "MISSING"]
    assert [row["slot"] for row in missing] == [
        "2026-09-07T17:00:00+00:00",
        "2026-09-07T18:00:00+00:00",
    ]
    assert all(row["missing_classification_is_retrospective"] is True for row in missing)


def test_operational_reliability_does_not_infer_beyond_latest_observed_slot() -> None:
    ledger = {
        "slots": [
            {"slot": "2026-09-07T20:00:00+00:00", "fulfilled_by": "PRIMARY"},
        ]
    }
    dense = densify_operational_slots(ledger, interval_minutes=60)
    assert len(dense["slots"]) == 1
    assert dense["slots"][0]["slot"] == "2026-09-07T20:00:00+00:00"
