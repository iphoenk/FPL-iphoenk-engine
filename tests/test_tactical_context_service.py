from __future__ import annotations

import json

from src.engines import tactical_context_service as svc
from src.models import tactical_matchup as tm


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _projection() -> dict:
    return {
        "players": [
            {
                "element": 10,
                "name": "Observed Creator",
                "team_id": 1,
                "position": "MID",
                "xpts_by_gw": [{"gw": 2, "fixtures": [{"opponent": 2, "home": True, "mean": 5.0, "std": 2.0}]}],
            }
        ]
    }


def test_materializer_uses_canonical_observed_evidence_without_fabrication(monkeypatch, tmp_path):
    _write(tmp_path / "official_snapshot.json", {
        "bootstrap": {"teams": [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}]}
    })
    _write(tmp_path / "player_features.json", {
        "contract": "PLAYER_FEATURE_CONTRACT_V1",
        "team_system_context": {
            "1": {
                "dominant_shape": "4-3-3",
                "shape_consistency": 1.0,
                "valid_matches": 1,
                "observed_matches": 1,
                "confidence": "LOW",
                "matches": [{"match_id": "m1", "valid": True, "fpl_position_shape": "4-3-3"}],
            },
            "2": {
                "dominant_shape": "4-2-3-1",
                "shape_consistency": 1.0,
                "valid_matches": 1,
                "observed_matches": 1,
                "confidence": "LOW",
                "matches": [{"match_id": "m2", "valid": True, "fpl_position_shape": "4-2-3-1"}],
            },
        },
        "players": {
            "10": {
                "element": 10,
                "name": "Observed Creator",
                "team_id": 1,
                "position": "MID",
                "tactical_role": {
                    "profile": "CREATOR_PROFILE",
                    "confidence": "LOW",
                    "sample_quality": "SINGLE_APPEARANCE",
                    "evidence_minutes": 90,
                    "metrics": {"xa_per90": 0.3},
                    "reason": "chance-creation threshold met",
                },
                "provenance": {"tactical_role": "advanced-match-source"},
            }
        },
    })
    monkeypatch.setattr(svc, "DATA", tmp_path)
    out = svc.build()

    alpha = out["team_profiles"]["teams"]["1"]
    beta = out["team_profiles"]["teams"]["2"]
    role = out["player_roles"]["players"]["10"]
    assert alpha["coach"] is None
    assert alpha["pressing"] is None
    assert beta["vulnerabilities"] == []
    assert alpha["base_formation"] == "4-3-3"
    assert alpha["evidence"]["class"] == "OBSERVED_FPL_POSITION_SHAPE"
    assert alpha["evidence"]["not_true_tactical_formation"] is True
    assert role["role"] == "CREATOR_PROFILE"
    assert role["progression_route"] is None
    assert role["return_routes"] == []
    assert out["recent_form"]["teams"] == {"1": [], "2": []}
    assert out["summary"]["status"] == "PARTIAL_INTERNAL_EVIDENCE"

    artifacts = {
        "team_profiles": out["team_profiles"],
        "player_roles": out["player_roles"],
        "recent_form": out["recent_form"],
    }
    monkeypatch.setattr(tm, "_artifact", lambda name: artifacts[name])
    projected = tm.attach_tactical_matchups(_projection(), 2)
    matchup = projected["players"][0]["tactical_matchup"]
    assert matchup["status"] == "PARTIAL"
    assert matchup["rich_opponent_context"] is False
    assert matchup["xpts_mutated"] is False
    assert projected["tactical_matchup_summary"]["ready"] == 0
    assert projected["tactical_matchup_summary"]["partial"] == 1
