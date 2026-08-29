from datetime import datetime, timezone

import pytest

from src.engines import v4_submitted_state as submitted


def _picks(chip="wildcard"):
    rows = []
    for position in range(1, 16):
        rows.append({
            "element": 100 + position,
            "position": position,
            "multiplier": 1 if position <= 11 else 0,
            "is_captain": position == 1,
            "is_vice_captain": position == 2,
        })
    return {"picks": rows, "active_chip": chip, "entry_history": {"event": 2}}


def test_official_submitted_shape_preserves_xi_bench_captain_vice_chip():
    core = submitted._official_core(_picks())
    assert len(core["squad_elements"]) == 15
    assert core["starting_xi"] == list(range(101, 112))
    assert core["bench"] == list(range(112, 116))
    assert core["captain"] == 101
    assert core["vice_captain"] == 102
    assert core["active_chip"] == "wildcard"


def test_predeadline_archive_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(submitted, "ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(submitted, "_baseline_for_gw", lambda gw: {"applicable": False, "target_gw": None, "squad_elements": [], "starting_xi": [], "bench": [], "captain": None, "vice_captain": None, "chip": None, "source": "TEST"})
    with pytest.raises(RuntimeError, match="pre-deadline"):
        submitted.persist_submitted_state(
            2,
            "2026-08-29T11:30:00+00:00",
            _picks(),
            now=datetime(2026, 8, 29, 11, 29, tzinfo=timezone.utc),
        )


def test_archive_is_immutable_and_conflicting_later_official_payload_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(submitted, "ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(submitted, "_baseline_for_gw", lambda gw: {"applicable": False, "target_gw": None, "squad_elements": [], "starting_xi": [], "bench": [], "captain": None, "vice_captain": None, "chip": None, "source": "TEST"})
    now = datetime(2026, 8, 29, 11, 31, tzinfo=timezone.utc)
    first = submitted.persist_submitted_state(2, "2026-08-29T11:30:00+00:00", _picks(), now=now)
    again = submitted.persist_submitted_state(2, "2026-08-29T11:30:00+00:00", _picks(), now=now)
    assert again == first
    ok, reason = submitted.submitted_state_integrity(first, 2)
    assert ok is True and reason is None
    changed = _picks()
    changed["picks"][10]["element"] = 999
    with pytest.raises(RuntimeError, match="conflicts"):
        submitted.persist_submitted_state(2, "2026-08-29T11:30:00+00:00", changed, now=now)
