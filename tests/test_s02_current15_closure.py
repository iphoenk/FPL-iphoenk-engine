from __future__ import annotations

from pathlib import Path

from src.engines import v12_integrated_report_runner as runner


OLD_GW5_IDS = [
    572, 109,
    115, 8, 31, 391, 279,
    426, 565, 40, 15, 68,
    411, 165, 346,
]

CURRENT_GW6 = {
    "goalkeepers": [
        {"element_id": 572, "display_name": "Tzolakis"},
        {"element_id": 109, "display_name": "Verbruggen"},
    ],
    "defenders": [
        {"element_id": 115, "display_name": "De Cuyper"},
        {"element_id": 8, "display_name": "Calafiori"},
        {"element_id": 31, "display_name": "Konsa"},
        {"element_id": 391, "display_name": "Gvardiol"},
        {"element_id": 279, "display_name": "Ajayi"},
    ],
    "midfielders": [
        {"element_id": 426, "display_name": "B.Fernandes"},
        {"element_id": 124, "display_name": "Pascal Groß"},
        {"element_id": 40, "display_name": "Rogers"},
        {"element_id": 15, "display_name": "Ødegaard"},
        {"element_id": 68, "display_name": "Tavernier"},
    ],
    "forwards": [
        {"element_id": 411, "display_name": "Haaland"},
        {"element_id": 165, "display_name": "João Pedro"},
        {"element_id": 346, "display_name": "Calvert-Lewin"},
    ],
    "transfer_execution_state": "EXECUTED",
    "status": "USER_CONFIRMED_CURRENT",
    "explicit_user_confirmation": True,
    "explicit_user_confirmed_at": "2026-09-23T05:54:41+00:00",
    "applicable_planning_gw": 6,
    "evidence_source_class": "USER_CONFIRMED",
    "evidence_basis": "EXPLICIT_USER_CONFIRMED_CURRENT15",
}


def _write_runtime_identity(root: Path) -> None:
    personal = root / "data/v6/personal"
    personal.mkdir(parents=True, exist_ok=True)
    stale_picks = [
        {
            "element_id": element_id,
            "squad_position": index,
            "captain": False,
            "vice_captain": False,
        }
        for index, element_id in enumerate(OLD_GW5_IDS, start=1)
    ]
    runner._write_json(
        personal / "submitted_picks.json",
        {
            "status": "AVAILABLE",
            "entry_id": 3462711,
            "gw": 5,
            "generated_at": "2026-09-24T07:17:31.862320+00:00",
            "authority": "OFFICIAL_FPL",
            "picks": stale_picks,
        },
    )
    runner._write_json(
        personal / "current_team.json",
        {
            "entry_id": 3462711,
            "gw": 5,
            "generated_at": "2026-09-24T07:17:31.433974+00:00",
            "authority": "OFFICIAL_FPL",
            "auth_state": "AUTH_EXPIRED",
            "squad_state": "SUBMITTED_PICKS_ONLY",
            "players": stale_picks,
        },
    )


def test_explicit_planning_gw_identity_beats_previous_gw_public_fallback(tmp_path: Path):
    _write_runtime_identity(tmp_path)
    state = {"confirmed_current_squad_state": CURRENT_GW6}

    resolved = runner._personal_evidence_resolution(
        tmp_path,
        state,
        planning_gw=6,
    )

    assert resolved["resolution_status"] == "CURRENT_VALID"
    assert resolved["source"] == "FPL_MASTER_STATE_V12:EXPLICIT_USER_CONFIRMED"
    assert resolved["source_class"] == "USER_CONFIRMED"
    assert resolved["gw"] == 6
    assert resolved["stale"] is False
    assert resolved["exact15"] is True
    assert len(resolved["rows"]) == 15
    ids = {int(row["element_id"]) for row in resolved["rows"]}
    assert 124 in ids
    assert 565 not in ids


def test_previous_gw_public_identity_remains_stale_without_current_confirmation(tmp_path: Path):
    _write_runtime_identity(tmp_path)

    resolved = runner._personal_evidence_resolution(
        tmp_path,
        {"confirmed_current_squad_state": {}},
        planning_gw=6,
    )

    assert resolved["resolution_status"] == "PREVIOUS_GW_IDENTITY_FALLBACK"
    assert resolved["source"] == "data/v6/personal/submitted_picks.json"
    assert resolved["gw"] == 5
    assert resolved["stale"] is True
    assert resolved["finance_allowed"] is False
    assert len(resolved["rows"]) == 15


def test_identity_only_confirmation_does_not_fabricate_private_finance(tmp_path: Path):
    _write_runtime_identity(tmp_path)
    resolved = runner._personal_evidence_resolution(
        tmp_path,
        {"confirmed_current_squad_state": CURRENT_GW6},
        planning_gw=6,
    )

    finance = runner._private_finance_context(resolved)

    assert finance["bank"] is None
    assert finance["chips"] is None
    assert finance["bank_status"] == "UNAVAILABLE"
    assert finance["purchase_price_status"] == "UNAVAILABLE"
    assert finance["sell_value_status"] == "UNAVAILABLE"
    assert finance["free_transfers"] is None
    assert finance["free_transfers_status"] == "NOT_SUPPORTED"
    assert finance["private_finance_fabricated"] is False
