from __future__ import annotations

from src.engines import dss_operationalization_overlay as overlay


def test_set_piece_role_probe_becomes_available_from_projection_role_evidence(monkeypatch):
    monkeypatch.setattr(
        overlay,
        "_projection_players",
        lambda: [
            {"element": 10, "set_piece_role": {"source": "OFFICIAL_FPL_BOOTSTRAP", "direct_freekicks_order": 1}},
            {"element": 20},
        ],
    )
    ok, detail = overlay._optional_player_role(
        {
            "keys": ["set_piece_share", "set_piece_role"],
            "fallback": "neutral set-piece adjustment",
        }
    )
    assert ok is True
    assert detail["evidence_state"] == "AVAILABLE"
    assert detail["explicit_role_players"] == 1
    assert detail["missing_role_evidence_fabricated"] is False


def test_penalty_role_probe_remains_safe_fallback_when_official_role_is_absent(monkeypatch):
    monkeypatch.setattr(
        overlay,
        "_projection_players",
        lambda: [{"element": 10}, {"element": 20}],
    )
    ok, detail = overlay._optional_player_role(
        {
            "keys": ["penalty_share", "penalty_role"],
            "fallback": "neutral penalty adjustment",
        }
    )
    assert ok is True
    assert detail["evidence_state"] == "UNAVAILABLE_WITH_SAFE_FALLBACK"
    assert detail["explicit_role_players"] == 0
    assert detail["missing_role_evidence_fabricated"] is False
