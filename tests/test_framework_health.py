from __future__ import annotations

import json

from src.engines import framework_health_audit as audit_engine
from src.engines import p0_framework_health_overlay as p0_overlay
from src.engines.framework_health_audit import EXPECTED_COUNTS, REGISTRIES, _gate0, _registry_integrity
from src.utils import read_json


def test_canonical_registry_counts_and_unique_ids():
    for name, expected in EXPECTED_COUNTS.items():
        obj = read_json(REGISTRIES[name], {})
        result = _registry_integrity(name, obj)
        assert result["declared"] == expected
        assert result["integrity_ok"] is True
        assert result["duplicate_ids"] == []


def test_dss_core_numbering_is_immutable_01_to_50():
    obj = read_json(REGISTRIES["dss_core"], {})
    ids = [row["id"] for row in obj["modules"]]
    assert ids == [f"DSS-{i:02d}" for i in range(1, 51)]


def test_enhancement_numbering_is_exactly_eight():
    obj = read_json(REGISTRIES["enhancements"], {})
    ids = [row["id"] for row in obj["layers"]]
    assert ids == [f"ENH-{i:02d}" for i in range(1, 9)]


def test_gate0_preflight_is_fail_closed_but_phase_aware(tmp_path, monkeypatch):
    # Gate0's identity/eligibility checks need a universe, but the test must not
    # depend on mutable runtime data being committed to the source branch.
    lock = read_json(audit_engine.CONFIG / "locked_squad.json", {})
    team_ids: dict[str, int] = {}
    universe_players = []
    for player in lock.get("players") or []:
        team_name = str(player.get("expected_team") or "UNKNOWN")
        team_id = team_ids.setdefault(team_name, len(team_ids) + 1)
        universe_players.append({
            "element": int(player["element"]),
            "name": player.get("name") or f"P{player['element']}",
            "team_id": team_id,
            "team": team_name,
            "position": player.get("position"),
            "status": "a",
            "now_cost": int(player.get("purchase_cost") or 45),
        })
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "universe.json").write_text(json.dumps({"players": universe_players}), encoding="utf-8")
    (data_dir / "team.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(audit_engine, "DATA", data_dir)

    result = _gate0("preflight")
    assert result["counts"].get("FAIL", 0) == 0
    assert result["counts"].get("DEFERRED", 0) >= 1
    assert result["pass"] is True


def test_every_framework_item_declares_criticality_and_probe_for_intelligence_layers():
    for group in ("dss_core", "dss_extensions", "enhancements"):
        obj = read_json(REGISTRIES[group], {})
        key = "layers" if group == "enhancements" else "modules"
        for row in obj[key]:
            assert isinstance(row.get("critical"), bool)
            assert row.get("operational_probe"), row["id"]


def _write_challenger_scorecard(tmp_path, providers):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "challenger_scorecard.json").write_text(json.dumps({
        "status": "ACTIVE_INTERNAL_ONLY_EXTERNAL_DATA_ABSENT",
        "providers": providers,
        "current_comparisons": [],
        "structured_fresh_count": 0,
        "auto_scrape": False,
    }), encoding="utf-8")
    return data_dir


def test_challenger_health_is_partial_when_external_advisory_data_is_absent(tmp_path, monkeypatch):
    data_dir = _write_challenger_scorecard(tmp_path, [
        {"id": "internal", "state": "ACTIVE"},
        {"id": "fffix", "state": "NO_OBSERVATION"},
        {"id": "ffhub", "state": "NO_OBSERVATION"},
    ])
    monkeypatch.setattr(p0_overlay, "DATA", data_dir)
    status, detail = p0_overlay._challenger_probe()
    assert status == "PARTIAL"
    assert detail["external_active"] == []
    assert "no fabrication" in detail["reason"]


def test_challenger_health_accepts_active_structured_state(tmp_path, monkeypatch):
    data_dir = _write_challenger_scorecard(tmp_path, [
        {"id": "internal", "state": "ACTIVE"},
        {"id": "fffix", "state": "ACTIVE_STRUCTURED_OBSERVATION"},
        {"id": "ffhub", "state": "NO_OBSERVATION"},
    ])
    monkeypatch.setattr(p0_overlay, "DATA", data_dir)
    status, detail = p0_overlay._challenger_probe()
    assert status == "ACTIVE"
    assert detail["external_active"] == ["fffix"]


def test_challenger_health_fails_closed_on_registry_provider_mismatch(tmp_path, monkeypatch):
    data_dir = _write_challenger_scorecard(tmp_path, [
        {"id": "internal", "state": "ACTIVE"},
        {"id": "fffix", "state": "NO_OBSERVATION"},
    ])
    monkeypatch.setattr(p0_overlay, "DATA", data_dir)
    status, detail = p0_overlay._challenger_probe()
    assert status == "FAILED"
    assert detail["missing"] == ["ffhub"]
