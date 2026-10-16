"""P0 regression: operational history stays factual and ChatGPT remains scheduler authority."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.runtime_v6.domains.control_plane import runtime_control as runtime_module
from src.runtime_v6.runtime_control import build_operational_slots, build_runtime_control


def _natural(slot_hour: int, previous_hour: int | None = None):
    previous = (
        {"runtime_control": {
            "last_chatgpt_scheduler_cycle_at": f"2026-10-16T{previous_hour:02d}:00:00+00:00"
        }}
        if previous_hour is not None
        else {}
    )
    return build_runtime_control(
        previous,
        now=datetime(2026, 10, 16, slot_hour, 33, tzinfo=timezone.utc),
        event_name="issues",
        run_id=f"natural-{slot_hour}",
        schedule_kind="chatgpt_scheduler",
        logical_slot=f"2026-10-16T{slot_hour:02d}:00:00+00:00",
    )


def test_adjacent_natural_slots_are_green_and_never_invent_misses():
    previous = _natural(3)
    current = _natural(4, previous_hour=3)
    assert current["health"] == "GREEN"
    assert current["missed_cycle_count"] == 0
    assert current["chatgpt_scheduler_proof"] is True
    ledger = build_operational_slots(build_operational_slots({}, previous), current)
    assert ledger["summary"]["missing_operational_slots"] == 0
    assert ledger["summary"]["consecutive_successful_slots"] == 2


def test_four_missing_slots_remain_immutable_factual_observations():
    first = _natural(3)
    final = _natural(8, previous_hour=3)
    assert final["health"] == "RED"
    assert final["missed_cycle_count"] == 4
    ledger = build_operational_slots(build_operational_slots({}, first), final)
    assert ledger["summary"]["missing_operational_slots"] == 4
    assert ledger["summary"]["consecutive_successful_slots"] == 1
    assert [row["slot"] for row in ledger["slots"] if row["fulfilled_by"] == "MISSING"] == [
        f"2026-10-16T{hour:02d}:00:00+00:00" for hour in range(4, 8)
    ]


def test_duplicate_and_out_of_order_natural_slots_do_not_turn_green():
    duplicate = _natural(4, previous_hour=4)
    out_of_order = _natural(3, previous_hour=4)
    assert duplicate["health"] == "AMBER"
    assert duplicate["duplicate_scheduled_cycle"] is True
    assert duplicate["missed_cycle_count"] == 0
    assert out_of_order["health"] == "AMBER"
    assert out_of_order["out_of_order_scheduled_cycle"] is True
    assert out_of_order["missed_cycle_count"] == 0


def test_controlled_dispatch_and_report_prefetch_do_not_create_natural_proof():
    ledger = build_operational_slots({}, _natural(3))
    for kind in ("master_orchestrated", "report_prefetch"):
        control = build_runtime_control(
            {},
            now=datetime(2026, 10, 16, 4, 33, tzinfo=timezone.utc),
            event_name="workflow_dispatch",
            run_id=f"controlled-{kind}",
            schedule_kind=kind,
            logical_slot="2026-10-16T04:00:00+00:00",
        )
        assert control["chatgpt_scheduler_proof"] is False
        assert control["counts_as_completed_scheduled_slot"] is False
        ledger = build_operational_slots(ledger, control)
    assert ledger["summary"]["fulfilled_by_chatgpt"] == 1
    assert ledger["summary"]["consecutive_successful_slots"] == 1
    assert ledger["slots"][0]["run_id"] == "natural-3"


def test_main_manifest_governance_uses_configured_chatgpt_health_authority(monkeypatch, tmp_path):
    health = tmp_path / "health"
    health.mkdir()
    manifest_path = tmp_path / "manifest.json"
    previous_path = tmp_path / "previous.json"
    manifest = {"overall": "GREEN", "polling": {"scheduler_interval_minutes": 60}}
    monkeypatch.setattr(runtime_module, "MANIFEST", manifest_path)
    monkeypatch.setattr(runtime_module, "HEALTH", health)
    monkeypatch.setenv("V6_PREVIOUS_MANIFEST", str(previous_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issues")
    monkeypatch.setenv("V6_SCHEDULE_KIND", "chatgpt_scheduler")
    monkeypatch.setenv("V6_MASTER_LOGICAL_SLOT", "2026-10-16T08:00:00+00:00")
    monkeypatch.setattr(runtime_module, "_read_json", lambda path: manifest if path == manifest_path else {})
    writes = {}
    monkeypatch.setattr(runtime_module, "write_json", lambda path, value: writes.__setitem__(Path(path), value))
    assert runtime_module.main() == 0
    written = writes[manifest_path]
    governance = written["governance"]
    assert governance["chatgpt_scheduler_is_current_health_authority"] is True
    assert governance["github_scheduler_is_current_health_authority"] is False
    assert governance["legacy_github_scheduler_evidence_is_historical_only"] is True
    assert written["runtime_control_health"] == "GREEN"
    assert written["operational_reliability"]["health"] == "AMBER"
    assert written["operational_reliability"]["consecutive_successful_slots"] == 1
