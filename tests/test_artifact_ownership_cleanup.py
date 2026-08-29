from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_base_snapshot_declares_only_artifacts_it_owns():
    registry = _json("config/v3_service_registry.json")
    base = registry["services"]["base_snapshot"]

    assert set(base["artifacts"]) == {"latest.json", "native.json"}
    assert set(base["inputs"]) == {
        "official_snapshot.json",
        "health.json",
        "team.json",
        "chips.json",
        "live.json",
        "prices.json",
        "universe.json",
        "advanced_stats_sync.json",
    }


def test_only_two_intentional_multiwriter_artifacts_remain():
    registry = _json("config/v3_service_registry.json")
    domains = _json("config/runtime/execution_domains.json")

    producers: dict[str, set[str]] = {}
    for service, spec in registry["services"].items():
        for artifact in spec.get("artifacts") or []:
            producers.setdefault(str(artifact), set()).add(str(service))

    multiwriters = {artifact: writers for artifact, writers in producers.items() if len(writers) > 1}
    assert multiwriters == {
        "prices.json": {"market_state", "price"},
        "user_report.json": {"reporting", "report_materializer"},
    }

    declared = {
        artifact: set(spec["writers"])
        for artifact, spec in domains["artifact_writer_exceptions"].items()
    }
    assert declared == multiwriters


def test_base_snapshot_consumer_files_still_have_canonical_producers():
    registry = _json("config/v3_service_registry.json")
    services = registry["services"]
    base_inputs = set(services["base_snapshot"]["inputs"])

    producers: dict[str, set[str]] = {}
    for service, spec in services.items():
        if service == "base_snapshot":
            continue
        for artifact in spec.get("artifacts") or []:
            producers.setdefault(str(artifact), set()).add(str(service))

    assert base_inputs <= set(producers)
    assert producers["health.json"] == {"official_snapshot"}
    assert producers["team.json"] == {"team_state"}
    assert producers["chips.json"] == {"team_state"}
    assert producers["live.json"] == {"live_state"}
    assert producers["universe.json"] == {"market_state"}
    assert producers["advanced_stats_sync.json"] == {"advanced_stats"}
