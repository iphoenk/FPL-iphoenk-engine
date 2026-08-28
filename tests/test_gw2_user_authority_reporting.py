import json
from pathlib import Path

from src.engines.report_transparency_overlay import _sync_current_authority


def _planning():
    return {
        "status": "PROJECTION",
        "decision_authority": "USER_OVERRIDE",
        "source": "USER_SCREENSHOT_2026-08-28T00:40:04Z",
        "gw": 2,
        "formation": "3-5-2",
        "starting_xi": [
            {"name": "Tzolakis", "position": "GK"},
            {"name": "De Cuyper", "position": "DEF"},
            {"name": "Calafiori", "position": "DEF"},
            {"name": "Kayode", "position": "DEF"},
            {"name": "Bruno Fernandes", "position": "MID"},
            {"name": "Ødegaard", "position": "MID"},
            {"name": "Tzolis", "position": "MID"},
            {"name": "Rogers", "position": "MID"},
            {"name": "M. Sangaré", "position": "MID"},
            {"name": "Haaland", "position": "FWD"},
            {"name": "João Pedro", "position": "FWD"},
        ],
        "bench": [
            {"name": "Verbruggen", "position": "GK"},
            {"name": "Robinson", "position": "DEF"},
            {"name": "Calvert-Lewin", "position": "FWD"},
            {"name": "Aina", "position": "DEF"},
        ],
        "captain": {"name": "Bruno Fernandes"},
        "vice_captain": {"name": "Haaland"},
        "active_chip": "WILDCARD",
        "estimated_points": 49.0,
        "engine_recommendation": {
            "formation": "3-5-2",
            "captain": "Haaland",
            "vice_captain": "De Cuyper",
            "estimated_points": 51.0,
        },
    }


def test_compact_serving_uses_current_user_authority_and_keeps_engine_as_challenger():
    payload = {
        "gameweek_context": {"planning": _planning()},
        "captaincy": {
            "decision": "LEAN",
            "confidence": "MEDIUM",
            "captain": "Haaland",
            "vice": "De Cuyper",
            "reason": "engine captain reason",
        },
        "action_board": [
            {"action": "LEAN", "subject": "Captain: Haaland", "trigger": "engine captain reason"},
            {"action": "HOLD", "subject": "Squad", "trigger": "no material change"},
        ],
    }

    _sync_current_authority(payload, compact_captaincy=True)

    assert payload["captaincy"]["captain"] == "Bruno Fernandes"
    assert payload["captaincy"]["vice"] == "Haaland"
    assert payload["captaincy"]["authority"] == "USER_OVERRIDE"
    assert payload["captaincy"]["reason"] == "pilihan tim saat ini; tinjau ulang hanya jika ada kabar tim atau bukti baru yang material"
    assert payload["captaincy"]["engine_challenger"]["captain"] == "Haaland"
    assert payload["captaincy"]["engine_challenger"]["vice"] == "De Cuyper"
    assert payload["captaincy"]["engine_challenger"]["reason"] == "engine captain reason"
    assert payload["current_team"]["formation"] == "3-5-2"
    assert payload["current_team"]["bench_order"] == ["Robinson", "Calvert-Lewin", "Aina"]
    assert payload["current_team"]["gk_bench"] == "Verbruggen"
    assert payload["action_board"][0]["subject"] == "Captain: Bruno Fernandes"
    assert payload["action_board"][0]["trigger"] == "ubah hanya jika ada kabar tim atau bukti baru yang material"
    assert payload["action_board"][1]["subject"] == "Squad"


def test_gw2_manual_override_matches_latest_user_team_authority():
    cfg = json.loads(Path("config/manual_lineup_override.json").read_text(encoding="utf-8"))
    assert cfg["status"] == "ACTIVE"
    assert cfg["gw"] == 2
    assert cfg["captain"] == 426
    assert cfg["vice_captain"] == 411
    assert cfg["bench_gk"] == 109
    assert cfg["bench_order"] == [254, 346, 473]
    assert cfg["starting_xi"] == [572, 115, 8, 88, 426, 15, 557, 40, 565, 411, 165]


def test_reporting_governance_blocks_internal_terms_from_human_surface():
    cfg = json.loads(Path("config/intelligence/reporting.json").read_text(encoding="utf-8"))
    forbidden = set((cfg.get("language") or {}).get("forbidden_user_presentation_tokens") or [])
    for token in {
        "user_override_active",
        "runtime_publish",
        "schema_version",
        "report_artifact_registry",
        "technical_appendix",
        "payload_type",
        "REFRESH_REQUIRED",
        "INVALID_EVIDENCE_CONTRACT",
        "PARTIAL/UNAVAILABLE",
    }:
        assert token in forbidden


def test_deadline_adaptive_schedule_is_quarter_hour():
    workflow = Path(".github/workflows/v3-runtime-fast.yml").read_text(encoding="utf-8")
    policy = json.loads(Path("config/runtime/collector_policy.json").read_text(encoding="utf-8"))
    assert 'cron: "*/15 * * * *"' in workflow
    assert policy["schedules"]["adaptive"] == "*/15 * * * *"
